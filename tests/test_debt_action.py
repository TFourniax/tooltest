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

    def test_action_restores_but_never_pushes_cumulative_ledger(self) -> None:
        root = Path(__file__).resolve().parents[1]
        action = (root / "action.yml").read_text(encoding="utf-8")
        self.assertIn("ledger-sync:", action)
        self.assertIn("ledger-remote:", action)
        self.assertIn("ledger-ref:", action)
        self.assertIn('dw ledger pull --remote "$DW_LEDGER_REMOTE" --ref "$DW_LEDGER_REF"', action)
        # Pull-request execution may read the trusted baseline but must never mutate the shared
        # ledger ref. Publishing checkpoints belongs in a trusted post-merge workflow.
        self.assertNotIn("dw ledger push", action)


if __name__ == "__main__":
    unittest.main()
