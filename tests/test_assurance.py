from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.assurance import assurance_policy, build_assurance
from diffwitness.diffing import parse_file_patches
from diffwitness.entry import main
from diffwitness.gitops import diff_text, snapshot_worktree


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init_repo(repo: Path, *, source: str, test_source: str | None = None) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "assurance@example.com", cwd=repo)
    git("config", "user.name", "Assurance Test", cwd=repo)
    (repo / "calc.py").write_text(source, encoding="utf-8")
    if test_source is not None:
        tests = repo / "tests"
        tests.mkdir()
        (tests / "test_calc.py").write_text(test_source, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


class AssuranceTests(unittest.TestCase):
    def test_behavior_preserving_refactor_gets_preservation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            test_source = (
                "import unittest\nfrom calc import add\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n"
            )
            base = init_repo(
                repo,
                source="def add(a, b):\n    return a + b\n",
                test_source=test_source,
            )
            (repo / "calc.py").write_text(
                "def add(a, b):\n    return sum((a, b))\n", encoding="utf-8"
            )
            candidate = snapshot_worktree(repo)
            files = parse_file_patches(diff_text(repo, base, candidate))
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            report = build_assurance(
                source_repo=repo,
                base_sha=base,
                candidate_sha=candidate,
                candidate_ref="WORKTREE",
                files=files,
                test_command=command,
                stability_runs=1,
                timeout=30,
                prepare_command=None,
                shared_paths=[],
                overlay_candidate_tests=True,
            )
            self.assertEqual(report["classification"], "preservation-evidence")
            self.assertTrue(assurance_policy(report, "balanced")[0])
            self.assertFalse(assurance_policy(report, "strict")[0])

    def test_gate_balanced_accepts_and_public_verify_understands_assurance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            test_source = (
                "import unittest\nfrom calc import add\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n"
            )
            base = init_repo(
                repo,
                source="def add(a, b):\n    return a + b\n",
                test_source=test_source,
            )
            (repo / "calc.py").write_text(
                "def add(a, b):\n    return sum((a, b))\n", encoding="utf-8"
            )
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            certificate = root / "assurance.json"
            balanced = main(
                [
                    "gate", "--repo", str(repo), "--base", base, "--candidate", "WORKTREE",
                    "--test", command, "--policy", "balanced", "--stability-runs", "1",
                    "--certificate", str(certificate), "--no-github-actions",
                ]
            )
            self.assertEqual(balanced, 0)
            payload = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertEqual(payload["classification"], "preservation-evidence")
            self.assertTrue(payload["certificate_id"].startswith("dwa1_"))
            self.assertEqual(main(["verify", str(certificate), "--repo", str(repo)]), 0)

            (repo / "calc.py").write_text(
                "def add(a, b):\n    return a - b\n", encoding="utf-8"
            )
            self.assertEqual(main(["verify", str(certificate), "--repo", str(repo)]), 1)

            strict = main(
                [
                    "gate", "--repo", str(repo), "--base", base, "--candidate", "WORKTREE",
                    "--test", command, "--policy", "strict", "--stability-runs", "1",
                    "--no-github-actions",
                ]
            )
            self.assertEqual(strict, 1)

    def test_changed_tests_that_already_pass_on_base_are_non_discriminating(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            base = init_repo(repo, source="VALUE = 1\n")
            (repo / "calc.py").write_text("VALUE = 2\n", encoding="utf-8")
            tests = repo / "tests"
            tests.mkdir()
            (tests / "test_unrelated.py").write_text(
                "import unittest\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_arithmetic(self):\n"
                "        self.assertEqual(1 + 1, 2)\n",
                encoding="utf-8",
            )
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            certificate = root / "weak-evidence.json"
            rc = main(
                [
                    "gate", "--repo", str(repo), "--base", base, "--candidate", "WORKTREE",
                    "--test", command, "--policy", "balanced", "--stability-runs", "1",
                    "--certificate", str(certificate), "--no-github-actions",
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertEqual(payload["classification"], "non-discriminating-change")
            self.assertEqual(payload["baseline_with_candidate_tests_run"]["classification"], "stable-pass")
            self.assertEqual(payload["candidate_run"]["classification"], "stable-pass")


if __name__ == "__main__":
    unittest.main()
