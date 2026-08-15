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
            fresh = verify_against_repo(
                report,
                repo=repo,
                against="WORKTREE",
                ignore_artifacts=["proof.json"],
            )
            self.assertTrue(fresh["valid"])
            self.assertEqual(fresh["integrity"], "valid")
            self.assertEqual(fresh["freshness"], "fresh")
            self.assertEqual(main(["verify", str(certificate), "--repo", str(repo)]), 0)

            (repo / "README.md").write_text("changed-after-proof\n", encoding="utf-8")
            stale = verify_against_repo(
                report,
                repo=repo,
                against="WORKTREE",
                ignore_artifacts=["proof.json"],
            )
            self.assertFalse(stale["valid"])
            self.assertEqual(stale["freshness"], "stale")
            self.assertEqual(main(["verify", str(certificate), "--repo", str(repo)]), 1)

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

    def test_tree_bound_validation_proof_verifies_in_fresh_clone_without_snapshot_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "source"
            repo.mkdir()
            git("init", "-q", cwd=repo)
            git("config", "user.email", "attest@example.com", cwd=repo)
            git("config", "user.name", "Attest Test", cwd=repo)
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)

            tests = repo / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text(
                "import unittest\nfrom app import VALUE\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_value(self):\n"
                "        self.assertEqual(VALUE, 1)\n",
                encoding="utf-8",
            )
            certificate = root / "portable-proof.json"
            self.assertEqual(
                main(
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
                ),
                0,
            )
            report = load_certificate(certificate)
            ephemeral_sha = report["candidate"]["sha"]
            self.assertTrue(report["candidate"].get("tree"))

            git("add", "tests/test_app.py", cwd=repo)
            git("commit", "-q", "-m", "tests", cwd=repo)
            clone = root / "clone"
            git("clone", "-q", str(repo), str(clone), cwd=root)

            # A normal clone receives reachable commits, not DiffWitness's unreachable snapshot.
            missing = subprocess.run(
                ["git", "cat-file", "-e", f"{ephemeral_sha}^{{commit}}"],
                cwd=clone,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(
                main(
                    [
                        "verify",
                        str(certificate),
                        "--repo",
                        str(clone),
                        "--against",
                        "HEAD",
                    ]
                ),
                0,
            )
            verification = verify_against_repo(report, repo=clone, against="HEAD")
            self.assertEqual(verification["candidate_binding"], "embedded-tree")
            self.assertTrue(verification["valid"])


if __name__ == "__main__":
    unittest.main()
