from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from diffwitness.ide_handoff import _MAX_RETRIES, _retry_or_block


class IdeHandoffFailClosedTests(unittest.TestCase):
    def test_exhausted_continuation_budget_never_becomes_approval(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            state = {"retries": 0}
            result = None
            for _ in range(_MAX_RETRIES + 2):
                result = _retry_or_block(path, state, "evidence still fails")
                self.assertEqual(result["decision"], "block", result)
                state = json.loads(path.read_text(encoding="utf-8"))

            self.assertIsNotNone(result)
            self.assertIn("human intervention", result["reason"])
            self.assertGreater(state["retries"], _MAX_RETRIES)


if __name__ == "__main__":
    unittest.main()
