from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.ledger import DebtLedger, LedgerError


class LedgerCorruptionTests(unittest.TestCase):
    def signal(self) -> DebtSignal:
        return DebtSignal(
            category="evidence",
            rule_id="corruption",
            title="Debt",
            severity="medium",
            measurement="causal",
            anchor="corruption-fixture",
            explanation="why",
            path="app.py",
            verification={"type": "rerun-proof"},
        )

    def test_truncated_jsonl_tail_fails_closed_and_is_not_repaired_silently(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            ledger = DebtLedger.load(path)
            ledger.record_report(DebtReport(scope="change", signals=[self.signal()]))
            valid = path.read_bytes()
            truncated = valid + b'{"schema_version":"debt-ledger-event-1","seq":2'
            path.write_bytes(truncated)

            with self.assertRaises(LedgerError):
                DebtLedger.load(path)

            self.assertEqual(path.read_bytes(), truncated, "load mutated a corrupt ledger instead of failing closed")

    def test_non_object_jsonl_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            path.write_text("[]\n", encoding="utf-8")
            before = path.read_bytes()

            with self.assertRaises(LedgerError):
                DebtLedger.load(path)

            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
