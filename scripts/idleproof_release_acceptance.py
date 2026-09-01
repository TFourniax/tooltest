from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def check(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    proc = run(args, cwd=cwd, env=env, input_text=input_text, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def git(repo: Path, *args: str) -> str:
    return check(["git", *args], cwd=repo).stdout.strip()


def dw(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    # This script is executed only after the exact release wheel has been installed. Running through
    # the module entry point avoids accidentally exercising checkout-local source code while the
    # nested `dw portal` / `dw setup` calls must still locate the installed `idleproof` entry point.
    return run(
        [sys.executable, "-m", "diffwitness.entry", *args],
        cwd=repo,
        env=env,
        input_text=input_text,
        timeout=timeout,
    )


def require(condition: bool, message: str, proc: subprocess.CompletedProcess[str] | None = None) -> None:
    if condition:
        return
    detail = ""
    if proc is not None:
        detail = f"\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    raise RuntimeError(message + detail)


def parse_json(proc: subprocess.CompletedProcess[str], label: str) -> dict:
    require(proc.returncode == 0, f"{label} failed", proc)
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} did not emit JSON: {exc}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}") from exc
    require(isinstance(value, dict), f"{label} JSON root is not an object", proc)
    return value


def evidence_command() -> str:
    parts = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


class FakeProvider:
    def __init__(self) -> None:
        self.requests = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                owner.requests += 1
                length = int(self.headers.get("content-length") or "0")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                messages = body.get("messages") or []
                user_message = messages[1]["content"]
                prompt = json.loads(user_message)
                units = prompt.get("units") or []
                if not units:
                    self.send_response(500)
                    self.end_headers()
                    return
                unit_id = units[0]["id"]
                provider_content = json.dumps(
                    {
                        "rewrites": [
                            {
                                "id": unit_id,
                                "text": "Clearer wording of the same evidence-backed statement.",
                            },
                            {"id": "invented:999", "text": "Everything is definitely safe."},
                        ]
                    }
                )
                response = json.dumps({"choices": [{"message": {"content": provider_content}}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1/chat/completions?should_not_be_displayed=secret"

    def __enter__(self) -> "FakeProvider":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class FakePortal:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                length = int(self.headers.get("content-length") or "0")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                owner.requests.append(
                    {
                        "authorization": self.headers.get("authorization"),
                        "body": body,
                    }
                )
                status_name = "accepted" if len(owner.requests) == 1 else "duplicate"
                response = json.dumps(
                    {
                        "schema": "idleproof.portal-ingest-ack.v1",
                        "status": status_name,
                        "snapshotId": body.get("snapshotId"),
                    }
                ).encode("utf-8")
                self.send_response(202 if status_name == "accepted" else 200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/functions/v1/idleproof-ingest"

    def __enter__(self) -> "FakePortal":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def build_guarded_fixture(root: Path) -> Path:
    repo = root / "project"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "idleproof-release@diffwitness.local")
    git(repo, "config", "user.name", "IdleProof Release Rehearsal")
    marker = "RAW_SOURCE_MARKER_MUST_NOT_REACH_PROVIDER_7f193c"
    (repo / "app.py").write_text(
        f"# {marker}\ndef add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text(
        "import unittest\nfrom app import add\n\n"
        "class AddTests(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "buggy baseline")

    agent_script = (
        "from pathlib import Path; "
        f"Path('app.py').write_text('# {marker}\\ndef add(a, b):\\n    return a + b\\n', encoding='utf-8')"
    )
    cert = root / "proof.json"
    guard = dw(
        repo,
        "guard",
        "--repo",
        str(repo),
        "--test",
        evidence_command(),
        "--policy",
        "strict",
        "--strategy",
        "exhaustive",
        "--stability-runs",
        "2",
        "--certificate",
        str(cert),
        "--no-debt",
        "--",
        sys.executable,
        "-c",
        agent_script,
        timeout=180,
    )
    require(guard.returncode == 0, "installed wheel Guard could not accept the witnessed bugfix", guard)
    require("PROOF ACCEPTED" in f"{guard.stdout}\n{guard.stderr}", "Guard acceptance was not visible", guard)
    artifact = repo / ".git" / "diffwitness" / "idleproof-explanation.json"
    require(artifact.is_file(), "Guard did not persist the deterministic IdleProof explanation artifact", guard)
    return repo


def rehearse_bundled_setup_and_portal(repo: Path) -> None:
    idleproof_executable = shutil.which("idleproof")
    require(bool(idleproof_executable), "release wheel did not install the bundled idleproof executable")
    version = check([str(idleproof_executable), "--version"], cwd=repo)
    require("bundled with DiffWitness" in version.stdout, "idleproof executable is not the bundled sidecar", version)

    setup = parse_json(
        dw(repo, "setup", "install", "--agent", "all", "--json"),
        "bundled dw setup install",
    )
    require(setup.get("healthy") is True, "dw setup did not become healthy")
    require(setup.get("expectedAdapters") == ["claude", "codex", "cursor"], "dw setup did not install all requested adapters")
    local_id = setup.get("localProjectId")
    require(isinstance(local_id, str) and len(local_id) == 24, "dw setup did not create a stable local project id")

    status = parse_json(dw(repo, "setup", "status", "--json"), "bundled dw setup status")
    require(status.get("healthy") is True, "dw setup status did not verify installed hooks")
    require(status.get("localProjectId") == local_id, "local project identity drifted after setup")

    identity = parse_json(dw(repo, "portal", "id", "--json"), "dw portal id")
    require(identity.get("localId") == local_id, "dw portal id did not reuse setup local identity")
    compatibility_identity = parse_json(dw(repo, "portal", "identity", "--json"), "dw portal identity alias")
    require(compatibility_identity.get("localId") == local_id, "compatibility identity alias drifted")

    local_snapshot = parse_json(dw(repo, "portal", "snapshot", "--json"), "dw portal bounded snapshot")
    snapshot = local_snapshot.get("snapshot") if local_snapshot.get("schema") == "idleproof.portal-sync.v1" else local_snapshot
    encoded_local = json.dumps(snapshot, ensure_ascii=False)
    require(snapshot.get("schema") == "idleproof.portal-snapshot.v1", "dw portal snapshot schema drifted")
    require("RAW_SOURCE_MARKER_MUST_NOT_REACH_PROVIDER_7f193c" not in encoded_local, "raw source leaked into local Portal snapshot")
    require(snapshot.get("privacy", {}).get("sourceCodeIncluded") is False, "Portal snapshot claims source code is included")
    require(snapshot.get("assurance", {}).get("proof", {}).get("accepted") is True, "accepted Guard proof was not preserved for Portal")

    with FakePortal() as portal:
        device_token = "ipd_abcdefghijklmnopqrstuvwxyz0123456789"
        configured = parse_json(
            dw(
                repo,
                "portal",
                "configure",
                "--endpoint",
                portal.endpoint,
                "--token-stdin",
                "--json",
                input_text=device_token + "\n",
            ),
            "dw portal configure with hidden/stdin credential",
        )
        require(configured.get("tokenMode") == "local-file", "stdin credential was not placed in local secret storage")
        token_path = repo / ".git" / "diffwitness" / "portal-device-token"
        require(token_path.is_file(), "stdin credential was not persisted under .git metadata")
        require(device_token not in (repo / ".idleproof" / "portal.json").read_text(encoding="utf-8"), "device token leaked into project config")
        if os.name != "nt":
            require((token_path.stat().st_mode & 0o077) == 0, "local device token permissions are broader than owner-only")

        first = parse_json(dw(repo, "portal", "sync", "--json"), "first dw portal sync")
        second = parse_json(dw(repo, "portal", "sync", "--json"), "idempotent dw portal sync")
        require(first.get("status") == "accepted", "first Portal sync was not accepted")
        require(second.get("status") == "duplicate", "second identical Portal sync was not idempotent")
        require(len(portal.requests) == 2, "Portal rehearsal did not make the expected two scoped requests")
        require(portal.requests[0]["authorization"] == f"Bearer {device_token}", "Portal sync did not use the scoped device token")
        uploaded = json.dumps(portal.requests[0]["body"], ensure_ascii=False)
        require("RAW_SOURCE_MARKER_MUST_NOT_REACH_PROVIDER_7f193c" not in uploaded, "raw source leaked over Portal transport")
        require('"rawPromptIncluded": true' not in uploaded, "Portal transport marked raw prompt as included")
        require('"rawDiffIncluded": true' not in uploaded, "Portal transport marked raw diff as included")

    disconnected = parse_json(dw(repo, "portal", "disconnect", "--json"), "dw portal disconnect")
    require(disconnected.get("configured") is False, "Portal disconnect did not clear configuration")
    require(not (repo / ".git" / "diffwitness" / "portal-device-token").exists(), "Portal disconnect left the scoped token behind")
    require((repo / ".git" / "diffwitness" / "change-envelope.json").is_file(), "Portal disconnect erased authoritative evidence")

    uninstall = parse_json(dw(repo, "setup", "uninstall", "--json"), "bundled dw setup uninstall")
    require(uninstall.get("installed") is False, "dw setup uninstall did not report removal")
    require((repo / ".idleproof" / "project.json").is_file(), "setup uninstall erased stable project identity/history")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="idleproof-release-acceptance-") as td:
        root = Path(td)
        repo = build_guarded_fixture(root)

        deterministic_proc = dw(repo, "explain", "--repo", str(repo), "--json")
        deterministic = parse_json(deterministic_proc, "deterministic dw explain")
        require(deterministic.get("schema") == "idleproof.explanation.v2", "unexpected deterministic explanation schema")
        require(deterministic.get("source") == "deterministic", "deterministic explanation source drifted")
        provenance = deterministic.get("provenance") or {}
        require(provenance.get("llm_used") is False, "deterministic explanation unexpectedly used an LLM")
        require(provenance.get("network_required") is False, "deterministic explanation unexpectedly requires network")
        require(provenance.get("claims_are_evidence_bounded") is True, "deterministic explanation lost evidence boundary")
        require(deterministic.get("proof", {}).get("accepted") is True, "accepted proof was not preserved in explanation")
        encoded = json.dumps(deterministic, ensure_ascii=False)
        require("RAW_SOURCE_MARKER_MUST_NOT_REACH_PROVIDER_7f193c" not in encoded, "raw source leaked into deterministic explanation payload")

        session_proc = dw(repo, "explain", "--repo", str(repo), "--engine", "agent-session")
        session = parse_json(session_proc, "agent-session context")
        require(session.get("canonical_source") == "deterministic", "agent-session route changed canonical source")
        require(session.get("cost_owner") == "user-session", "agent-session cost ownership drifted")
        require(session.get("diffwitness_managed_api_used") is False, "agent-session route marked managed inference as used")
        require("RAW_SOURCE_MARKER_MUST_NOT_REACH_PROVIDER_7f193c" not in json.dumps(session), "raw source leaked into bounded agent-session context")

        managed_proc = dw(repo, "explain", "--repo", str(repo), "--engine", "managed", "--json")
        managed = parse_json(managed_proc, "managed OSS fallback")
        require(managed.get("source") == "deterministic", "OSS managed request did not fall back to deterministic")
        require("Managed AI is deliberately unavailable" in managed_proc.stderr, "OSS managed rejection was not explicit", managed_proc)
        require("No DiffWitness-paid API was contacted" in managed_proc.stderr, "OSS managed fallback did not state the cost boundary", managed_proc)

        with FakeProvider() as provider:
            custom_args = (
                "explain",
                "--repo",
                str(repo),
                "--engine",
                "custom",
                "--endpoint",
                provider.endpoint,
                "--model",
                "idleproof-release-rehearsal",
                "--json",
            )
            first_proc = dw(repo, *custom_args)
            first = parse_json(first_proc, "first user-owned custom inference")
            require(provider.requests == 1, "first user-owned inference did not make exactly one provider request")
            require(first.get("canonical_source") == "deterministic", "user-owned AI replaced deterministic canonical source")
            require(first.get("cost_owner") == "user", "user-owned provider cost ownership drifted")
            require(first.get("diffwitness_managed_api_used") is False, "user-owned provider was marked as DiffWitness managed")
            require("should_not_be_displayed" not in str(first.get("provider_endpoint")), "provider URL query data leaked into output")
            units = first.get("units") or []
            require(units and any(unit.get("presentation_only") is True for unit in units), "provider rewrite was not labelled presentation-only")
            require(all(unit.get("original") for unit in units), "AI presentation removed deterministic originals")
            require(all(unit.get("id") != "invented:999" for unit in units), "provider invented a new evidence unit")

            second_proc = dw(repo, *custom_args)
            second = parse_json(second_proc, "cached user-owned custom inference")
            require(provider.requests == 1, "identical second inference bypassed the local cache")
            require(second.get("cache") == "hit", "second inference was not reported as a cache hit")

        cache_path = repo / ".git" / "diffwitness" / "idleproof-ai-cache.json"
        require(cache_path.is_file(), "user-owned inference cache was not stored under .git")
        require(not (repo / "idleproof-ai-cache.json").exists(), "user-owned inference cache polluted project source")

        env = os.environ.copy()
        env["DIFFWITNESS_MANAGED_SECRET"] = "must-never-be-read"
        forbidden_key = dw(
            repo,
            "explain",
            "--repo",
            str(repo),
            "--engine",
            "custom",
            "--endpoint",
            "http://127.0.0.1:9/v1/chat/completions",
            "--model",
            "blocked",
            "--api-key-env",
            "DIFFWITNESS_MANAGED_SECRET",
            "--json",
            env=env,
        )
        forbidden = parse_json(forbidden_key, "managed-credential namespace rejection")
        require(forbidden.get("source") == "deterministic", "forbidden managed credential did not fail closed")
        require("cannot read DiffWitness-managed provider credentials" in forbidden_key.stderr, "managed credential rejection was not explicit", forbidden_key)

        rehearse_bundled_setup_and_portal(repo)

    print(
        "IDLEPROOF RELEASE ACCEPTANCE PASS · installed deterministic + agent-session + managed fallback + "
        "user-owned provider/cache + bundled setup + scoped Portal sync boundaries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
