from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diffwitness.config import load_config, validate_config


class EngineConfigTests(unittest.TestCase):
    def test_engine_command_is_argv_not_shell_text(self):
        config = validate_config({
            "engine": {
                "command": ["dw-private-engine", "--profile", "balanced"],
                "timeout": 1.5,
                "required": False,
            }
        })
        self.assertEqual(config["engine"]["command"][0], "dw-private-engine")

        with self.assertRaisesRegex(ValueError, "array"):
            validate_config({"engine": {"command": "dw-private-engine --unsafe"}})

    def test_required_engine_needs_command(self):
        with self.assertRaisesRegex(ValueError, "requires"):
            validate_config({"engine": {"required": True}})

    def test_top_level_engine_table_loads_without_relaxing_unknown_keys(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".diffwitness.toml").write_text(
                "[diffwitness]\npolicy = \"strict\"\n\n"
                "[engine]\ncommand = [\"dw-private-engine\"]\n"
                "timeout = 2.0\nrequired = false\n",
                encoding="utf-8",
            )
            loaded = load_config(repo)
            self.assertEqual(loaded["policy"], "strict")
            self.assertEqual(loaded["engine"]["command"], ["dw-private-engine"])

        with self.assertRaisesRegex(ValueError, "Unknown DiffWitness engine"):
            validate_config({"engine": {"command": ["x"], "magic": True}})


if __name__ == "__main__":
    unittest.main()
