from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.ide_handoff import _MAX_RETRIES, _retry_or_block, finalize_ide_session
from diffwitness.proof_cli import _state_path


class IdeHandoffFailClosedTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "handoff@example.test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Handoff Test"], cwd=repo, check=True)
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
        return repo

    def test_missing_or_invalid_native_start_capture_terminates_unverified_without_a_loop(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            missing = finalize_ide_session(
                {
                    "cwd": str(repo),
                    "session_id": "missing",
                    "stop_hook_active": True,
                },
                repo=repo,
            )
            self.assertNotIn("decision", missing)
            self.assertIs(missing["continue"], False)
            self.assertIn("not armed", missing["stopReason"])

            _state_path(repo, "invalid").write_text("{}", encoding="utf-8")
            invalid = finalize_ide_session(
                {
                    "cwd": str(repo),
                    "session_id": "invalid",
                    "stop_hook_active": True,
                },
                repo=repo,
            )
            self.assertNotIn("decision", invalid)
            self.assertIs(invalid["continue"], False)
            self.assertIn("state is invalid", invalid["stopReason"])

    def test_exhausted_continuation_budget_never_becomes_approval(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            state = {"retries": 0}
            for _ in range(_MAX_RETRIES):
                result = _retry_or_block(path, state, "evidence still fails")
                self.assertEqual(result["decision"], "block", result)
                state = json.loads(path.read_text(encoding="utf-8"))

            result = _retry_or_block(path, state, "evidence still fails")
            self.assertNotIn("decision", result)
            self.assertIs(result["continue"], False)
            self.assertIn("human intervention", result["stopReason"])
            state = json.loads(path.read_text(encoding="utf-8"))

            repeated = _retry_or_block(path, state, "evidence still fails")
            self.assertNotIn("decision", repeated)
            self.assertIs(repeated["continue"], False)
            self.assertGreater(state["retries"], _MAX_RETRIES)


if __name__ == "__main__":
    unittest.main()
