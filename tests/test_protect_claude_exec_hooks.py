from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import diffwitness.protect as protect


class ProtectClaudeExecHookTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        state = repo / ".git" / "diffwitness"
        state.mkdir(parents=True)
        (state / "setup-scope.json").write_text(
            json.dumps({"schema": "diffwitness.setup-scope.v1", "adapters": ["claude"]}),
            encoding="utf-8",
        )
        return repo

    def test_claude_protect_uses_exec_form_and_preserves_native_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            settings = repo / ".claude" / "settings.local.json"
            settings.parent.mkdir()
            dw_command = r"C:\Users\tester\.local\bin\dw.exe"
            settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "SessionStart": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": dw_command,
                                            "args": ["ide-hook", "session-start", "--provider", "claude"],
                                            "timeout": 10,
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            before = protect.detect_external_harness(repo)
            self.assertFalse(before["otherHookActivityDetected"])

            with mock.patch("diffwitness.protect._resolve_dw_command", return_value=dw_command):
                enabled = protect.set_protect_mode(repo, "builtin", force=True)
            self.assertEqual(enabled["health"], "ready")
            self.assertFalse(enabled["otherHookActivityDetected"])

            payload = json.loads(settings.read_text(encoding="utf-8"))
            pre = payload["hooks"]["PreToolUse"][0]["hooks"][0]
            post = payload["hooks"]["PostToolUse"][0]["hooks"][0]
            self.assertEqual(pre["command"], dw_command)
            self.assertEqual(pre["args"], ["ide-hook", "protect-pre", "--provider", "claude"])
            self.assertEqual(post["command"], dw_command)
            self.assertEqual(post["args"], ["ide-hook", "protect-post", "--provider", "claude"])

            # Simulate the shell-form hook emitted by the pre-fix release. Re-enabling Protect must
            # migrate it away rather than leave duplicate or broken runtime guards behind.
            legacy_pre = protect._managed_command(dw_command, "protect-pre", "claude")
            payload["hooks"]["PreToolUse"].append(
                {"hooks": [{"type": "command", "command": legacy_pre, "timeout": 3}]}
            )
            settings.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch("diffwitness.protect._resolve_dw_command", return_value=dw_command):
                protect.set_protect_mode(repo, "builtin", force=True)

            migrated = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(len(migrated["hooks"]["PreToolUse"]), 1)
            migrated_pre = migrated["hooks"]["PreToolUse"][0]["hooks"][0]
            self.assertEqual(migrated_pre["command"], dw_command)
            self.assertEqual(migrated_pre["args"], ["ide-hook", "protect-pre", "--provider", "claude"])

            with mock.patch("diffwitness.protect._resolve_dw_command", return_value=dw_command):
                disabled = protect.set_protect_mode(repo, "off")
            self.assertEqual(disabled["mode"], "off")
            after = json.loads(settings.read_text(encoding="utf-8"))
            self.assertIn("SessionStart", after["hooks"])
            self.assertNotIn("PreToolUse", after["hooks"])
            self.assertNotIn("PostToolUse", after["hooks"])


if __name__ == "__main__":
    unittest.main()
