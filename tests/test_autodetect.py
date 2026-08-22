from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from diffwitness.autodetect import default_evidence, detect_evidence


class AutoDetectTests(unittest.TestCase):
    def test_prefers_declared_pnpm_test_script(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "typecheck": "tsc --noEmit"}}),
                encoding="utf-8",
            )
            (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
            plans = detect_evidence(repo)
            self.assertEqual(plans[0].command, "pnpm test")
            self.assertEqual(plans[0].confidence, "high")
            self.assertEqual(plans[1].command, "pnpm typecheck")

    def test_detects_pytest_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
            plan = default_evidence(repo)
            self.assertIsNotNone(plan)
            self.assertEqual(plan.command, "python -m pytest -q")
            self.assertEqual(plan.confidence, "high")

    def test_falls_back_to_unittest_for_plain_tests_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "tests").mkdir()
            plan = default_evidence(repo)
            self.assertIsNotNone(plan)
            self.assertEqual(plan.command, "python -m unittest discover -s tests -q")
            self.assertEqual(plan.confidence, "medium")


if __name__ == "__main__":
    unittest.main()
