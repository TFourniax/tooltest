from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diffwitness.config import load_config


class DebtConfigTests(unittest.TestCase):
    def test_top_level_debt_and_category_tables_normalize(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); (repo / ".diffwitness.toml").write_text('[diffwitness]\ntest = "pytest -q"\n\n[debt]\nmax_total = 100\nmax_per_change = 12\nauto_record = true\n\n[debt.security]\nmax = 10\n[debt.evidence]\nmax = 30\n', encoding="utf-8")
            config = load_config(repo); self.assertEqual(config["debt"]["max_total"], 100); self.assertEqual(config["debt"]["category_limits"], {"security": 10, "evidence": 30})

    def test_unknown_debt_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); (repo / ".diffwitness.toml").write_text('[debt]\nmagical_score = 99\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unknown DiffWitness debt config"): load_config(repo)

    def test_nested_diffwitness_debt_supported(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); (repo / ".diffwitness.toml").write_text('[diffwitness]\ntest = "pytest -q"\n[diffwitness.debt]\nmax_per_change = 9\n', encoding="utf-8")
            self.assertEqual(load_config(repo)["debt"]["max_per_change"], 9)


if __name__ == "__main__": unittest.main()
