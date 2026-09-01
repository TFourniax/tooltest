from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float = 300.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
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
    timeout: float = 300.0,
) -> str:
    proc = run(args, cwd=cwd, env=env, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def require(
    condition: bool,
    message: str,
    proc: subprocess.CompletedProcess[str] | None = None,
) -> None:
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


def bin_in_node_consumer(consumer: Path, name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    return consumer / "node_modules" / ".bin" / f"{name}{suffix}"


def build_exact_consumers(root: Path, idleproof_repo: Path) -> tuple[Path, Path, Path]:
    artifacts = root / "artifacts"
    artifacts.mkdir()
    check(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "--wheel-dir", str(artifacts)],
        cwd=ROOT,
        timeout=240,
    )
    wheels = sorted(artifacts.glob("diffwitness-*.whl"))
    require(len(wheels) == 1, f"expected one DiffWitness wheel, found {len(wheels)}")

    pyenv = root / "python-consumer"
    venv.EnvBuilder(with_pip=True, clear=True).create(pyenv)
    python = executable_in_venv(pyenv, "python")
    check(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])],
        cwd=root,
        timeout=180,
    )

    npm = shutil.which("npm")
    require(bool(npm), "npm is required for the exact IdleProof package acceptance journey")
    packed = json.loads(check([str(npm), "pack", "--json"], cwd=idleproof_repo, timeout=180))
    require(
        isinstance(packed, list) and packed and packed[0].get("filename"),
        "npm pack returned no IdleProof artifact",
    )
    tarball = idleproof_repo / packed[0]["filename"]
    consumer = root / "node-consumer"
    consumer.mkdir()
    check([str(npm), "init", "-y"], cwd=consumer)
    check(
        [str(npm), "install", "--ignore-scripts", "--no-audit", "--no-fund", str(tarball)],
        cwd=consumer,
        timeout=180,
    )
    idleproof = bin_in_node_consumer(consumer, "idleproof")
    require(idleproof.is_file(), "installed IdleProof package has no CLI shim")
    return python, idleproof, tarball


def command_available(name: str) -> str:
    found = shutil.which(name)
    require(bool(found), f"required authenticated agent CLI is not available on PATH: {name}")
    return str(found)


def real_agent_env(idleproof: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = str(idleproof.parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for secret in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_DB_PASSWORD"):
        env.pop(secret, None)
    return env


def shell_command(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def claude_command(claude: str, prompt: str, budget: float) -> list[str]:
    return [
        claude,
        "-p",
        "--permission-mode", "acceptEdits",
        "--tools", "Read,Edit,Write",
        "--disallowedTools", "mcp__*",
        "--max-turns", "10",
        "--max-budget-usd", f"{budget:.2f}",
        "--no-session-persistence",
        "--no-chrome",
        "--disable-slash-commands",
        "--setting-sources", "project,local",
        prompt,
    ]


def codex_command(idleproof: Path, prompt: str) -> list[str]:
    return [str(idleproof), "codex", "--sandbox", "workspace-write", "--", prompt]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_git_status(repo: Path) -> list[tuple[str, str]]:
    # Porcelain's leading XY columns are data. Never route this through check()/git(),
    # because check() strips leading whitespace and corrupts paths for entries like
    # " M path/to/file". NUL framing also keeps spaces/newlines in filenames lossless.
    proc = run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo,
    )
    require(proc.returncode == 0, "git status --porcelain failed", proc)

    entries: list[tuple[str, str]] = []
    records = proc.stdout.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        require(
            len(record) >= 4 and record[2] == " ",
            f"malformed porcelain-v1 record: {record!r}",
        )
        status = record[:2]
        path = record[3:].replace("\\", "/")
        entries.append((status, path))

        # With -z, rename/copy entries carry the source pathname in the next NUL
        # field. The first pathname is the destination and is the worktree path we
        # want to validate, so consume (but do not report) the source field.
        if "R" in status or "C" in status:
            require(
                index < len(records) and bool(records[index]),
                f"malformed porcelain rename/copy record for {path!r}",
            )
            index += 1
    return entries


def snapshot_path(path: Path) -> tuple[bool, bytes | None]:
    if not path.exists():
        return False, None
    if path.is_file():
        return True, path.read_bytes()
    return True, None


def assert_path_unchanged(path: Path, before: tuple[bool, bytes | None]) -> None:
    existed, payload = before
    require(path.exists() == existed, f"pre-existing user path changed existence: {path}")
    if existed and payload is not None:
        require(path.is_file() and path.read_bytes() == payload, f"pre-existing user file was modified: {path}")


def assert_only_allowed_changes(
    repo: Path,
    allowed_paths: set[str],
    *,
    preexisting_paths: set[str] | None = None,
) -> None:
    preexisting_paths = preexisting_paths or set()
    unexpected: list[str] = []
    allowed_prefixes = (".idleproof/", ".claude/", ".codex/")
    for status, path in safe_git_status(repo):
        if path in allowed_paths or path in preexisting_paths:
            continue
        if path.startswith(allowed_prefixes):
            continue
        unexpected.append(f"{status} {path}")
    require(not unexpected, f"agent/harness exceeded allowed worktree surface: {unexpected}")

    tracked = [p.replace("\\", "/") for p in git(repo, "diff", "--name-only", "HEAD").splitlines() if p]
    tracked_new = [p for p in tracked if p not in preexisting_paths]
    require(bool(tracked_new), "agent produced no tracked candidate change")
    require(set(tracked_new).issubset(allowed_paths), f"tracked agent scope escaped allowed paths: {tracked_new}")


def assert_product_state(repo: Path, idleproof: Path, agent: str, env: dict[str, str]) -> dict:
    envelope_path = repo / ".git" / "diffwitness" / "change-envelope.json"
    receipt_path = repo / ".idleproof" / "receipt.json"
    require(envelope_path.is_file(), f"{agent}: missing integrated change envelope")
    require(receipt_path.is_file(), f"{agent}: missing IdleProof receipt")
    envelope = read_json(envelope_path)
    receipt = read_json(receipt_path)
    change_id = str(envelope.get("change_id") or "")
    require(change_id.startswith("dwchg_") and len(change_id) == 30, f"{agent}: invalid canonical change id")
    require(envelope.get("proof", {}).get("accepted") is True, f"{agent}: proof was not accepted")
    require(isinstance(envelope.get("debt", {}).get("points"), int), f"{agent}: Debt Ledger points missing")
    require(isinstance(envelope.get("understanding"), dict), f"{agent}: IdleProof understanding did not correlate")
    require(
        receipt.get("session", {}).get("change", {}).get("changeId") == change_id,
        f"{agent}: IdleProof/DiffWitness identity mismatch",
    )
    require(
        receipt.get("session", {}).get("proof", {}).get("changeId") == change_id,
        f"{agent}: receipt proof identity mismatch",
    )
    source = str(receipt.get("session", {}).get("source") or "")
    if agent == "claude":
        require(source == "claude", f"Claude lifecycle source is unsupported: {source!r}")
    else:
        require(source in {"codex", "codex-json-bridge"}, f"Codex lifecycle source is unsupported: {source!r}")

    preview = run([str(idleproof), "portal-preview", "--json"], cwd=repo, env=env, timeout=30)
    require(preview.returncode == 0, f"{agent}: IdleProof portal preview failed", preview)
    snapshot = json.loads(preview.stdout)
    require(snapshot.get("task", {}).get("summary"), f"{agent}: user-facing task summary is empty")
    require(snapshot.get("explanation") is not None, f"{agent}: user-facing explanation is empty")
    privacy = snapshot.get("privacy", {})
    require(
        privacy.get("sourceCodeIncluded") is False
        and privacy.get("rawDiffIncluded") is False
        and privacy.get("rawAgentEventsIncluded") is False
        and privacy.get("rawPromptIncluded") is False,
        f"{agent}: Portal preview privacy boundary regressed",
    )
    return {
        "agent": agent,
        "changeId": change_id,
        "proofClaim": envelope.get("proof", {}).get("claim"),
        "debtPoints": envelope.get("debt", {}).get("points"),
        "openObligations": len(envelope.get("debt", {}).get("open_lineages") or []),
        "understandingSource": source,
        "taskSummary": snapshot.get("task", {}).get("summary"),
        "files": snapshot.get("files", []),
    }


def assert_no_false_acceptance(repo: Path, guard: subprocess.CompletedProcess[str]) -> None:
    combined = guard.stdout + "\n" + guard.stderr
    require("PROOF ACCEPTED" not in combined, "failed agent/change was falsely reported as PROOF ACCEPTED", guard)
    envelope = repo / ".git" / "diffwitness" / "change-envelope.json"
    if envelope.is_file():
        payload = read_json(envelope)
        require(payload.get("proof", {}).get("accepted") is not True, "failed journey persisted an accepted envelope")


def continuity_ids(repo: Path) -> set[str]:
    journal = repo / ".git" / "diffwitness" / "events.jsonl"
    if not journal.is_file():
        return set()
    ids: set[str] = set()
    for line in journal.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("change_id", "changeId"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("dwchg_"):
                ids.add(value)
        nested = payload.get("payload")
        if isinstance(nested, dict):
            for key in ("change_id", "changeId"):
                value = nested.get(key)
                if isinstance(value, str) and value.startswith("dwchg_"):
                    ids.add(value)
    return ids
