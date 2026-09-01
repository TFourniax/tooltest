from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from diffwitness.debt_history import trend
from diffwitness.debt_models import DebtSignal
from diffwitness.ledger import DebtLedger


class DebtHistoryTests(unittest.TestCase):
    def test_trend_reconstructs_prior_balance_from_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ledger = DebtLedger.load(Path(td) / "ledger.jsonl")
            a = DebtSignal(category="evidence", rule_id="a", title="a", severity="medium", measurement="causal", anchor="a", explanation="a")
            b = DebtSignal(category="security", rule_id="b", title="b", severity="high", measurement="deterministic", anchor="b", explanation="b")
            ledger.append(event_type="introduced", debt_id=a.debt_id, payload={"signal": a.to_dict()}, timestamp="2026-06-01T00:00:00+00:00")
            ledger.append(event_type="introduced", debt_id=b.debt_id, payload={"signal": b.to_dict()}, timestamp="2026-08-10T00:00:00+00:00")
            value = trend(ledger, days=30, now=datetime(2026, 8, 16, tzinfo=timezone.utc))
            self.assertEqual(value.start_points, 3)
            self.assertEqual(value.current_points, 8)
            self.assertEqual(value.delta_points, 5)
            self.assertEqual(value.introduced, 1)


if __name__ == "__main__":
    unittest.main()
