from __future__ import annotations

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


class FailClosedTests(unittest.TestCase):
    def test_unknown_test_only_surface_without_evidence_never_becomes_noop_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "failclosed@example.com", cwd=repo)
            git("config", "user.name", "Fail Closed Test", cwd=repo)
            (repo / "app.weird").write_text("production\n", encoding="utf-8")
            git("add", "app.weird", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)

            checks = repo / "checks"
            checks.mkdir()
            (checks / "behavior.case").write_text("new test contract\n", encoding="utf-8")

            rc = main(
                [
                    "gate",
                    "--repo",
                    str(repo),
                    "--base",
                    base,
                    "--candidate",
                    "WORKTREE",
                    "--test-glob",
                    "checks/*.case",
                    "--no-github-actions",
                ]
            )

            # No conventional evidence command exists for this deliberately unknown stack.
            # A proof layer must fail closed rather than silently waive a test-only change.
            self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
