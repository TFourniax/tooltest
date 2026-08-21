from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(args: list[str], *, cwd: Path, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def check(args: list[str], *, cwd: Path) -> str:
    proc = run(args, cwd=cwd)
    if proc.returncode:
        raise RuntimeError(f"{' '.join(args)} failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return proc.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return check(["git", *args], cwd=repo)


def init_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "recovery@diffwitness.local")
    git(repo, "config", "user.name", "DiffWitness Recovery Acceptance")
    return repo


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def dw(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, "-m", "diffwitness.entry", *args], cwd=repo, timeout=90.0)


def require(condition: bool, message: str, proc: subprocess.CompletedProcess[str] | None = None) -> None:
    if condition:
        return
    detail = f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}" if proc else ""
    raise RuntimeError(message + detail)


def ledger_corruption_is_fail_closed(root: Path) -> None:
    repo = init_repo(root, "ledger-corruption")
    (repo / "app.py").write_text("def value():\n    return 0\n", encoding="utf-8")
    base = commit(repo, "base")
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    candidate = commit(repo, "candidate")

    measured = dw(repo, "debt", "--repo", str(repo), "--base", base, "--candidate", candidate)
    require(measured.returncode == 0, "could not create a real ledger before corruption test", measured)
    ledger = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
    original = ledger.read_text(encoding="utf-8")
    require(bool(original.strip()), "debt measurement created an empty ledger")

    lines = original.splitlines()
    first = json.loads(lines[0])
    payload = dict(first.get("payload") or {})
    payload["acceptance_probe"] = "tampered-after-hash"
    first["payload"] = payload
    lines[0] = json.dumps(first, sort_keys=True, ensure_ascii=False)
    tampered = "\n".join(lines) + "\n"
    ledger.write_text(tampered, encoding="utf-8")

    status = dw(repo, "ledger", "--repo", str(repo), "status")
    require(status.returncode == 2, "tampered Debt Ledger was not rejected", status)
    require(
        "integrity check failed" in status.stderr.lower() or "hash chain broken" in status.stderr.lower(),
        "ledger failure does not explain the integrity problem",
        status,
    )
    require(ledger.read_text(encoding="utf-8") == tampered, "read path rewrote or repaired a tampered ledger silently")

    # Recovery is intentionally explicit rather than magical: restoring a known-good copy should
    # immediately make the local ledger usable again without hidden migrations or state mutation.
    ledger.write_text(original, encoding="utf-8")
    restored = dw(repo, "ledger", "--repo", str(repo), "status")
    require(restored.returncode == 0, "restored known-good ledger did not recover cleanly", restored)
    require("Events:" in restored.stdout and "Last hash:" in restored.stdout, "recovered status lacks integrity orientation", restored)


def unknown_stack_is_fail_closed(root: Path) -> None:
    repo = init_repo(root, "unknown-evidence")
    (repo / "app.weird").write_text("production\n", encoding="utf-8")
    commit(repo, "baseline")
    checks = repo / "checks"
    checks.mkdir()
    (checks / "behavior.case").write_text("new test contract\n", encoding="utf-8")

    gate = dw(
        repo,
        "gate",
        "--repo", str(repo),
        "--base", "HEAD",
        "--candidate", "WORKTREE",
        "--test-glob", "checks/*.case",
        "--no-github-actions",
    )
    require(gate.returncode == 2, "unknown evidence stack was silently accepted", gate)
    text = f"{gate.stdout}\n{gate.stderr}".lower()
    require("failing closed" in text and "--test" in text, "unknown-stack failure is not actionable to a human", gate)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="diffwitness-recovery-acceptance-") as td:
        root = Path(td)
        print("[recovery] tampered Debt Ledger")
        ledger_corruption_is_fail_closed(root)
        print("[recovery] PASS · tampered Debt Ledger")
        print("[recovery] unknown evidence stack")
        unknown_stack_is_fail_closed(root)
        print("[recovery] PASS · unknown evidence stack")
    print("RECOVERY ACCEPTANCE PASS · fail-closed installed-product journeys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
