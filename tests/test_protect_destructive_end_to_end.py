from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.ide_plugin import protect_pre
from diffwitness.protect import protection_summary, protect_status, set_protect_mode


class ProtectDestructiveEndToEndTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return proc.stdout.strip()

    def test_forced_git_clean_is_denied_before_execution_and_never_mints_proof(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "protect-e2e@example.test")
            self.git(repo, "config", "user.name", "Protect E2E")
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self.git(repo, "add", "app.py")
            self.git(repo, "commit", "-qm", "base")

            # Make Claude a configured local adapter without depending on a machine-global CLI.
            (repo / ".claude").mkdir()
            status = set_protect_mode(repo, "builtin", policy="standard")
            self.assertEqual(status["mode"], "builtin")
            self.assertIn("claude", status["adapters"])

            sentinel = repo / "DO_NOT_DELETE.txt"
            sentinel.write_text("survive\n", encoding="utf-8")
            payload = {
                "cwd": str(repo),
                "provider": "claude",
                "tool_name": "Bash",
                "tool_input": {"command": "git clean -fdx"},
            }
            decision = protect_pre(payload)
            self.assertIsNotNone(decision)
            assert decision is not None
            hook = decision["hookSpecificOutput"]
            self.assertEqual(hook["hookEventName"], "PreToolUse")
            self.assertEqual(hook["permissionDecision"], "deny")
            self.assertIn("clean", hook["permissionDecisionReason"].lower())

            # Protect is a pre-execution decision boundary. The destructive command itself is never
            # executed by DiffWitness and the sentinel therefore remains untouched.
            self.assertTrue(sentinel.is_file())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "survive\n")

            summary = protection_summary(repo)
            self.assertTrue(summary["integrity"])
            self.assertGreaterEqual(summary["decisions"].get("block", 0), 1)
            self.assertGreaterEqual(summary["categories"].get("destructive-git", 0), 1)
            live = protect_status(repo)["adapters"]["claude"]
            self.assertTrue(live["activeSeen"])
            self.assertTrue(live["ready"])

            # Runtime safety observations can never silently become software Proof.
            self.assertFalse((repo / ".git" / "diffwitness" / "change-envelope.json").exists())

            safe = protect_pre(
                {
                    "cwd": str(repo),
                    "provider": "claude",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status --short"},
                }
            )
            self.assertIsNone(safe)
            self.assertTrue(sentinel.is_file())


if __name__ == "__main__":
    unittest.main()
