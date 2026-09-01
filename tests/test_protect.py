from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.protect import (
    detect_external_harness,
    evaluate_post_tool,
    evaluate_pre_tool,
    load_protect_config,
    protect_status,
    protection_summary,
    set_protect_mode,
)


class ProtectTests(unittest.TestCase):
    def repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        (repo / ".git" / "diffwitness").mkdir(parents=True)
        return repo

    def test_default_is_off_and_never_gates(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.assertEqual(load_protect_config(repo)["mode"], "off")
            result = evaluate_pre_tool(
                repo,
                {
                    "session_id": "s1",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git reset --hard HEAD~1"},
                },
            )
            self.assertIsNone(result)
            self.assertEqual(protection_summary(repo)["count"], 0)

    def test_external_harness_marker_delegates_without_force(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".interlinked").mkdir()
            detection = detect_external_harness(repo)
            self.assertTrue(detection["externalHarnessDetected"])
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                status = set_protect_mode(repo, "builtin")
            self.assertEqual(status["mode"], "external")
            self.assertEqual(status["health"], "delegated")
            self.assertFalse((repo / ".claude" / "settings.local.json").exists())

    def test_force_builtin_merges_and_disable_preserves_foreign_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            claude = repo / ".claude"
            claude.mkdir()
            settings = claude / "settings.local.json"
            foreign = {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "other-harness check",
                                    "timeout": 2,
                                }
                            ]
                        }
                    ]
                }
            }
            settings.write_text(json.dumps(foreign), encoding="utf-8")
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                enabled = set_protect_mode(repo, "builtin", force=True)
            self.assertEqual(enabled["mode"], "builtin")
            self.assertTrue(enabled["adapters"]["claude"]["installed"])
            installed = settings.read_text(encoding="utf-8")
            self.assertIn("other-harness check", installed)
            self.assertIn("protect-pre", installed)
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                disabled = set_protect_mode(repo, "off")
            self.assertEqual(disabled["mode"], "off")
            after = settings.read_text(encoding="utf-8")
            self.assertIn("other-harness check", after)
            self.assertNotIn("protect-pre", after)
            self.assertNotIn("protect-post", after)

    def test_standard_blocks_destructive_git_without_recording_raw_command(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".claude").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", policy="standard", force=True)
            command = "git reset --hard HEAD~1"
            result = evaluate_pre_tool(
                repo,
                {
                    "session_id": "secret-session-name",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                },
            )
            self.assertEqual(result["decision"], "block")
            receipt_text = (repo / ".git" / "diffwitness" / "protection.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(command, receipt_text)
            self.assertNotIn("secret-session-name", receipt_text)
            self.assertIn("hard-reset", receipt_text)

    def test_secret_is_blocked_but_secret_value_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".claude").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", force=True)
            secret = "ghp_" + "A" * 40
            result = evaluate_pre_tool(
                repo,
                {
                    "session_id": "s2",
                    "tool_name": "Write",
                    "tool_input": {"file_path": "app.py", "content": f"TOKEN = '{secret}'"},
                },
            )
            self.assertEqual(result["decision"], "block")
            raw = (repo / ".git" / "diffwitness" / "protection.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(secret, raw)
            self.assertIn("secret-exposure", raw)

    def test_write_outside_repository_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self.repo(root)
            (repo / ".claude").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", force=True)
            result = evaluate_pre_tool(
                repo,
                {
                    "session_id": "s3",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(root / "outside.txt"), "content": "safe"},
                },
            )
            self.assertEqual(result["rule"], "write-outside-repository")

    def test_observe_policy_records_but_does_not_block(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".claude").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", policy="observe", force=True)
            result = evaluate_pre_tool(
                repo,
                {
                    "session_id": "s4",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git push --force origin main"},
                },
            )
            self.assertIsNone(result)
            summary = protection_summary(repo)
            self.assertEqual(summary["decisions"]["observed"], 1)

    def test_strict_dependency_install_requests_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".claude").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", policy="strict", force=True)
            result = evaluate_pre_tool(
                repo,
                {
                    "session_id": "s5",
                    "tool_name": "Bash",
                    "tool_input": {"command": "npm install left-pad"},
                },
            )
            self.assertEqual(result["decision"], "ask")
            self.assertEqual(result["rule"], "dependency-install")

    def test_post_tool_reports_invalid_json_as_observed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".claude").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", force=True)
            path = repo / "settings.json"
            path.write_text('{"broken":', encoding="utf-8")
            result = evaluate_post_tool(
                repo,
                {
                    "session_id": "s6",
                    "tool_name": "Write",
                    "tool_input": {"file_path": "settings.json"},
                },
            )
            self.assertEqual(result["decision"], "observed")
            self.assertEqual(result["rule"], "invalid-json")

    def test_receipt_integrity_detects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".claude").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", force=True)
            evaluate_pre_tool(
                repo,
                {
                    "session_id": "s7",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git reset --hard HEAD"},
                },
            )
            path = repo / ".git" / "diffwitness" / "protection.jsonl"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["message"] = "tampered"
            path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            self.assertFalse(protection_summary(repo)["integrity"])

    def test_status_is_bounded_and_contains_no_raw_agent_data(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            status = protect_status(repo)
            rendered = json.dumps(status)
            self.assertEqual(status["mode"], "off")
            self.assertNotIn("rawPrompt", rendered)
            self.assertNotIn("rawCommand", rendered)
            self.assertNotIn("sourceCode", rendered)


if __name__ == "__main__":
    unittest.main()
