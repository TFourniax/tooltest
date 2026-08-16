from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_entry import debt_entry


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


class DebtEntryTests(unittest.TestCase):
    def test_tampered_certificate_fails_before_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            git("init", "-q", cwd=repo)
            git("config", "user.email", "x@y", cwd=repo)
            git("config", "user.name", "x", cwd=repo)
            (repo / "app.py").write_text("x=1\n", encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "base", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)
            (repo / "app.py").write_text("x=2\n", encoding="utf-8")
            cert = root / "cert.json"
            cert.write_text(
                json.dumps(
                    {
                        "certificate_id": "dwa1_00000000000000000000",
                        "classification": "preservation-evidence",
                        "candidate": {"sha": base},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                debt_entry(
                    [
                        "--repo", str(repo), "--base", base, "--candidate", "WORKTREE",
                        "--certificate", str(cert), "--no-record",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
