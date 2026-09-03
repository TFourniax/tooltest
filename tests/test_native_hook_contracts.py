from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.ide_handoff import _block, _success, _terminal_failure
from diffwitness.ide_plugin import session_start, user_prompt_submit


class NativeHookContractTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.check_call(["git", "init", "-q"], cwd=repo)
        subprocess.check_call(["git", "config", "user.email", "hooks@example.test"], cwd=repo)
        subprocess.check_call(["git", "config", "user.name", "Hook Contract"], cwd=repo)
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "app.py"], cwd=repo)
        subprocess.check_call(["git", "commit", "-qm", "base"], cwd=repo)
        return repo

    def test_stop_success_omits_unsupported_approve_decision(self):
        result = _success("DiffWitness Proof accepted")
        self.assertNotIn("decision", result)
        self.assertNotIn("reason", result)
        self.assertEqual(result["systemMessage"], "DiffWitness Proof accepted")

    def test_stop_block_preserves_block_and_reason(self):
        result = _block("Evidence failed")
        self.assertEqual(result["decision"], "block")
        self.assertEqual(result["reason"], "Evidence failed")
        self.assertEqual(result["systemMessage"], "Evidence failed")

    def test_terminal_stop_failure_never_requests_another_agent_turn(self):
        result = _terminal_failure("SessionStart capture is missing; task is unverified")
        self.assertNotIn("decision", result)
        self.assertIs(result["continue"], False)
        self.assertEqual(result["stopReason"], result["systemMessage"])

    def test_native_prompt_context_never_tells_active_agent_to_launch_guard(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            payload = {
                "session_id": "native-codex",
                "cwd": str(repo),
                "prompt": "Fix the calculator with the smallest change",
            }
            session_start(payload)
            result = user_prompt_submit(payload)
            self.assertIsNotNone(result)
            context = result["hookSpecificOutput"]["additionalContext"]
            self.assertIn("native DiffWitness task boundary is already armed", context)
            self.assertIn("native Stop hook owns the final Proof/Debt/Continuity handoff", context)
            self.assertNotIn("change-proof: dw guard", context)
            self.assertNotIn("dw guard -- <agent>", context)

    def test_native_prompt_without_session_start_does_not_spawn_fallback_agent(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            result = user_prompt_submit(
                {
                    "session_id": "trust-enabled-after-start",
                    "cwd": str(repo),
                    "prompt": "Make the requested edit",
                }
            )
            self.assertIsNotNone(result)
            context = result["hookSpecificOutput"]["additionalContext"]
            self.assertIn("SessionStart capture was not observed", context)
            self.assertIn("Stop boundary will fail closed", context)
            self.assertIn("Do not run `dw guard`, `dw gate`, or launch another coding agent", context)
            self.assertNotIn("change-proof: dw guard", context)


if __name__ == "__main__":
    unittest.main()
