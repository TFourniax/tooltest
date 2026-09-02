from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float = 120.0,
    input_text: str | None = None,
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


def check(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: float = 120.0) -> str:
    proc = run(args, cwd=cwd, env=env, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def require(condition: bool, message: str, proc: subprocess.CompletedProcess[str] | None = None) -> None:
    if condition:
        return
    detail = "" if proc is None else f"\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    raise RuntimeError(message + detail)


def git(repo: Path, *args: str) -> str:
    return check(["git", *args], cwd=repo)


def executable_in_venv(venv_dir: Path, name: str) -> Path:
    scripts = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_dir / scripts / f"{name}{suffix}"


def evidence_command(python: Path) -> str:
    parts = [str(python), "-m", "unittest", "discover", "-s", "tests", "-q"]
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def install_exact_artifacts(root: Path, idleproof_repo: Path) -> tuple[Path, Path, Path, Path, Path | None]:
    artifacts = root / "artifacts"
    artifacts.mkdir()
    check(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "--wheel-dir", str(artifacts)],
        cwd=ROOT,
        timeout=180,
    )
    wheels = sorted(artifacts.glob("diffwitness-*.whl"))
    require(len(wheels) == 1, f"expected exactly one DiffWitness wheel, found {len(wheels)}")

    pyenv = root / "python-consumer"
    venv.EnvBuilder(with_pip=True, clear=True).create(pyenv)
    python = executable_in_venv(pyenv, "python")
    dw = executable_in_venv(pyenv, "dw")
    check([str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheels[0])], cwd=root, timeout=120)
    require(dw.is_file(), "installed DiffWitness wheel has no dw console entrypoint")

    npm = shutil.which("npm")
    node = shutil.which("node")
    require(bool(npm), "npm is required for the exact IdleProof sidecar artifact journey")
    require(bool(node), "node is required for the exact IdleProof sidecar artifact journey")
    packed = json.loads(check([str(npm), "pack", "--json"], cwd=idleproof_repo, timeout=120))
    require(isinstance(packed, list) and packed and packed[0].get("filename"), "npm pack did not return an IdleProof artifact")
    tarball = idleproof_repo / packed[0]["filename"]

    consumer = root / "node-consumer"
    consumer.mkdir()
    check([str(npm), "init", "-y"], cwd=consumer)
    check([str(npm), "install", "--ignore-scripts", "--no-audit", "--no-fund", str(tarball)], cwd=consumer, timeout=120)
    package_root = consumer / "node_modules" / "idleproof"
    idleproof_bin = package_root / "bin" / "idleproof.mjs"
    hook_bin = package_root / "bin" / "idleproof-hook.mjs"
    require(idleproof_bin.is_file(), "installed IdleProof sidecar artifact has no CLI")
    require(hook_bin.is_file(), "installed IdleProof sidecar artifact has no convergent native hook")
    return python, dw, Path(str(node)), idleproof_bin, tarball


def create_idleproof_shim(root: Path, *, node: Path, idleproof_bin: Path, invocation_log: Path) -> Path:
    shim_dir = root / "shim"
    shim_dir.mkdir()
    if os.name == "nt":
        shim = shim_dir / "idleproof.cmd"
        shim.write_text(
            f'@echo off\r\necho %*>>"{invocation_log}"\r\n"{node}" "{idleproof_bin}" %*\r\n',
            encoding="utf-8",
        )
    else:
        shim = shim_dir / "idleproof"
        shim.write_text(
            "#!/usr/bin/env sh\n"
            f"printf '%s\\n' \"$*\" >> {shlex.quote(str(invocation_log))}\n"
            f"exec {shlex.quote(str(node))} {shlex.quote(str(idleproof_bin))} \"$@\"\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
    return shim


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def last_json(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line.strip())
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def run_native_hook(
    *,
    node: Path,
    hook_bin: Path,
    project: Path,
    env: dict[str, str],
    session: str,
    event: dict,
    provider: str = "claude",
    timeout: float = 240.0,
) -> tuple[subprocess.CompletedProcess[str], dict | None]:
    require(provider in {"claude", "codex"}, f"unsupported native smoke provider: {provider}")
    payload = {"cwd": str(project), "session_id": session, **event}
    proc = run(
        [str(node), str(hook_bin), provider],
        cwd=project,
        env=env,
        timeout=timeout,
        input_text=json.dumps(payload) + "\n",
    )
    require(proc.returncode == 0, f"native {provider} hook failed for {event.get('hook_event_name')}", proc)
    return proc, last_json(proc.stdout)


def setup_status_json(*, dw: Path, idleproof_shim: Path, project: Path, env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], dict]:
    status = run(
        [str(dw), "setup", "status", "--idleproof-command", str(idleproof_shim), "--json"],
        cwd=project,
        env=env,
        timeout=30,
    )
    require(status.returncode == 0, "dw setup status rejected the freshly installed integration", status)
    try:
        payload = json.loads(status.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"dw setup status returned invalid JSON: {status.stdout[:1000]}") from exc
    return status, payload


def assert_successful_stop(
    proc: subprocess.CompletedProcess[str],
    payload: dict | None,
    *,
    label: str,
) -> str:
    """Validate the current Claude/Codex success contract without inventing an allow decision.

    Native Stop success is represented by a successful hook process plus optional informational
    output. A top-level decision is reserved for an actual block. Re-introducing `approve` here
    would recreate the provider-contract bug found in human qualification (#25/#30).
    """
    require(payload is not None, f"{label} produced no structured native handoff", proc)
    assert payload is not None
    require("decision" not in payload, f"{label} emitted an unsupported top-level success decision", proc)
    message = str(payload.get("systemMessage") or "")
    require("Proof accepted" in message, f"{label} did not surface Proof acceptance", proc)
    return message


def assert_no_unrelated_auth_claim(repo: Path, message: str) -> None:
    """Regression gate for the calculator false-positive found during release qualification."""
    lower = message.lower()
    for forbidden in (
        "identity and permissions",
        "who the user is",
        "what that user is allowed to do",
        "authenticated-but-unauthorized",
    ):
        require(forbidden not in lower, f"IdleProof fabricated unrelated auth semantics in calculator handoff: {forbidden}")

    receipt = read_json(repo / ".idleproof" / "receipt.json")
    concepts = {
        str(item.get("id") or "")
        for item in (receipt.get("session", {}).get("concepts") or [])
        if isinstance(item, dict)
    }
    require("auth" not in concepts, "calculator-only task was incorrectly persisted as an auth concept")


def assert_integrated_envelope(repo: Path, *, previous_change_id: str | None = None) -> str:
    envelope_path = repo / ".git" / "diffwitness" / "change-envelope.json"
    receipt_path = repo / ".idleproof" / "receipt.json"
    require(envelope_path.is_file(), "native DiffWitness handoff did not persist the integrated change envelope")
    require(receipt_path.is_file(), "understanding sidecar did not persist its exact task receipt")
    envelope = read_json(envelope_path)
    receipt = read_json(receipt_path)
    change_id = str(envelope.get("change_id") or "")
    require(change_id.startswith("dwchg_") and len(change_id) == 30, "integrated envelope has no canonical change id")
    if previous_change_id is not None:
        require(change_id != previous_change_id, "a later task reused the previous canonical change id")
    require(envelope.get("proof", {}).get("accepted") is True, "integrated envelope lost accepted DiffWitness proof")
    require(isinstance(envelope.get("debt", {}).get("points"), int), "integrated envelope has no bounded Debt Ledger points")
    require(isinstance(envelope.get("debt", {}).get("open_lineages"), list), "integrated envelope has no bounded debt lineage list")
    understanding = envelope.get("understanding")
    require(isinstance(understanding, dict), "exact understanding receipt was not correlated into the envelope")
    require(str(understanding.get("receipt_digest") or "").startswith("sha256:"), "understanding receipt is not digest-bound")
    require(envelope.get("privacy", {}).get("code_uploaded") is False, "envelope privacy boundary claims source upload")
    require(envelope.get("privacy", {}).get("contains_prompt_text") is False, "envelope privacy boundary contains prompt text")
    receipt_session = receipt.get("session", {})
    receipt_change = receipt_session.get("change", {})
    require(receipt_change.get("changeId") == change_id, "understanding and DiffWitness did not converge on the same dwchg identity")
    receipt_proof = receipt_session.get("proof", {})
    require(receipt_proof.get("changeId") == change_id, "receipt proof identity diverges from exact change identity")
    require(str((receipt_session.get("task") or {}).get("id") or "").startswith("dwtask_"), "receipt has no stable dwtask identity")
    return change_id


def assert_continuity(repo: Path, change_id: str) -> None:
    # Project Continuity intentionally shares the Git-common DiffWitness root with the frozen
    # change envelope: .git/diffwitness/events.jsonl + rebuildable state.db. Keeping this assertion
    # on the public continuity contract (not an invented subdirectory) catches real missing events.
    journal = repo / ".git" / "diffwitness" / "events.jsonl"
    require(journal.is_file(), "native handoff produced no Project Continuity event journal")
    text = journal.read_text(encoding="utf-8", errors="replace")
    require(change_id in text, "Project Continuity journal is not correlated to the canonical change id")
    for event_type in ("change.observed", "proof.completed", "debt.snapshot"):
        require(f'"event_type":"{event_type}"' in text, f"Project Continuity journal is missing {event_type}")
    require((repo / ".git" / "diffwitness" / "state.db").is_file(), "Project Continuity did not materialize its rebuildable state")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exercise installed DiffWitness + sidecar through the native alpha setup path.")
    parser.add_argument("--idleproof-repo", required=True, type=Path)
    args = parser.parse_args(argv)
    idleproof_repo = args.idleproof_repo.resolve()
    require((idleproof_repo / "package.json").is_file(), "--idleproof-repo does not contain package.json")

    tarball: Path | None = None
    with tempfile.TemporaryDirectory(prefix="integrated-product-smoke-") as td:
        root = Path(td)
        try:
            python, dw, node, idleproof_bin, tarball = install_exact_artifacts(root, idleproof_repo)
            hook_bin = idleproof_bin.parent / "idleproof-hook.mjs"
            invocation_log = root / "idleproof-invocations.log"
            idleproof_shim = create_idleproof_shim(root, node=node, idleproof_bin=idleproof_bin, invocation_log=invocation_log)
            env = os.environ.copy()
            env["PATH"] = str(idleproof_shim.parent) + os.pathsep + str(dw.parent) + os.pathsep + env.get("PATH", "")
            env["DIFFWITNESS_BIN"] = str(dw)

            project = root / "project"
            project.mkdir()
            git(project, "init", "-q")
            git(project, "config", "user.email", "integrated-smoke@diffwitness.local")
            git(project, "config", "user.name", "Integrated Product Smoke")
            (project / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            tests = project / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text(
                "import unittest\nfrom app import add\n\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            test_command = evidence_command(python)
            (project / ".diffwitness.toml").write_text(
                "[diffwitness]\n"
                f"test = {json.dumps(test_command)}\n"
                "stability_runs = 1\n"
                "max_total_seconds = 120\n\n"
                "[debt]\n"
                "max_total = 1000\n"
                "max_per_change = 1000\n",
                encoding="utf-8",
            )
            git(project, "add", "-A")
            git(project, "commit", "-qm", "buggy baseline")

            setup = run(
                [str(dw), "setup", "--agent", "all", "--idleproof-command", str(idleproof_shim)],
                cwd=project,
                env=env,
                timeout=120,
            )
            require(setup.returncode == 0, "dw setup did not configure the exact installed artifacts", setup)
            require(
                "DiffWitness is ready" not in setup.stdout,
                "setup claimed full readiness before Codex provider trust/observation",
                setup,
            )
            status, status_json = setup_status_json(dw=dw, idleproof_shim=idleproof_shim, project=project, env=env)
            require(status_json.get("healthy") is True, "dw setup status is not healthy", status)
            require(status_json.get("expectedAdapters") == ["claude", "codex", "cursor"], "dw setup did not configure all supported adapters")
            native = status_json.get("nativeActivation") or {}
            require(native.get("observedAdapters") == [], "fresh installation fabricated a live native provider observation", status)
            require("codex" in (native.get("pendingTrustAdapters") or []), "fresh Codex setup did not expose provider trust as pending", status)
            require(native.get("fullyObserved") is False, "fresh integration incorrectly claimed all native providers were observed", status)

            integration_config = read_json(project / ".idleproof" / "diffwitness.json")
            require(integration_config.get("schema") == "diffwitness.integration-config.v1", "setup did not write canonical integration config")
            require(not (project / ".idleproof" / "defitness.json").exists(), "setup left the experimental product-name config behind")
            require("defitness" not in json.dumps(integration_config).lower(), "canonical setup config still exposes the experimental product name")
            claude_settings = read_json(project / ".claude" / "settings.local.json")
            require("idleproof-hook.mjs" in json.dumps(claude_settings), "dw setup did not install the convergent Claude hook")

            # Directly exercising the installed Codex hook represents the provider actually running
            # an already-approved project hook. DiffWitness itself never edits provider trust state;
            # liveness becomes observed only because this native callback reached the core.
            run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session="native-codex-activation",
                provider="codex",
                event={"hook_event_name": "SessionStart"},
            )
            status_after_codex, status_after_codex_json = setup_status_json(
                dw=dw,
                idleproof_shim=idleproof_shim,
                project=project,
                env=env,
            )
            native_after_codex = status_after_codex_json.get("nativeActivation") or {}
            require("codex" in (native_after_codex.get("observedAdapters") or []), "executed Codex SessionStart was not recorded as observed", status_after_codex)
            require("codex" not in (native_after_codex.get("pendingTrustAdapters") or []), "Codex remained trust-pending after its hook actually executed", status_after_codex)

            session1 = "native-alpha-fix"
            run_native_hook(node=node, hook_bin=hook_bin, project=project, env=env, session=session1, event={"hook_event_name": "SessionStart"})
            _, prompt1 = run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session=session1,
                event={"hook_event_name": "UserPromptSubmit", "prompt": "Fix add so the regression test passes without unrelated changes"},
            )
            require(prompt1 is not None, "native UserPromptSubmit produced no integrated context")
            run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session=session1,
                event={"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(project / "app.py")}},
            )
            (project / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session=session1,
                event={"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(project / "app.py")}},
            )
            stop1_proc, stop1 = run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session=session1,
                event={"hook_event_name": "Stop"},
            )
            stop1_message = assert_successful_stop(stop1_proc, stop1, label="native task handoff")
            first_change_id = assert_integrated_envelope(project)
            assert_no_unrelated_auth_claim(project, stop1_message)
            assert_continuity(project, first_change_id)

            # Do not commit the first task. Add a new failing regression test before SessionStart as
            # ordinary pre-existing human work. The second agent session therefore starts from an
            # exact dirty baseline containing both the prior fix and the new failing test. Only the
            # later implementation change may be attributed to this task.
            (tests / "test_app.py").write_text(
                "import unittest\nfrom app import add, multiply\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self): self.assertEqual(add(2, 3), 5)\n"
                "    def test_multiply(self): self.assertEqual(multiply(4, 5), 20)\n",
                encoding="utf-8",
            )
            dirty_status = git(project, "status", "--porcelain")
            require("app.py" in dirty_status and "tests/test_app.py" in dirty_status, "fixture did not create the intended dirty baseline")

            session2 = "native-alpha-dirty-regression"
            run_native_hook(node=node, hook_bin=hook_bin, project=project, env=env, session=session2, event={"hook_event_name": "SessionStart"})
            _, prompt2 = run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session=session2,
                event={"hook_event_name": "UserPromptSubmit", "prompt": "Implement multiply so the new regression passes; preserve the existing add fix"},
            )
            require(prompt2 is not None, "dirty-baseline task produced no integrated context")
            run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session=session2,
                event={"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(project / "app.py")}},
            )
            (project / "app.py").write_text(
                "def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return a * b\n",
                encoding="utf-8",
            )
            run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session=session2,
                event={"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(project / "app.py")}},
            )
            stop2_proc, stop2 = run_native_hook(
                node=node,
                hook_bin=hook_bin,
                project=project,
                env=env,
                session=session2,
                event={"hook_event_name": "Stop"},
            )
            assert_successful_stop(stop2_proc, stop2, label="dirty-baseline native handoff")
            second_change_id = assert_integrated_envelope(project, previous_change_id=first_change_id)
            assert_continuity(project, second_change_id)

            invocations = invocation_log.read_text(encoding="utf-8") if invocation_log.exists() else ""
            require("integration install" in invocations, "dw setup never exercised the installed sidecar integration API")
            require("portal assurance --envelope" in invocations, "native DiffWitness handoff never exercised the installed Portal assurance bridge")
            require(" guard " not in f" {invocations} ", "native alpha journey unexpectedly relied on dw guard")

            uninstall = run(
                [str(dw), "setup", "uninstall", "--idleproof-command", str(idleproof_shim)],
                cwd=project,
                env=env,
                timeout=60,
            )
            require(uninstall.returncode == 0, "dw setup uninstall failed", uninstall)
            require(not (project / ".idleproof" / "diffwitness.json").exists(), "uninstall left the integration config armed")
            require((project / ".idleproof" / "receipt.json").is_file(), "uninstall destroyed historical understanding evidence")
            require((project / ".git" / "diffwitness" / "change-envelope.json").is_file(), "uninstall destroyed historical Proof/Debt evidence")

            print(
                "INTEGRATED PRODUCT SMOKE PASS · exact wheel + exact sidecar artifact · setup trust lifecycle · "
                "native hooks without guard · dirty baseline · UNDERSTAND/PROVE/OWE/CONTINUITY · uninstall preserves evidence"
            )
            return 0
        finally:
            if tarball is not None:
                try:
                    tarball.unlink(missing_ok=True)
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
