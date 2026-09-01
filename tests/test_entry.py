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


class EntryTests(unittest.TestCase):
    def test_docs_only_prove_succeeds_without_test_command_and_writes_noop_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "entry@example.com", cwd=repo)
            git("config", "user.name", "Entry Test", cwd=repo)
            (repo / "README.md").write_text("old\n", encoding="utf-8")
            git("add", "README.md", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)
            (repo / "README.md").write_text("new\n", encoding="utf-8")
            certificate = repo / "proof.json"
            report = repo / "proof.md"

            rc = main(
                [
                    "prove",
                    "--repo",
                    str(repo),
                    "--base",
                    base,
                    "--candidate",
                    "WORKTREE",
                    "--certificate",
                    str(certificate),
                    "--report",
                    str(report),
                ]
            )
            self.assertEqual(rc, 0)
            payload = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertEqual(payload["outcome"], "proof-not-required")
            self.assertTrue(payload["certificate_id"].startswith("dw0_"))
            self.assertEqual(payload["summary"]["mutations"], 0)
            self.assertIn("proof not required", report.read_text(encoding="utf-8").lower())

    def test_code_change_does_not_get_noop_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "entry@example.com", cwd=repo)
            git("config", "user.name", "Entry Test", cwd=repo)
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)
            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

            # No tests exist: a real code change must not be silently waived by the no-op layer.
            rc = main(
                [
                    "prove",
                    "--repo",
                    str(repo),
                    "--base",
                    base,
                    "--candidate",
                    "WORKTREE",
                ]
            )
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
