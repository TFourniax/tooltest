from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: float = 300.0) -> subprocess.CompletedProcess[str]:
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


def check(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: float = 300.0) -> str:
    proc = run(args, cwd=cwd, env=env, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def require(condition: bool, message: str, proc: subprocess.CompletedProcess[str] | None = None) -> None:
    if condition:
        return
    suffix = "" if proc is None else f"\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    raise RuntimeError(message + suffix)


def git(repo: Path, *args: str) -> str:
    return check(["git", *args], cwd=repo)


def git_status_entries(repo: Path) -> list[str]:
    """Return porcelain-v1 entries without destroying the leading XY status columns."""
    proc = run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo,
        timeout=30,
    )
    require(proc.returncode == 0, "git status failed during agent scope validation", proc)
    return [entry for entry in proc.stdout.split("\0") if entry]


def executable_in_venv(venv_dir: Path, name: str) -> Path:
    scripts = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_dir / scripts / f"{name}{suffix}"


def bin_in_node_consumer(consumer: Path, name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    return consumer / "node_modules" / ".bin" / f"{name}{suffix}"


def evidence_command(python: Path) -> str:
    parts = [str(python), "-B", "-m", "unittest", "discover", "-s", "tests", "-q"]
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def build_exact_consumers(root: Path, idleproof_repo: Path) -> tuple[Path, Path, Path]:
    artifacts = root / "artifacts"
    artifacts.mkdir()
    check([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "--wheel-dir", str(artifacts)], cwd=ROOT, timeout=240)
    wheels = sorted(artifacts.glob("diffwitness-*.whl"))
    require(len(wheels) == 1, f"expected one DiffWitness wheel, found {len(wheels)}")

    pyenv = root / "python-consumer"
    venv.EnvBuilder(with_pip=True, clear=True).create(pyenv)
    python = executable_in_venv(pyenv, "python")
    check([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])], cwd=root, timeout=180)

    npm = shutil.which("npm")
    require(bool(npm), "npm is required for the exact IdleProof package acceptance journey")
    packed = json.loads(check([str(npm), "pack", "--json"], cwd=idleproof_repo, timeout=180))
    require(isinstance(packed, list) and packed and packed[0].get("filename"), "npm pack returned no IdleProof artifact")
    tarball = idleproof_repo / packed[0]["filename"]
    consumer = root / "node-consumer"
    consumer.mkdir()
    check([str(npm), "init", "-y"], cwd=consumer)
    check([str(npm), "install", "--ignore-scripts", "--no-audit", "--no-fund", str(tarball)], cwd=consumer, timeout=180)
    idleproof = bin_in_node_consumer(consumer, "idleproof")
    require(idleproof.is_file(), "installed IdleProof package has no CLI shim")
    return python, idleproof, tarball


def create_repo(root: Path, agent: str) -> Path:
    repo = root / f"repo-{agent}"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "real-agent-lab@diffwitness.local")
    git(repo, "config", "user.name", "Real Agent Acceptance")
    (repo / "calculator.py").write_text(
        "def clamp(value, low, high):\n"
        "    # Deliberate regression: the bounds are reversed.\n"
        "    return max(high, min(low, value))\n",
        encoding="utf-8",
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_calculator.py").write_text(
        "import unittest\n"
        "from calculator import clamp\n\n"
        "class ClampTests(unittest.TestCase):\n"
        "    def test_inside_range(self): self.assertEqual(clamp(5, 0, 10), 5)\n"
        "    def test_below_range(self): self.assertEqual(clamp(-3, 0, 10), 0)\n"
        "    def test_above_range(self): self.assertEqual(clamp(25, 0, 10), 10)\n",
        encoding="utf-8",
    )
    git(repo, "add", "calculator.py", "tests/test_calculator.py")
    git(repo, "commit", "-qm", "deliberately failing clamp baseline")
    return repo


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def command_available(name: str) -> str:
    found = shutil.which(name)
    require(bool(found), f"required authenticated agent CLI is not available on PATH: {name}")
    return str(found)


def strict_agent_prompt() -> str:
    return (
        "There is one deliberately failing regression in this tiny repository. "
        "Fix the clamp implementation so all existing tests pass. "
        "Edit calculator.py only. Do not edit tests, do not create files, do not commit, "
        "do not change git/agent/IdleProof configuration, and do not install dependencies. "
        "The external harness will run the tests after you finish."
    )


def claude_command(claude: str, prompt: str, budget: float) -> list[str]:
    return [
        claude,
        "-p",
        "--permission-mode", "acceptEdits",
        "--tools", "Read,Edit,Write",
        "--disallowedTools", "mcp__*",
        "--max-turns", "8",
        "--max-budget-usd", f"{budget:.2f}",
        "--no-session-persistence",
        "--no-chrome",
        "--disable-slash-commands",
        "--setting-sources", "project,local",
        prompt,
    ]


def codex_command(idleproof: Path, prompt: str) -> list[str]:
    # IdleProof's bridge deliberately limits Codex to read-only/workspace-write and consumes
    # the official JSONL telemetry stream. This remains observable even when project hooks
    # require manual trust or are skipped by a Codex regression.
    return [str(idleproof), "codex", "--sandbox", "workspace-write", "--", prompt]


def assert_only_expected_change(repo: Path) -> None:
    changed = git_status_entries(repo)
    unexpected: list[str] = []
    for entry in changed:
        # Porcelain v1 is "XY path". Preserve XY exactly; stripping the entry first turns
        # " M calculator.py" into "M calculator.py" and corrupts path extraction.
        if len(entry) < 4 or entry[2] != " ":
            unexpected.append(entry)
            continue
        path_text = entry[3:]
        normalized = path_text.replace("\\", "/")
        if normalized == "calculator.py":
            continue
        if normalized.startswith(".idleproof/") or normalized.startswith(".claude/") or normalized.startswith(".codex/"):
            continue
        unexpected.append(entry)
    require(not unexpected, f"agent exceeded the requested scope: {unexpected}")
    require(git(repo, "diff", "--name-only", "HEAD").splitlines() == ["calculator.py"], "tracked scope is not exactly calculator.py")


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
    require(receipt.get("session", {}).get("change", {}).get("changeId") == change_id, f"{agent}: IdleProof/DiffWitness identity mismatch")
    require(receipt.get("session", {}).get("proof", {}).get("changeId") == change_id, f"{agent}: receipt proof identity mismatch")
    source = str(receipt.get("session", {}).get("source") or "")
    if agent == "claude":
        require(source == "claude", f"Claude real lifecycle was not observed through native hooks (source={source!r})")
    else:
        require(source in {"codex", "codex-json-bridge"}, f"Codex lifecycle source is unsupported: {source!r}")

    preview = run([str(idleproof), "portal-preview", "--json"], cwd=repo, env=env, timeout=30)
    require(preview.returncode == 0, f"{agent}: IdleProof could not materialize its user-facing explanation snapshot", preview)
    snapshot = json.loads(preview.stdout)
    require(snapshot.get("task", {}).get("summary"), f"{agent}: user-facing task summary is empty")
    require(snapshot.get("explanation") is not None, f"{agent}: user-facing explanation is empty")
    require("calculator.py" in snapshot.get("files", []), f"{agent}: explanation lost the changed file")
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


def exercise_agent(agent: str, *, root: Path, python: Path, idleproof: Path, env: dict[str, str], claude_budget: float) -> dict:
    repo = create_repo(root, agent)
    prompt = strict_agent_prompt()
    server_started = False
    if agent == "claude":
        claude = command_available("claude")
        version = check([claude, "--version"], cwd=repo, env=env, timeout=20)
        require(version.strip(), "Claude CLI returned no version")
        started = run([str(idleproof), "on", "--agent", "claude", "--no-open"], cwd=repo, env=env, timeout=30)
        require(started.returncode == 0, "IdleProof could not install/start the Claude adapter", started)
        server_started = True
        agent_cmd = claude_command(claude, prompt, claude_budget)
    elif agent == "codex":
        codex = command_available("codex")
        version = check([codex, "--version"], cwd=repo, env=env, timeout=20)
        require(version.strip(), "Codex CLI returned no version")
        agent_cmd = codex_command(idleproof, prompt)
    else:
        raise ValueError(agent)

    baseline = run([str(python), "-B", "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=repo, env=env, timeout=30)
    require(baseline.returncode != 0, f"{agent}: acceptance fixture baseline is unexpectedly green")
    certificate = root / f"{agent}-certificate.json"
    guard = run(
        [
            str(python), "-m", "diffwitness.entry", "guard",
            "--repo", str(repo),
            "--test", evidence_command(python),
            "--policy", "strict",
            "--strategy", "exhaustive",
            "--stability-runs", "1",
            "--certificate", str(certificate),
            "--",
            *agent_cmd,
        ],
        cwd=repo,
        env=env,
        timeout=600,
    )
    try:
        require(guard.returncode == 0, f"{agent}: real agent journey was not accepted by DiffWitness", guard)
        require("PROOF ACCEPTED" in (guard.stdout + guard.stderr), f"{agent}: Guard did not surface accepted proof", guard)
        post = run([str(python), "-B", "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=repo, env=env, timeout=30)
        require(post.returncode == 0, f"{agent}: candidate is not actually green after Guard", post)
        assert_only_expected_change(repo)
        summary = assert_product_state(repo, idleproof, agent, env)
        require(certificate.is_file(), f"{agent}: certificate was not persisted")
        cert = read_json(certificate)
        require(bool(cert.get("certificate_id")), f"{agent}: certificate has no identity")
        summary["certificateId"] = cert.get("certificate_id")
        return summary
    finally:
        if server_started:
            run([str(idleproof), "stop"], cwd=repo, env=env, timeout=15)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real authenticated Claude Code/Codex through exact IdleProof + DiffWitness + Debt Ledger artifacts.")
    parser.add_argument("--idleproof-repo", required=True, type=Path)
    parser.add_argument("--agents", choices=["claude", "codex", "both"], default="both")
    parser.add_argument("--claude-budget-usd", type=float, default=float(os.environ.get("REAL_AGENT_CLAUDE_BUDGET_USD", "1.50")))
    args = parser.parse_args(argv)
    require(0.10 <= args.claude_budget_usd <= 10.0, "Claude budget must be between $0.10 and $10.00")
    idleproof_repo = args.idleproof_repo.resolve()
    require((idleproof_repo / "package.json").is_file(), "--idleproof-repo does not point to the IdleProof repository")

    selected = ["claude", "codex"] if args.agents == "both" else [args.agents]
    started = time.monotonic()
    tarball: Path | None = None
    with tempfile.TemporaryDirectory(prefix="real-agent-acceptance-") as td:
        root = Path(td)
        try:
            python, idleproof, tarball = build_exact_consumers(root, idleproof_repo)
            env = os.environ.copy()
            env["PATH"] = str(idleproof.parent) + os.pathsep + env.get("PATH", "")
            # Keep harness-created Python cache files out of the user workspace so the strict
            # scope validator measures agent behavior rather than interpreter side effects.
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            # The real-agent jobs must never inherit production Portal authority. They only exercise
            # local agent behavior; the managed Portal behavior lab is a separate isolated workflow.
            for secret in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_DB_PASSWORD"):
                env.pop(secret, None)
            results = [exercise_agent(agent, root=root, python=python, idleproof=idleproof, env=env, claude_budget=args.claude_budget_usd) for agent in selected]
            duration = round(time.monotonic() - started, 2)
            print(json.dumps({"schema":"diffwitness.real-agent-acceptance.v1","ok":True,"durationSeconds":duration,"results":results}, indent=2))
            return 0
        finally:
            if tarball is not None:
                try:
                    tarball.unlink(missing_ok=True)
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
