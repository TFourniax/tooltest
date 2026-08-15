from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.entry import main


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init(repo: Path, source: str) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "gate@example.com", cwd=repo)
    git("config", "user.name", "Gate Test", cwd=repo)
    (repo / "calc.py").write_text(source, encoding="utf-8")
    git("add", "calc.py", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def add_regression(repo: Path) -> None:
    tests = repo / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_calc.py").write_text(
        "import unittest\nfrom calc import add\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )


class GateTests(unittest.TestCase):
    def test_small_proven_fix_uses_exhaustive_gate_and_writes_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init(repo, "def add(a, b):\n    return a - b\n")
            (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            add_regression(repo)
            certificate = repo.parent / "gate-proof.json"
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            rc = main(
                [
                    "gate",
                    "--repo",
                    str(repo),
                    "--base",
                    base,
                    "--candidate",
                    "WORKTREE",
                    "--test",
                    command,
                    "--strategy",
                    "auto",
                    "--policy",
                    "strict",
                    "--stability-runs",
                    "1",
                    "--certificate",
                    str(certificate),
                    "--no-github-actions",
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertTrue(payload["certificate_id"].startswith("dw2_"))
            self.assertEqual(payload["contrast"], "base-fail_candidate-pass")
            self.assertEqual(payload["summary"]["unwitnessed"], 0)

    def test_auto_routes_surplus_patch_to_adaptive_and_rejects_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init(
                repo,
                "def add(a, b):\n    return a - b\n\n\n\n\n\n\n\n\n"
                "def label():\n    return 'calc'\n",
            )
            (repo / "calc.py").write_text(
                "def add(a, b):\n    return a + b\n\n\n\n\n\n\n\n\n"
                "def label():\n    return 'calculator'\n",
                encoding="utf-8",
            )
            add_regression(repo)
            certificate = repo.parent / "adaptive-proof.json"
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            rc = main(
                [
                    "gate",
                    "--repo",
                    str(repo),
                    "--base",
                    base,
                    "--candidate",
                    "WORKTREE",
                    "--test",
                    command,
                    "--strategy",
                    "auto",
                    "--adaptive-threshold",
                    "1",
                    "--adaptive-budget",
                    "10",
                    "--policy",
                    "balanced",
                    "--stability-runs",
                    "1",
                    "--certificate",
                    str(certificate),
                    "--no-github-actions",
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertTrue(payload["certificate_id"].startswith("dwac1_"))
            self.assertTrue(payload["one_minimal"])
            self.assertEqual(len(payload["removable_mutation_ids"]), 1)

    def test_docs_only_gate_becomes_formal_proof_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "gate@example.com", cwd=repo)
            git("config", "user.name", "Gate Test", cwd=repo)
            (repo / "README.md").write_text("old\n", encoding="utf-8")
            git("add", "README.md", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)
            (repo / "README.md").write_text("new\n", encoding="utf-8")
            certificate = repo.parent / "noop.json"
            rc = main(
                [
                    "gate",
                    "--repo",
                    str(repo),
                    "--base",
                    base,
                    "--candidate",
                    "WORKTREE",
                    "--certificate",
                    str(certificate),
                    "--no-github-actions",
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertEqual(payload["outcome"], "proof-not-required")

    def test_explicit_nondefault_config_supplies_evidence_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init(repo, "def add(a, b):\n    return a - b\n")
            (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            add_regression(repo)
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            escaped = command.replace("\\", "\\\\").replace('"', '\\"')
            (repo / "proof-config.toml").write_text(
                f'[diffwitness]\ntest = "{escaped}"\nstability_runs = 1\n',
                encoding="utf-8",
            )
            rc = main(
                [
                    "gate",
                    "--repo",
                    str(repo),
                    "--config",
                    "proof-config.toml",
                    "--base",
                    base,
                    "--candidate",
                    "WORKTREE",
                    "--strategy",
                    "exhaustive",
                    "--policy",
                    "strict",
                    "--no-github-actions",
                ]
            )
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
