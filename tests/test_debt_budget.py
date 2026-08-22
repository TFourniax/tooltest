from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_budget import evaluate_budget
from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.ledger import DebtLedger


class DebtBudgetTests(unittest.TestCase):
    def signal(self, category="evidence", anchor="x", severity="medium"):
        return DebtSignal(category=category, rule_id="r." + category, title="x", severity=severity, measurement="deterministic", anchor=anchor, explanation="x")

    def test_total_change_and_category_limits(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = DebtLedger.load(Path(td) / "ledger.jsonl"); existing = self.signal(anchor="existing"); ledger.record_report(DebtReport(scope="change", signals=[existing])); change = DebtReport(scope="change", signals=[self.signal(category="security", anchor="new", severity="high")])
            result = evaluate_budget(ledger=ledger, change=change, debt_config={"max_total": 7, "max_per_change": 4, "category_limits": {"security": 4}})
            self.assertFalse(result.passed); self.assertEqual(result.active_total, 3); self.assertEqual(result.change_points, 5); self.assertEqual(result.projected_total, 8); self.assertEqual(len(result.violations), 3)

    def test_existing_lineage_is_not_double_counted(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = DebtLedger.load(Path(td) / "ledger.jsonl"); signal = self.signal(anchor="same"); ledger.record_report(DebtReport(scope="change", signals=[signal])); result = evaluate_budget(ledger=ledger, change=DebtReport(scope="change", signals=[signal]), debt_config={})
            self.assertEqual(result.change_points, 0); self.assertEqual(result.projected_total, 3)


if __name__ == "__main__": unittest.main()
