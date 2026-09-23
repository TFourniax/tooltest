from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from diffwitness.attestation import AttestationError, expected_certificate_id, verify_against_repo
from diffwitness.debt_certificate import DebtCertificateError, validate_debt_certificate
from test_debt_certificate import git


class ProofDebtFamilyTests(unittest.TestCase):
    def invoke(self, repo, *args):
        p = subprocess.run([sys.executable, "-c", "from diffwitness.entry import main; raise SystemExit(main())", *args],
            cwd=repo, capture_output=True, text=True, timeout=45,
            env={**os.environ, "GITHUB_ACTIONS": "false"})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def produce(self, root, family):
        repo = root / "repo"
        repo.mkdir()
        git("init", "-q", cwd=repo)
        git("config", "user.email", "proof-debt@example.test", cwd=repo)
        git("config", "user.name", "Proof Debt Test", cwd=repo)
        git("config", "maintenance.auto", "false", cwd=repo)
        git("config", "gc.auto", "0", cwd=repo)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n" if family in {"dwac1", "dw2"}
            else "def add(a, b):\n    return a + b\n", encoding="utf-8")
        (repo / "tests").mkdir()
        test = "import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2, 3), 5)\n"
        if family != "dwv1":
            (repo / "tests/test_calc.py").write_text(test, encoding="utf-8")
        git("add", ".", cwd=repo)
        git("commit", "-qm", "base", cwd=repo)
        base = git("rev-parse", "HEAD", cwd=repo)
        if family in {"dwac1", "dw2"}:
            (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        elif family == "dwa1":
            (repo / "calc.py").write_text("def add(a, b):\n    return sum((a, b))\n", encoding="utf-8")
        elif family == "dwv1":
            (repo / "tests/test_calc.py").write_text(test, encoding="utf-8")
        else:
            (repo / "README.md").write_text("updated fixture\n", encoding="utf-8")
        git("add", ".", cwd=repo)
        git("commit", "-qm", "candidate", cwd=repo)
        candidate = git("rev-parse", "HEAD", cwd=repo)
        path = root / "certificate.json"
        args = ["gate" if family in {"dwac1", "dwa1"} else "prove", "--base", base,
                "--candidate", candidate, "--test", f'"{sys.executable}" -m unittest discover -s tests -q',
                "--stability-runs", "1", "--certificate", str(path), "--no-github-actions"]
        if family == "dwac1":
            args += ["--strategy", "adaptive", "--adaptive-budget", "10"]
        self.invoke(repo, *args)
        report = json.loads(path.read_text())
        self.assertTrue(report["certificate_id"].startswith(family + "_"))
        return repo, base, candidate, path, report

    def test_all_real_public_producers_verify_then_feed_debt_unchanged(self):
        for family in ("dwac1", "dw2", "dwa1", "dwv1", "dw0"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                repo, base, candidate, cert, _ = self.produce(root, family)
                before = hashlib.sha256(cert.read_bytes()).hexdigest()
                self.invoke(repo, "verify", str(cert), "--against", candidate, "--json")
                self.invoke(repo, "debt", "--base", base, "--candidate", candidate,
                            "--certificate", str(cert), "--no-record", "--json", str(root / "debt.json"))
                self.assertEqual(hashlib.sha256(cert.read_bytes()).hexdigest(), before)

    def test_binding_conflicts_and_unknown_schemas_are_refused_by_both_readers(self):
        for family in ("dwac1", "dw2", "dwa1", "dwv1", "dw0"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as td:
                repo, base, candidate, cert, report = self.produce(Path(td), family)
                for mutation in ("conflict", "unknown-schema", "malformed-binding", "corrupt"):
                    bad = copy.deepcopy(report)
                    if mutation == "conflict":
                        if family == "dwac1":
                            bad["candidate"]["tree"] = "f" * 40
                        else:
                            bad["candidate_tree"] = "f" * 40
                    elif mutation == "unknown-schema":
                        bad["schema_version"] = "future-unknown"
                    elif mutation == "malformed-binding":
                        if family == "dwac1": bad["candidate_tree"] = "HEAD"
                        else: bad["candidate"]["tree"] = "HEAD"
                    else:
                        bad["certificate_id"] = family + "_" + "0" * 20
                    if mutation != "corrupt":
                        bad["certificate_id"] = expected_certificate_id(bad)
                    with self.subTest(mutation=mutation):
                        with self.assertRaises(DebtCertificateError):
                            validate_debt_certificate(bad, repo=repo, candidate_sha=candidate)
                        try:
                            verified = verify_against_repo(bad, repo=repo, against=candidate)
                        except AttestationError:
                            pass
                        else:
                            self.assertFalse(verified["valid"])
                with self.assertRaises(DebtCertificateError):
                    validate_debt_certificate(report, repo=repo, candidate_sha=base)


if __name__ == "__main__":
    unittest.main()
