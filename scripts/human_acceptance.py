from __future__ import annotations

import json
import os
import shlex
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


def check(args: list[str], *, cwd: Path, timeout: float = 60.0) -> str:
    proc = run(args, cwd=cwd, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def git(repo: Path, *args: str) -> str:
    return check(["git", *args], cwd=repo)


def init_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "human-acceptance@diffwitness.local")
    git(repo, "config", "user.name", "DiffWitness Human Acceptance")
    return repo


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def evidence_command(*, tests_dir: str = "tests") -> str:
    parts = [sys.executable, "-m", "unittest", "discover", "-s", tests_dir, "-q"]
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def dw(repo: Path, *args: str, timeout: float = 90.0) -> subprocess.CompletedProcess[str]:
    # Use the installed module rather than source-tree imports. The wheel-e2e job runs this script
    # only after installing the exact release artifact into the interpreter executing this file.
    return run([sys.executable, "-m", "diffwitness.entry", *args], cwd=repo, timeout=timeout)


def combined(proc: subprocess.CompletedProcess[str]) -> str:
    return f"{proc.stdout}\n{proc.stderr}"


def require(condition: bool, message: str, proc: subprocess.CompletedProcess[str] | None = None) -> None:
    if condition:
        return
    detail = f"\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}" if proc is not None else ""
    raise RuntimeError(message + detail)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_unittest(repo: Path, body: str) -> None:
    tests = repo / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_app.py").write_text(body, encoding="utf-8")


def scenario_strict_bugfix(root: Path) -> None:
    repo = init_repo(root, "strict-bugfix")
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    write_unittest(
        repo,
        "import unittest\nfrom app import add\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
    )
    commit(repo, "buggy baseline with regression evidence")
    cert = root / "strict-bugfix.json"
    script = "from pathlib import Path; Path('app.py').write_text('def add(a, b):\\n    return a + b\\n', encoding='utf-8')"
    proc = dw(
        repo,
        "guard", "--repo", str(repo), "--test", evidence_command(), "--policy", "strict",
        "--strategy", "exhaustive", "--stability-runs", "2", "--certificate", str(cert),
        "--no-debt", "--", sys.executable, "-c", script,
    )
    require(proc.returncode == 0, "strict witnessed bugfix was not accepted", proc)
    require("PROOF ACCEPTED" in combined(proc), "guard did not clearly report acceptance", proc)
    payload = read_json(cert)
    require(payload.get("contrast") == "base-fail_candidate-pass", "strict bugfix lost causal contrast")
    summary = payload.get("summary") or {}
    require(summary.get("witnessed", 0) >= 1 and not summary.get("inconclusive", 0), "strict bugfix certificate is not decisive")
    verify = dw(repo, "verify", str(cert), "--repo", str(repo))
    require(verify.returncode == 0, "fresh proof certificate did not verify", verify)


def scenario_noop_and_agent_failure(root: Path) -> None:
    repo = init_repo(root, "agent-boundary")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_unittest(repo, "import unittest\nimport app\nclass T(unittest.TestCase):\n    def test_value(self): self.assertEqual(app.VALUE, 1)\n")
    commit(repo, "working baseline")

    noop_cert = root / "noop.json"
    noop = dw(
        repo, "guard", "--repo", str(repo), "--test", evidence_command(), "--certificate", str(noop_cert),
        "--no-debt", "--", sys.executable, "-c", "pass",
    )
    require(noop.returncode == 0, "no-op agent should not fail the workflow", noop)
    require("no repository change" in combined(noop).lower(), "no-op result is not understandable to a human", noop)
    require(not noop_cert.exists(), "no-op agent unexpectedly minted a proof certificate")

    fail_cert = root / "agent-failure.json"
    failed = dw(
        repo, "guard", "--repo", str(repo), "--test", evidence_command(), "--certificate", str(fail_cert),
        "--no-debt", "--", sys.executable, "-c", "raise SystemExit(7)",
    )
    require(failed.returncode == 7, "Guard did not preserve the agent failure exit code", failed)
    require("proof was not attempted" in combined(failed).lower(), "agent failure could be mistaken for a proof result", failed)
    require(not fail_cert.exists(), "failed agent unexpectedly minted a proof certificate")

    missing_cert = root / "missing-agent.json"
    missing = dw(
        repo, "guard", "--repo", str(repo), "--test", evidence_command(), "--certificate", str(missing_cert),
        "--no-debt", "--", "diffwitness-agent-that-does-not-exist-8e1ce9",
    )
    require(missing.returncode == 127, "missing agent executable did not return shell-like 127", missing)
    require("cannot start agent command" in combined(missing).lower(), "missing agent error is not actionable", missing)
    require(not missing_cert.exists(), "missing agent unexpectedly minted a proof certificate")


def scenario_preservation_refactor(root: Path) -> None:
    repo = init_repo(root, "preservation-refactor")
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    write_unittest(repo, "import unittest\nfrom app import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2, 3), 5)\n")
    commit(repo, "working baseline")
    cert = root / "preservation.json"
    script = "from pathlib import Path; Path('app.py').write_text('def add(a, b):\\n    return sum((a, b))\\n', encoding='utf-8')"
    proc = dw(
        repo, "guard", "--repo", str(repo), "--test", evidence_command(), "--policy", "balanced",
        "--stability-runs", "2", "--certificate", str(cert), "--no-debt", "--", sys.executable, "-c", script,
    )
    require(proc.returncode == 0, "balanced preservation refactor should be accepted", proc)
    payload = read_json(cert)
    require(payload.get("classification") == "preservation-evidence", "refactor was overstated as causal proof")
    require("preservation" in str(payload.get("claim", "")).lower(), "certificate does not explain the preservation boundary")


def scenario_non_discriminating_test(root: Path) -> None:
    repo = init_repo(root, "non-discriminating")
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    commit(repo, "baseline already has desired behavior")
    cert = root / "non-discriminating.json"
    script = (
        "from pathlib import Path; "
        "Path('app.py').write_text('def value():\\n    return int(\\\"1\\\")\\n', encoding='utf-8'); "
        "Path('tests').mkdir(exist_ok=True); "
        "Path('tests/test_app.py').write_text("
        "'import unittest\\nfrom app import value\\nclass T(unittest.TestCase):\\n    def test_value(self): self.assertEqual(value(), 1)\\n', encoding='utf-8')"
    )
    proc = dw(
        repo, "guard", "--repo", str(repo), "--test", evidence_command(), "--policy", "balanced",
        "--stability-runs", "2", "--certificate", str(cert), "--no-debt", "--", sys.executable, "-c", script,
    )
    require(proc.returncode == 1, "non-discriminating changed tests must block balanced policy", proc)
    payload = read_json(cert)
    require(payload.get("classification") == "non-discriminating-change", "wrong classification for test that already passes on base")
    require("do not discriminate" in str(payload.get("claim", "")).lower(), "certificate fails to explain why green is insufficient")


def scenario_scope_creep(root: Path) -> None:
    repo = init_repo(root, "scope-creep")
    (repo / "core.py").write_text("def value():\n    return 0\n", encoding="utf-8")
    for index in range(8):
        (repo / f"decoy_{index}.py").write_text(f"VALUE = {index}\n", encoding="utf-8")
    write_unittest(repo, "import unittest\nfrom core import value\nclass T(unittest.TestCase):\n    def test_value(self): self.assertEqual(value(), 1)\n")
    commit(repo, "buggy baseline")
    cert = root / "scope-creep.json"
    script_lines = [
        "from pathlib import Path",
        "Path('core.py').write_text('def value():\\n    return 1\\n', encoding='utf-8')",
    ]
    for index in range(8):
        script_lines.append(f"Path('decoy_{index}.py').write_text('VALUE = {100 + index}\\n', encoding='utf-8')")
    proc = dw(
        repo, "guard", "--repo", str(repo), "--test", evidence_command(), "--policy", "balanced",
        "--strategy", "adaptive", "--adaptive-budget", "40", "--stability-runs", "1",
        "--certificate", str(cert), "--no-debt", "--", sys.executable, "-c", "; ".join(script_lines),
        timeout=120,
    )
    require(proc.returncode == 1, "scope creep should not be silently accepted", proc)
    require("PROOF REJECTED" in combined(proc), "scope-creep rejection is not visible to the user", proc)
    payload = read_json(cert)
    require(payload.get("one_minimal") is True, "scope-creep search did not establish its bounded 1-minimal claim")
    removable = payload.get("removable_mutation_ids") or []
    require(len(removable) >= 1, "scope-creep fixture did not identify any evidence-removable surface")
    require(len(payload.get("core_mutation_ids") or []) < len(payload.get("original_mutation_ids") or []), "scope-creep certificate did not reduce the patch")


def scenario_debt_lifecycle(root: Path) -> None:
    repo = init_repo(root, "debt-lifecycle")
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    base = commit(repo, "baseline")
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    candidate = commit(repo, "feature without regression test")

    debt = dw(repo, "debt", "--repo", str(repo), "--base", base, "--candidate", candidate)
    require(debt.returncode == 0, "ordinary debt measurement unexpectedly failed", debt)
    require("Debt impact:" in debt.stdout and "Ledger:" in debt.stdout, "debt command does not explain what it recorded", debt)
    ledger = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
    require(ledger.exists(), "debt measurement did not create the default durable local ledger")

    health = dw(repo, "health", "--repo", str(repo), "--no-record")
    require(health.returncode == 0, "health command failed on its own recorded ledger", health)
    require("Project health / debt ledger" in health.stdout and "Trend" in health.stdout, "health output lacks project-level orientation", health)

    plan = dw(repo, "plan", "--repo", str(repo))
    require(plan.returncode == 0, "repayment planning failed", plan)
    require("Repayment plan" in plan.stdout or "Manual/external-review backlog" in plan.stdout, "plan gave the user no next action", plan)

    prompt = dw(repo, "repay", "--repo", str(repo), "--prompt-only")
    require(prompt.returncode == 0, "prompt-only repayment failed", prompt)
    require("Debt obligations:" in prompt.stdout and "Change only what is necessary" in prompt.stdout, "repayment prompt lost its constrained mission")


def main() -> int:
    scenarios = [
        ("strict witnessed bugfix", scenario_strict_bugfix),
        ("no-op / failing / missing agent boundary", scenario_noop_and_agent_failure),
        ("preservation refactor", scenario_preservation_refactor),
        ("non-discriminating changed test", scenario_non_discriminating_test),
        ("scope-creep rejection", scenario_scope_creep),
        ("Debt Ledger lifecycle", scenario_debt_lifecycle),
    ]
    with tempfile.TemporaryDirectory(prefix="diffwitness-human-acceptance-") as td:
        root = Path(td)
        for name, scenario in scenarios:
            print(f"\n[human] {name}", flush=True)
            scenario(root)
            print(f"[human] PASS · {name}", flush=True)
    print(f"\nHUMAN ACCEPTANCE PASS · {len(scenarios)} installed-product journeys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
