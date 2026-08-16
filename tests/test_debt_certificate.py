from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_certificate import DebtCertificateError, expected_id, validate_debt_certificate


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


class DebtCertificateTests(unittest.TestCase):
    def test_assurance_certificate_must_be_content_addressed_and_tree_bound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "cert@example.com", cwd=repo)
            git("config", "user.name", "Cert Test", cwd=repo)
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "base", cwd=repo)
            sha = git("rev-parse", "HEAD", cwd=repo)
            tree = git("rev-parse", "HEAD^{tree}", cwd=repo)
            report = {
                "certificate_id": "dwa1_pending",
                "base": {"sha": sha, "tree": tree},
                "candidate": {"ref": "HEAD", "sha": sha, "tree": tree},
                "test_command": "python -m unittest -q",
                "changed_test_files": [],
                "candidate_run": {"classification": "stable-pass", "runs": [], "total_duration_s": 0.0},
                "baseline_with_candidate_tests_run": {"classification": "stable-pass", "runs": [], "total_duration_s": 0.0},
                "classification": "preservation-evidence",
                "execution": {"prepare": None, "timeout": 300.0, "stability_runs": 2, "share": [], "test_overlay": True},
            }
            report["certificate_id"] = expected_id({**report, "certificate_id": "dwa1_00000000000000000000"})
            validate_debt_certificate(report, repo=repo, candidate_sha=sha)

            forged = json.loads(json.dumps(report))
            forged["classification"] = "causal-contrast"
            with self.assertRaises(DebtCertificateError):
                validate_debt_certificate(forged, repo=repo, candidate_sha=sha)

            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "change", cwd=repo)
            other_sha = git("rev-parse", "HEAD", cwd=repo)
            with self.assertRaises(DebtCertificateError):
                validate_debt_certificate(report, repo=repo, candidate_sha=other_sha)


if __name__ == "__main__":
    unittest.main()
