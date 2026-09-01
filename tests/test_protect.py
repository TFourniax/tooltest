from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from diffwitness.protect import (
    ProtectError,
    append_receipt,
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
            self.assertIn("--provider claude", installed)
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                disabled = set_protect_mode(repo, "off")
            self.assertEqual(disabled["mode"], "off")
            after = settings.read_text(encoding="utf-8")
            self.assertIn("other-harness check", after)
            self.assertNotIn("protect-pre", after)
            self.assertNotIn("protect-post", after)

    def test_no_detected_adapter_does_not_create_provider_scaffolds(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                status = set_protect_mode(repo, "builtin", force=True)
            self.assertEqual(status["health"], "degraded")
            self.assertEqual(status["adapters"], {})
            self.assertFalse((repo / ".claude").exists())
            self.assertFalse((repo / ".codex").exists())

    def test_codex_requires_live_activation_then_becomes_ready_after_observed_hook(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".codex").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                enabled = set_protect_mode(repo, "builtin", force=True)
            codex = enabled["adapters"]["codex"]
            self.assertTrue(codex["installed"])
            self.assertFalse(codex["activeSeen"])
            self.assertFalse(codex["ready"])
            self.assertEqual(codex["activation"], "requires-provider-feature-and-trust")
            self.assertEqual(enabled["health"], "degraded")
            rendered = (repo / ".codex" / "hooks.json").read_text(encoding="utf-8")
            self.assertIn("--provider codex", rendered)

            invalid = repo / "probe.json"
            invalid.write_text('{"probe":', encoding="utf-8")
            result = evaluate_post_tool(
                repo,
                {
                    "provider": "codex",
                    "session_id": "codex-live",
                    "tool_name": "apply_patch",
                    "tool_input": {"file_path": "probe.json"},
                },
            )
            self.assertEqual(result["rule"], "invalid-json")
            live = protect_status(repo)
            self.assertEqual(live["health"], "ready")
            self.assertTrue(live["adapters"]["codex"]["activeSeen"])
            self.assertTrue(live["adapters"]["codex"]["ready"])
            self.assertEqual(live["adapters"]["codex"]["activation"], "observed")

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

    def test_strict_dependency_install_requests_confirmation_for_claude(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".claude").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", policy="strict", force=True)
            result = evaluate_pre_tool(
                repo,
                {
                    "provider": "claude",
                    "session_id": "s5",
                    "tool_name": "Bash",
                    "tool_input": {"command": "npm install left-pad"},
                },
            )
            self.assertEqual(result["decision"], "ask")
            self.assertEqual(result["rule"], "dependency-install")

    def test_strict_dependency_install_blocks_on_current_codex_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".codex").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", return_value=None):
                set_protect_mode(repo, "builtin", policy="strict", force=True)
            result = evaluate_pre_tool(
                repo,
                {
                    "provider": "codex",
                    "session_id": "codex-strict",
                    "tool_name": "shell",
                    "tool_input": {"command": "npm install left-pad"},
                },
            )
            self.assertEqual(result["decision"], "block")
            self.assertEqual(result["rule"], "dependency-install")
            self.assertIn("cannot safely request confirmation", result["reason"])

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

    def test_tampered_tail_cannot_be_silently_extended(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            append_receipt(
                repo,
                payload={"provider": "claude", "session_id": "one", "tool_name": "Write"},
                phase="post-tool",
                decision="observed",
                category="quality",
                rule="fixture",
                message="fixture",
            )
            path = repo / ".git" / "diffwitness" / "protection.jsonl"
            path.write_text("{damaged\n", encoding="utf-8")
            with self.assertRaises(ProtectError):
                append_receipt(
                    repo,
                    payload={"provider": "claude", "session_id": "two", "tool_name": "Write"},
                    phase="post-tool",
                    decision="observed",
                    category="quality",
                    rule="second",
                    message="must not append",
                )
            self.assertEqual(path.read_text(encoding="utf-8"), "{damaged\n")
            self.assertFalse(protection_summary(repo)["integrity"])

    def test_parallel_receipt_appends_preserve_one_valid_chain(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))

            def write(index: int) -> None:
                append_receipt(
                    repo,
                    payload={
                        "provider": "claude",
                        "session_id": f"parallel-{index}",
                        "tool_name": "Write",
                    },
                    phase="post-tool",
                    decision="observed",
                    category="quality",
                    rule=f"parallel-{index}",
                    message="parallel fixture",
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(write, range(40)))
            summary = protection_summary(repo)
            self.assertTrue(summary["integrity"])
            self.assertEqual(summary["count"], 40)
            self.assertFalse((repo / ".git" / "diffwitness" / "protection.lock").exists())

    def test_codex_safe_live_hook_promotes_readiness_without_a_risk_finding(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".codex").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", side_effect=lambda name: "/usr/bin/codex" if name == "codex" else None):
                enabled = set_protect_mode(repo, "builtin", force=True)
            self.assertEqual(enabled["health"], "degraded")
            self.assertFalse(enabled["adapters"]["codex"]["ready"])

            result = evaluate_pre_tool(
                repo,
                {
                    "provider": "codex",
                    "session_id": "safe-live",
                    "tool_name": "shell",
                    "tool_input": {"command": "git status --short"},
                },
            )
            self.assertIsNone(result)
            ready = protect_status(repo)
            self.assertEqual(ready["health"], "ready")
            self.assertTrue(ready["adapters"]["codex"]["activeSeen"])
            self.assertTrue(ready["adapters"]["codex"]["ready"])
            self.assertEqual(ready["receipts"]["decisions"].get("active"), 1)
            self.assertNotIn("observed", ready["receipts"]["decisions"])
            self.assertNotIn("block", ready["receipts"]["decisions"])

            evaluate_pre_tool(
                repo,
                {
                    "provider": "codex",
                    "session_id": "safe-live",
                    "tool_name": "shell",
                    "tool_input": {"command": "git diff --stat"},
                },
            )
            self.assertEqual(protection_summary(repo)["decisions"].get("active"), 1)

    def test_parallel_first_codex_hooks_record_one_durable_activation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            (repo / ".codex").mkdir()
            with mock.patch("diffwitness.protect.shutil.which", side_effect=lambda name: "/usr/bin/codex" if name == "codex" else None):
                enabled = set_protect_mode(repo, "builtin", force=True)
            self.assertEqual(enabled["health"], "degraded")

            def safe_hook(index: int) -> None:
                result = evaluate_pre_tool(
                    repo,
                    {
                        "provider": "codex",
                        "session_id": f"activation-{index}",
                        "tool_name": "shell",
                        "tool_input": {"command": "git status --short"},
                    },
                )
                self.assertIsNone(result)

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(safe_hook, range(40)))

            summary = protection_summary(repo)
            self.assertTrue(summary["integrity"])
            self.assertEqual(summary["count"], 1)
            self.assertEqual(summary["decisions"].get("active"), 1)
            config = load_protect_config(repo)
            self.assertIn("codex", config["providerActivation"])
            ready = protect_status(repo)
            self.assertTrue(ready["adapters"]["codex"]["activeSeen"])
            self.assertTrue(ready["adapters"]["codex"]["ready"])

            with mock.patch("diffwitness.protect._iter_receipts", return_value=([], True)):
                durable = protect_status(repo)
            self.assertTrue(durable["adapters"]["codex"]["activeSeen"])
            self.assertTrue(durable["adapters"]["codex"]["ready"])

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
