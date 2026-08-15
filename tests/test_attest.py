from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.attest import load_certificate, verify_against_repo
from diffwitness.entry import main


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


class AttestationTests(unittest.TestCase):
    def test_noop_certificate_is_fresh_then_stale_after_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "attest@example.com", cwd=repo)
            git("config", "user.name", "Attest Test", cwd=repo)
            (repo / "README.md").write_text("old\n", encoding="utf-8")
            git("add", "README.md", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)

            (repo / "README.md").write_text("proved\n", encoding="utf-8")
            certificate = repo / "proof.json"
            self.assertEqual(
                main(
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
                    ]
                ),
                0,
            )
            report = load_certificate(certificate)
            fresh = verify_against_repo(report, repo=repo, against="WORKTREE")
            self.assertTrue(fresh["valid"])
            self.assertEqual(fresh["integrity"], "valid")
            self.assertEqual(fresh["freshness"], "fresh")

            (repo / "README.md").write_text("changed-after-proof\n", encoding="utf-8")
            stale = verify_against_repo(report, repo=repo, against="WORKTREE")
            self.assertFalse(stale["valid"])
            self.assertEqual(stale["freshness"], "stale")

    def test_verified_worktree_proof_can_be_attached_after_identical_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "attest@example.com", cwd=repo)
            git("config", "user.name", "Attest Test", cwd=repo)
            (repo / "README.md").write_text("old\n", encoding="utf-8")
            git("add", "README.md", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)

            (repo / "README.md").write_text("proved\n", encoding="utf-8")
            certificate = repo / "proof.json"
            self.assertEqual(
                main(
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
                    ]
                ),
                0,
            )
            git("add", "README.md", cwd=repo)
            git("commit", "-q", "-m", "docs", cwd=repo)

            self.assertEqual(
                main(["note", str(certificate), "--repo", str(repo), "--commit", "HEAD"]),
                0,
            )
            note = git("notes", "--ref=diffwitness", "show", "HEAD", cwd=repo)
            payload = json.loads(note)
            self.assertEqual(payload["protocol"], "DiffWitness")
            self.assertEqual(payload["certificate_id"], load_certificate(certificate)["certificate_id"])


if __name__ == "__main__":
    unittest.main()
