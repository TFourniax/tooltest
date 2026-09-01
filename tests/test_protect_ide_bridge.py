from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from diffwitness import ide_plugin


class ProtectIdeBridgeTests(unittest.TestCase):
    def test_block_maps_to_provider_deny_without_allow_override(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            with (
                mock.patch("diffwitness.ide_plugin.repo_root", return_value=repo),
                mock.patch(
                    "diffwitness.protect.evaluate_pre_tool",
                    return_value={
                        "decision": "block",
                        "reason": "destructive action",
                        "category": "destructive-git",
                        "rule": "hard-reset",
                    },
                ),
            ):
                result = ide_plugin.protect_pre({"cwd": str(repo), "tool_name": "Bash"})

            self.assertEqual(result["hookSpecificOutput"]["hookEventName"], "PreToolUse")
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertNotEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
            self.assertIn("destructive action", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_strict_confirmation_maps_to_provider_ask(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            with (
                mock.patch("diffwitness.ide_plugin.repo_root", return_value=repo),
                mock.patch(
                    "diffwitness.protect.evaluate_pre_tool",
                    return_value={
                        "decision": "ask",
                        "reason": "dependency installation",
                        "category": "supply-chain",
                        "rule": "dependency-install",
                    },
                ),
            ):
                result = ide_plugin.protect_pre({"cwd": str(repo), "tool_name": "Bash"})

            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_clean_action_emits_no_permission_decision(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            with (
                mock.patch("diffwitness.ide_plugin.repo_root", return_value=repo),
                mock.patch("diffwitness.protect.evaluate_pre_tool", return_value=None),
            ):
                result = ide_plugin.protect_pre({"cwd": str(repo), "tool_name": "Read"})
            self.assertIsNone(result)

    def test_post_tool_feedback_is_explicitly_observed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            with (
                mock.patch("diffwitness.ide_plugin.repo_root", return_value=repo),
                mock.patch(
                    "diffwitness.protect.evaluate_post_tool",
                    return_value={
                        "decision": "observed",
                        "reason": "JSON is invalid",
                        "category": "quality",
                        "rule": "invalid-json",
                    },
                ),
            ):
                result = ide_plugin.protect_post({"cwd": str(repo), "tool_name": "Write"})
            output = result["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "PostToolUse")
            self.assertIn("OBSERVED", output["additionalContext"])
            self.assertNotIn("VERIFIED", output["additionalContext"])

    def test_pre_tool_bridge_failure_fails_closed(self):
        stream = io.StringIO()
        with (
            mock.patch("diffwitness.ide_plugin._read_payload", return_value={"cwd": "."}),
            mock.patch("diffwitness.ide_plugin.protect_pre", side_effect=RuntimeError("boom")),
            redirect_stdout(stream),
        ):
            rc = ide_plugin.ide_hook_cli(["protect-pre"])

        self.assertEqual(rc, 0)
        payload = json.loads(stream.getvalue())
        output = payload["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertNotIn("boom", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
