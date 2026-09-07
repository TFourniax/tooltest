from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.doctor import doctor_cli
from diffwitness.idleproof_sidecar import integration_install
from diffwitness.native_activation import native_activation_summary, record_native_activation
from diffwitness.protect import evaluate_pre_tool, protect_status, set_protect_mode
from diffwitness.protect_ui import _render_status
from diffwitness.setup import _protect_human_lines
from diffwitness.status_cli import build_project_status


class ProviderTrustReadinessTests(unittest.TestCase):
    def test_codex_reenable_waits_for_observation_without_inventing_trust_state(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            for args in (("init", "-q"), ("-c", "user.name=Test", "-c", "user.email=test@example.test",
                         "commit", "--allow-empty", "-qm", "baseline")):
                subprocess.run(["git", *args], cwd=repo, check=True)
            integration_install(repo, agent="codex", dw_command="dw")
            record_native_activation(repo, "codex")
            native_before = native_activation_summary(repo, ["codex"])
            enabled = set_protect_mode(repo, "builtin", force=True)
            hooks = repo / ".codex" / "hooks.json"
            enabled_hooks = json.loads(hooks.read_text(encoding="utf-8"))
            payload = {"provider": "codex", "session_id": "readiness-regression",
                       "tool_name": "Bash", "tool_input": {"command": "git status --short"}}
            self.assertIsNone(evaluate_pre_tool(repo, payload))
            observed = protect_status(repo)
            self.assertTrue(observed["adapters"]["codex"]["ready"])
            set_protect_mode(repo, "off")
            disabled_hooks = json.loads(hooks.read_text(encoding="utf-8"))
            for event in ("SessionStart", "UserPromptSubmit", "Stop"):
                self.assertEqual(disabled_hooks["hooks"][event], enabled_hooks["hooks"][event])
            reenabled = set_protect_mode(repo, "builtin", force=True)
            self.assertEqual(json.loads(hooks.read_text(encoding="utf-8")), enabled_hooks)
            self.assertEqual(native_activation_summary(repo, ["codex"]), native_before)
            self.assertFalse((repo / ".claude").exists())
            for state in (enabled, reenabled):
                adapter = state["adapters"]["codex"]
                self.assertTrue(adapter["installed"])
                self.assertFalse(adapter["ready"])
                self.assertFalse(adapter["activeSeen"])
                self.assertEqual(adapter["activation"], "awaiting-first-observation")
                self.assertEqual(adapter["providerTrust"], "unknown")
                for guided in (True, False):
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        _render_status(state, guided=guided)
                    rendered = output.getvalue().lower()
                    self.assertIn("/hooks", rendered)
                    self.assertNotIn("encore nécessaire", rendered)
                    self.assertNotIn("trust is pending", rendered)
                    self.assertNotIn("pending provider trust", "\n".join(_protect_human_lines(state, guided=guided)))
            status = build_project_status(repo)
            action = next(a for a in status["next_actions"] if a["kind"] == "activate-provider-protection")
            self.assertNotIn("finish runtime approval", action["title"].lower())
            self.assertNotIn("still require", action["reason"])
            self.assertNotEqual(status["current_worktree_verification"]["status"], "accepted")
            for view in ("guided", "technical"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    doctor_cli(["--repo", str(repo), "--view", view])
                self.assertNotIn("approbation du provider encore nécessaire", output.getvalue())
                self.assertNotIn("Pending provider trust", output.getvalue())
            self.assertIsNone(evaluate_pre_tool(repo, payload))
            final = protect_status(repo)
            self.assertTrue(final["adapters"]["codex"]["ready"])
            self.assertIsNotNone(final["adapters"]["codex"]["observedAt"])
            self.assertEqual(final["adapters"]["codex"]["providerTrust"], "unknown")
            self.assertEqual(final["adapters"]["codex"]["activation"], "observed")
            self.assertTrue(final["receipts"]["integrity"])
            self.assertEqual(final["receipts"]["count"], observed["receipts"]["count"] + 1)

    def test_missing_native_observation_does_not_prove_pending_approval(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            native = native_activation_summary(repo, ["codex", "claude"])
            self.assertEqual(native["pendingTrustAdapters"], [])
            self.assertEqual(native["unknownTrustAdapters"], ["codex"])
            self.assertFalse(native["adapters"]["codex"]["requiresProviderTrust"])
            self.assertEqual(native["adapters"]["codex"]["providerTrust"], "unknown")
            self.assertEqual(native["adapters"]["claude"]["providerTrust"], "not-required")
            self.assertFalse(native["fullyObserved"])


if __name__ == "__main__":
    unittest.main()
