from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.ledger import DebtLedger, LedgerError


class LedgerTests(unittest.TestCase):
    def signal(self, anchor="a", verification=None):
        return DebtSignal(category="evidence", rule_id="r", title="Debt", severity="medium", measurement="causal", anchor=anchor, explanation="why", path="app.py", verification=verification or {"type": "rerun-proof"})

    def test_event_sourced_lifecycle_and_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"; ledger = DebtLedger.load(path); signal = self.signal()
            ledger.record_report(DebtReport(scope="change", signals=[signal])); self.assertTrue(ledger.items()[signal.debt_id].active)
            ledger.resolve(signal.debt_id, reason="verified", verification={"result": "pass"}); self.assertFalse(ledger.items()[signal.debt_id].active)
            ledger.record_report(DebtReport(scope="change", signals=[signal])); reopened = ledger.items()[signal.debt_id]
            self.assertTrue(reopened.active); self.assertEqual(reopened.reopen_count, 1)

    def test_tampering_breaks_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"; ledger = DebtLedger.load(path); ledger.record_report(DebtReport(scope="change", signals=[self.signal()]))
            value = json.loads(path.read_text(encoding="utf-8").splitlines()[0]); value["payload"]["signal"]["points"] = 99; path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(LedgerError): DebtLedger.load(path)

    def test_project_reconciliation_only_closes_project_rules(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = DebtLedger.load(Path(td) / "ledger.jsonl"); project = self.signal(anchor="project", verification={"type": "project-rule"}); causal = self.signal(anchor="causal", verification={"type": "mutation-necessity"})
            ledger.record_report(DebtReport(scope="project", signals=[project, causal])); ledger.reconcile_project_report(DebtReport(scope="project", signals=[])); state = ledger.items()
            self.assertFalse(state[project.debt_id].active); self.assertTrue(state[causal.debt_id].active)


if __name__ == "__main__": unittest.main()
