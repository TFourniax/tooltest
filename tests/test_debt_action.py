from __future__ import annotations

import unittest
from pathlib import Path


class DebtActionContractTests(unittest.TestCase):
    def test_action_exposes_proof_and_debt_outputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        action = (root / "action.yml").read_text(encoding="utf-8")
        self.assertIn("dw debt --base", action)
        self.assertIn("debt_points:", action)
        self.assertIn("debt_projected_total:", action)
        self.assertIn("debt_budget_passed:", action)
        self.assertIn("diffwitness-debt.json", action)
        self.assertIn('exit "$debt_rc"', action)


if __name__ == "__main__":
    unittest.main()
