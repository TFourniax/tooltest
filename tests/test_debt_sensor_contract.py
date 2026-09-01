from __future__ import annotations

import unittest

from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.debt_sensor import DebtSensorResult, merge_sensor_result


class DebtSensorContractTests(unittest.TestCase):
    def test_experimental_kind_alias_is_normalized_before_report_persistence(self) -> None:
        signal = DebtSignal(
            category="architecture",
            rule_id="sensor.contract-test",
            title="Contract test",
            severity="low",
            measurement="heuristic",
            anchor="contract",
            explanation="test",
            points=0,
            verification={"kind": "project-rule", "sensor": "contract-test-v1"},
        )
        report = DebtReport(scope="project", signals=[])
        merge_sensor_result(
            report,
            DebtSensorResult(sensor_id="contract-test-v1", signals=[signal]),
        )
        self.assertEqual(report.signals[0].verification["type"], "project-rule")
        self.assertNotIn("kind", report.signals[0].verification)
        self.assertEqual(report.total_points, 0)


if __name__ == "__main__":
    unittest.main()
