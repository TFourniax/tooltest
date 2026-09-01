from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_debt_bridge import sync_debt_history
from diffwitness.continuity_events import ContinuityError, continuity_paths, read_project_events
from diffwitness.continuity_state import ensure_state
from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.ledger import DebtLedger


class ContinuityDebtBridgeTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def repo(self, root: Path) -> tuple[Path, str, str, str]:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "continuity-debt@example.test")
        self.git(repo, "config", "user.name", "Continuity Debt Test")
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git(repo, "add", "app.py")
        self.git(repo, "commit", "-qm", "base")
        base = self.git(repo, "rev-parse", "HEAD")
        (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.git(repo, "add", "app.py")
        self.git(repo, "commit", "-qm", "candidate")
        candidate = self.git(repo, "rev-parse", "HEAD")
        tree = self.git(repo, "rev-parse", "HEAD^{tree}")
        return repo, base, candidate, tree

    def report(self, repo: Path, base: str, candidate: str, tree: str) -> tuple[DebtReport, DebtSignal]:
        signal = DebtSignal(
            category="test",
            rule_id="continuity.test-gap",
            title="Partial refund path needs stronger evidence",
            severity="medium",
            measurement="deterministic",
            anchor="partial-refund-test-gap",
            explanation="This intentionally verbose explanation must not be copied into ProjectEvent history.",
            path="app.py",
            line=1,
        )
        report = DebtReport(
            scope="change",
            signals=[signal],
            repo=str(repo),
            base_sha=base,
            candidate_sha=candidate,
            candidate_tree=tree,
            certificate_id="dw2_continuity_test",
        )
        return report, signal

    def test_full_ledger_lifecycle_projects_idempotently(self):
        with tempfile.TemporaryDirectory() as td:
            repo, base, candidate, tree = self.repo(Path(td))
            report, signal = self.report(repo, base, candidate, tree)
            ledger_path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            ledger = DebtLedger.load(ledger_path)
            ledger.record_report(report, actor="diffwitness")
            ledger.accept(signal.debt_id, reason="temporary known tradeoff", actor="user")
            ledger.unaccept(signal.debt_id, actor="user")
            ledger.resolve(
                signal.debt_id,
                reason="discriminating evidence added",
                verification={"type": "project-rule", "result": "absent"},
                actor="diffwitness",
            )
            ledger.record_report(report, actor="diffwitness")

            first = sync_debt_history(repo)
            self.assertEqual(first["ledger_events"], 5)
            self.assertEqual(first["created"], 5)
            second = sync_debt_history(repo)
            self.assertEqual(second["created"], 0)

            events = [event for event in read_project_events(continuity_paths(repo).events) if event["subject"]["id"] == signal.debt_id]
            self.assertEqual(
                [event["event_type"] for event in events],
                ["debt.introduced", "debt.accepted", "debt.unaccepted", "debt.resolved", "debt.reopened"],
            )
            self.assertEqual(events[1]["epistemic_status"], "DECLARED")
            self.assertEqual(events[3]["epistemic_status"], "OBSERVED")
            self.assertTrue(events[0]["relations"])
            self.assertTrue(events[0]["relations"][0]["target"]["id"].startswith("dwchg_"))

            state = ensure_state(repo)
            conn = sqlite3.connect(state)
            try:
                row = conn.execute(
                    "select status,accepted,category,rule_id,title,points,path,introduced_change_id,last_change_id from debts where debt_id=?",
                    (signal.debt_id,),
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "open")
            self.assertEqual(row[1], 0)
            self.assertEqual(row[2], "test")
            self.assertEqual(row[3], "continuity.test-gap")
            self.assertEqual(row[5], 3)
            self.assertEqual(row[6], "app.py")
            self.assertTrue(row[7].startswith("dwchg_"))
            self.assertTrue(row[8].startswith("dwchg_"))

            raw = continuity_paths(repo).events.read_text(encoding="utf-8")
            self.assertNotIn("intentionally verbose explanation", raw)

    def test_corrupt_debt_ledger_never_becomes_project_history(self):
        with tempfile.TemporaryDirectory() as td:
            repo, base, candidate, tree = self.repo(Path(td))
            report, _ = self.report(repo, base, candidate, tree)
            ledger_path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            ledger = DebtLedger.load(ledger_path)
            ledger.record_report(report)
            lines = ledger_path.read_text(encoding="utf-8").splitlines()
            value = json.loads(lines[0])
            value["payload"]["signal"]["title"] = "tampered"
            ledger_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(ContinuityError):
                sync_debt_history(repo)
            self.assertFalse(continuity_paths(repo).events.exists())


if __name__ == "__main__":
    unittest.main()
