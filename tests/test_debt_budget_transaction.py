from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_budget import evaluate_and_record
from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.ledger import DebtLedger


def signal(anchor: str) -> DebtSignal:
    return DebtSignal(
        category="evidence",
        rule_id=f"budget.{anchor}",
        title=f"Budget debt {anchor}",
        severity="high",
        measurement="causal",
        anchor=anchor,
        explanation="atomic admission test",
        verification={"type": "mutation-necessity"},
    )


class DebtBudgetTransactionTests(unittest.TestCase):
    def test_two_stale_agents_cannot_both_consume_the_same_remaining_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            first = DebtLedger.load(path)
            second = DebtLedger.load(path)
            config = {"max_total": 5}

            first_budget, first_stats = evaluate_and_record(
                ledger=first,
                change=DebtReport(scope="change", signals=[signal("first")]),
                debt_config=config,
                actor="first-agent",
                record_if_budget_fails=False,
            )
            second_budget, second_stats = evaluate_and_record(
                ledger=second,
                change=DebtReport(scope="change", signals=[signal("second")]),
                debt_config=config,
                actor="second-agent",
                record_if_budget_fails=False,
            )

            self.assertTrue(first_budget.passed)
            self.assertEqual(first_stats["introduced"], 1)
            self.assertFalse(second_budget.passed)
            self.assertEqual(second_budget.active_total, 5)
            self.assertEqual(second_budget.projected_total, 10)
            self.assertEqual(second_stats, {"introduced": 0, "reopened": 0, "refreshed": 0})

            reloaded = DebtLedger.load(path)
            self.assertEqual(reloaded.active_points(), 5)
            self.assertEqual(len(reloaded.events), 1)

    def test_explicit_accounting_can_record_a_real_over_budget_change(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            ledger = DebtLedger.load(path)
            budget, stats = evaluate_and_record(
                ledger=ledger,
                change=DebtReport(scope="change", signals=[signal("real-over-budget")]),
                debt_config={"max_total": 0},
                actor="accounting",
                record_if_budget_fails=True,
            )
            self.assertFalse(budget.passed)
            self.assertEqual(stats["introduced"], 1)
            self.assertEqual(DebtLedger.load(path).active_points(), 5)

    def test_read_only_atomic_budget_check_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            ledger = DebtLedger.load(path)
            budget, stats = evaluate_and_record(
                ledger=ledger,
                change=DebtReport(scope="change", signals=[signal("read-only")]),
                debt_config={"max_total": 10},
                record=False,
            )
            self.assertTrue(budget.passed)
            self.assertEqual(stats, {"introduced": 0, "reopened": 0, "refreshed": 0})
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
