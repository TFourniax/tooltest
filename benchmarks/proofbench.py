from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from diffwitness.entry import main


@dataclass(slots=True)
class BenchResult:
    scenario: str
    naive_candidate_green: bool
    diffwitness_exit: int
    expected_exit: int
    certificate_kind: str | None
    classification: str | None
    passed: bool


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init(repo: Path, files: dict[str, str]) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "proofbench@example.com", cwd=repo)
    git("config", "user.name", "DiffWitness ProofBench", cwd=repo)
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def run_shell(command: str, repo: Path) -> bool:
    return subprocess.run(command, cwd=repo, shell=True).returncode == 0


def gate(
    repo: Path,
    *,
    base: str,
    command: str | None,
    policy: str,
    certificate: Path,
) -> tuple[int, dict]:
    args = [
        "gate",
        "--repo",
        str(repo),
        "--base",
        base,
        "--candidate",
        "WORKTREE",
        "--policy",
        policy,
        "--stability-runs",
        "1",
        "--certificate",
        str(certificate),
        "--no-github-actions",
    ]
    if command:
        args += ["--test", command]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = main(args)
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    return rc, payload


def kind(payload: dict) -> str | None:
    certificate = str(payload.get("certificate_id") or "")
    for prefix, name in (
        ("dw2_", "causal-exhaustive"),
        ("dwac1_", "causal-adaptive"),
        ("dwa1_", "assurance"),
        ("dwv1_", "validation-only"),
        ("dw0_", "not-required"),
    ):
        if certificate.startswith(prefix):
            return name
    return None


def scenario_scope_creep(root: Path) -> BenchResult:
    repo = root / "scope-creep"
    repo.mkdir()
    base = init(
        repo,
        {
            "calc.py": "def add(a, b):\n    return a - b\n\n\n\n\n\n\n\n\ndef label():\n    return 'calc'\n"
        },
    )
    (repo / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\n\n\n\n\n\n\ndef label():\n    return 'calculator'\n",
        encoding="utf-8",
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text(
        "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" -m unittest discover -s tests -q'
    naive = run_shell(command, repo)
    cert = root / "scope-creep.json"
    rc, payload = gate(repo, base=base, command=command, policy="strict", certificate=cert)
    expected = 1
    return BenchResult(
        "scope-creep-hidden-by-green-tests",
        naive,
        rc,
        expected,
        kind(payload),
        payload.get("classification") or payload.get("contrast"),
        naive and rc == expected,
    )


def scenario_non_discriminating(root: Path) -> BenchResult:
    repo = root / "non-discriminating"
    repo.mkdir()
    base = init(repo, {"app.py": "VALUE = 1\n"})
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_unrelated.py").write_text(
        "import unittest\n\nclass T(unittest.TestCase):\n"
        "    def test_arithmetic(self):\n        self.assertEqual(1 + 1, 2)\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" -m unittest discover -s tests -q'
    naive = run_shell(command, repo)
    cert = root / "non-discriminating.json"
    rc, payload = gate(repo, base=base, command=command, policy="balanced", certificate=cert)
    expected = 1
    return BenchResult(
        "new-tests-do-not-discriminate-change",
        naive,
        rc,
        expected,
        kind(payload),
        payload.get("classification"),
        naive and rc == expected and payload.get("classification") == "non-discriminating-change",
    )


def scenario_preservation(root: Path) -> BenchResult:
    repo = root / "preservation"
    repo.mkdir()
    test = (
        "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
    )
    base = init(
        repo,
        {"calc.py": "def add(a, b):\n    return a + b\n", "tests/test_calc.py": test},
    )
    (repo / "calc.py").write_text("def add(a, b):\n    return sum((a, b))\n", encoding="utf-8")
    command = f'"{sys.executable}" -m unittest discover -s tests -q'
    naive = run_shell(command, repo)
    cert = root / "preservation.json"
    rc, payload = gate(repo, base=base, command=command, policy="balanced", certificate=cert)
    expected = 0
    return BenchResult(
        "behavior-preserving-refactor",
        naive,
        rc,
        expected,
        kind(payload),
        payload.get("classification"),
        naive and rc == expected and payload.get("classification") == "preservation-evidence",
    )


def scenario_docs_only(root: Path) -> BenchResult:
    repo = root / "docs-only"
    repo.mkdir()
    base = init(repo, {"README.md": "old\n"})
    (repo / "README.md").write_text("new\n", encoding="utf-8")
    cert = root / "docs-only.json"
    rc, payload = gate(repo, base=base, command=None, policy="balanced", certificate=cert)
    expected = 0
    return BenchResult(
        "docs-only-no-fake-test-proof",
        True,
        rc,
        expected,
        kind(payload),
        payload.get("outcome"),
        rc == expected and payload.get("outcome") == "proof-not-required",
    )


def main_cli() -> int:
    parser = argparse.ArgumentParser(description="Run DiffWitness ProofBench scenarios.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        results = [
            scenario_scope_creep(root),
            scenario_non_discriminating(root),
            scenario_preservation(root),
            scenario_docs_only(root),
        ]
    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        print("DiffWitness ProofBench")
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            print(
                f"[{status}] {result.scenario}: naive_green={result.naive_candidate_green} "
                f"dw={result.diffwitness_exit} kind={result.certificate_kind} "
                f"classification={result.classification}"
            )
        print(f"\n{sum(result.passed for result in results)}/{len(results)} scenarios matched expected semantics")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
