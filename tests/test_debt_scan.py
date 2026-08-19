from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_scan import scan_change, scan_project


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init_repo(repo: Path, files: dict[str, str]) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "debt@example.com", cwd=repo)
    git("config", "user.name", "Debt Test", cwd=repo)
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


class DebtScanTests(unittest.TestCase):
    def test_unverified_change_and_no_changed_test_surface_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"app.py": "def add(a, b):\n    return a - b\n"})
            (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "change", cwd=repo)
            report = scan_change(repo=repo, base_sha=base, candidate_sha=git("rev-parse", "HEAD", cwd=repo))
            rules = {signal.rule_id for signal in report.signals}
            self.assertIn("change.no-proof-certificate", rules)
            self.assertIn("change.no-changed-test-surface", rules)

    def test_non_probative_certificate_cannot_hide_unverified_change(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            base = init_repo(repo, {"app.py": "def value():\n    return 1\n"})
            (repo / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "change", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)
            cert = root / "non-proof.json"
            cert.write_text(
                json.dumps({"certificate_id": "dw0_not-a-causal-proof"}),
                encoding="utf-8",
            )
            report = scan_change(
                repo=repo,
                base_sha=base,
                candidate_sha=candidate,
                certificate_path=cert,
            )
            rules = {signal.rule_id for signal in report.signals}
            self.assertFalse(report.metadata["behavior_backed"])
            self.assertIn("change.no-proof-certificate", rules)

    def test_preservation_certificate_prevents_fake_test_debt_but_not_security_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            base = init_repo(repo, {"auth/session.py": "def session(x):\n    return x\n"})
            (repo / "auth/session.py").write_text(
                "def session(x):\n    result = x\n    return result\n",
                encoding="utf-8",
            )
            git("add", "auth/session.py", cwd=repo)
            git("commit", "-q", "-m", "refactor", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)
            cert = root / "cert.json"
            cert.write_text(
                json.dumps({"certificate_id": "dwa1_123", "classification": "preservation-evidence"}),
                encoding="utf-8",
            )
            by_rule = {
                signal.rule_id: signal
                for signal in scan_change(
                    repo=repo,
                    base_sha=base,
                    candidate_sha=candidate,
                    certificate_path=cert,
                ).signals
            }
            self.assertNotIn("change.no-proof-certificate", by_rule)
            self.assertNotIn("change.no-changed-test-surface", by_rule)
            self.assertIn("security.sensitive-surface-change", by_rule)
            self.assertEqual(by_rule["security.sensitive-surface-change"].severity, "low")
            self.assertIn("not itself a security proof", by_rule["security.sensitive-surface-change"].explanation)

    def test_security_rule_has_same_identity_in_change_and_project_scan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"app.py": "def f(x):\n    return x\n"})
            (repo / "app.py").write_text("def f(x):\n    return eval(x)\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "risk", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)
            change = next(
                signal
                for signal in scan_change(repo=repo, base_sha=base, candidate_sha=candidate).signals
                if signal.rule_id == "security.dynamic-eval"
            )
            project = next(
                signal
                for signal in scan_project(repo=repo).signals
                if signal.rule_id == "security.dynamic-eval"
            )
            self.assertEqual(change.debt_id, project.debt_id)
            self.assertEqual(change.verification["type"], "project-rule")

    def test_change_only_rules_are_not_mislabeled_as_project_replay(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"app.py": "def f(x):\n    return x\n"})
            migration = repo / "migrations" / "001.sql"
            migration.parent.mkdir()
            migration.write_text("DROP TABLE users;\n", encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "migration", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)
            migration_signal = next(
                signal
                for signal in scan_change(repo=repo, base_sha=base, candidate_sha=candidate).signals
                if signal.rule_id == "migration.no-obvious-rollback"
            )
            self.assertEqual(migration_signal.measurement, "heuristic")
            self.assertEqual(migration_signal.verification["type"], "change-review")
            self.assertIn("does not prove rollback is impossible", migration_signal.explanation)

    def test_project_scan_finds_duplicate_block_and_local_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            block = "\n".join(
                [f"    value_{i} = input_value + {i}  # duplicated long statement {i}" for i in range(10)]
            )
            init_repo(
                repo,
                {
                    "a.py": "def alpha(input_value):\n" + block + "\n    return value_9\n",
                    "b.py": "def beta(input_value):\n" + block + "\n    return value_9\n",
                    "web/a.js": "import value from './b'\nexport default value + 1\n",
                    "web/b.js": "import value from './a'\nexport default value + 1\n",
                },
            )
            rules = {
                signal.rule_id
                for signal in scan_project(repo=repo, max_scan_files=100, max_duplicate_signals=10).signals
            }
            self.assertIn("project.exact-duplicate-block", rules)
            self.assertIn("project.local-import-cycle", rules)


if __name__ == "__main__":
    unittest.main()
