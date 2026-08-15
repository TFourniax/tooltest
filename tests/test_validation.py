from __future__ import annotations

import json
import subprocess
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


def init_repo(repo: Path) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "validation@example.com", cwd=repo)
    git("config", "user.name", "Validation Test", cwd=repo)
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    git("add", "app.py", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def add_test(repo: Path, expected: int) -> None:
    tests = repo / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_app.py").write_text(
        "import unittest\nfrom app import VALUE\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_value(self):\n"
        f"        self.assertEqual(VALUE, {expected})\n",
        encoding="utf-8",
    )


class ValidationOnlyTests(unittest.TestCase):
    def test_test_only_diff_runs_evidence_and_is_attestable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            base = init_repo(repo)
            add_test(repo, 1)
            certificate = root / "validation.json"

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
            report = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertEqual(report["outcome"], "validation-only")
            self.assertTrue(report["certificate_id"].startswith("dwv1_"))
            self.assertEqual(report["candidate_run"]["classification"], "stable-pass")
            self.assertTrue(report["valid"])
            self.assertEqual(
                main(["verify", str(certificate), "--repo", str(repo)]),
                0,
            )

    def test_failing_test_only_diff_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            base = init_repo(repo)
            add_test(repo, 2)
            certificate = root / "validation.json"

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
                    "--stability-runs",
                    "1",
                    "--no-github-actions",
                ]
            )
            self.assertEqual(rc, 1)
            report = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertEqual(report["candidate_run"]["classification"], "stable-fail")
            self.assertFalse(report["valid"])


if __name__ == "__main__":
    unittest.main()
