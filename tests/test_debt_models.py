from __future__ import annotations

import unittest

from diffwitness.debt_models import DebtReport, DebtSignal, dedupe_signals


class DebtModelTests(unittest.TestCase):
    def signal(self, **overrides):
        values = dict(category="evidence", rule_id="proof.unwitnessed", title="Unwitnessed", severity="medium", measurement="causal", anchor="h1", explanation="x", path="app.py")
        values.update(overrides); return DebtSignal(**values)

    def test_stable_identity_ignores_explanation_and_points(self):
        self.assertEqual(self.signal(explanation="first", points=3).debt_id, self.signal(explanation="second", points=8).debt_id)

    def test_report_is_additive_and_explicit(self):
        report = DebtReport(scope="change", signals=[self.signal(), self.signal(category="security", rule_id="security.eval", anchor="e1", severity="critical", measurement="deterministic")])
        self.assertEqual(report.total_points, 11); self.assertEqual(report.by_category, {"evidence": 3, "security": 8}); self.assertEqual(report.by_measurement, {"causal": 3, "deterministic": 8})

    def test_dedupe_keeps_strongest_same_lineage(self):
        values = dedupe_signals([self.signal(severity="low", measurement="heuristic"), self.signal(severity="high", measurement="causal")])
        self.assertEqual(len(values), 1); self.assertEqual(values[0].severity, "high"); self.assertEqual(values[0].measurement, "causal")


if __name__ == "__main__": unittest.main()
