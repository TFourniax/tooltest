from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diffwitness.config import load_config


class ConfigTests(unittest.TestCase):
    def test_unknown_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".diffwitness.toml").write_text(
                '[diffwitness]\ntest = "pytest -q"\nstrategyy = "adaptive"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Unknown DiffWitness config key"):
                load_config(repo)

    def test_invalid_policy_and_budget_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            config = repo / ".diffwitness.toml"
            config.write_text(
                '[diffwitness]\ntest = "pytest -q"\npolicy = "magic"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "policy"):
                load_config(repo)
            config.write_text(
                '[diffwitness]\ntest = "pytest -q"\nadaptive_budget = 0\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "adaptive_budget"):
                load_config(repo)
            config.write_text(
                '[diffwitness]\ntest = "pytest -q"\nmax_total_seconds = 0\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "max_total_seconds"):
                load_config(repo)

    def test_valid_gate_configuration_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".diffwitness.toml").write_text(
                '[diffwitness]\n'
                'test = "pytest -q"\n'
                'policy = "strict"\n'
                'strategy = "auto"\n'
                'adaptive_threshold = 20\n'
                'adaptive_budget = 50\n'
                'max_total_seconds = 420\n'
                'stability_runs = 3\n'
                'ignore = ["generated/**"]\n',
                encoding="utf-8",
            )
            config = load_config(repo)
            self.assertEqual(config["policy"], "strict")
            self.assertEqual(config["adaptive_budget"], 50)
            self.assertEqual(config["max_total_seconds"], 420)
            self.assertEqual(config["ignore"], ["generated/**"])


if __name__ == "__main__":
    unittest.main()
