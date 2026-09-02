from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.protect import evaluate_pre_tool, set_protect_mode


class ProtectCommandNormalizationTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        (repo / ".git" / "diffwitness").mkdir(parents=True)
        (repo / ".claude").mkdir()
        with mock.patch("diffwitness.protect.shutil.which", return_value=None):
            set_protect_mode(repo, "builtin", policy="standard", force=True)
        return repo

    def _classify(self, repo: Path, command: str):
        return evaluate_pre_tool(
            repo,
            {
                "provider": "claude",
                "session_id": "normalization",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
        )

    def test_git_global_options_cannot_bypass_forced_clean(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            commands = [
                "git -C . clean -fdx",
                "git -c core.quotePath=false clean -df",
                "git --git-dir=.git clean --force -d",
                "env FOO=1 git -C . clean -xfd",
                "bash -lc 'git clean -fdx'",
            ]
            for command in commands:
                with self.subTest(command=command):
                    result = self._classify(repo, command)
                    self.assertIsNotNone(result)
                    self.assertEqual(result["decision"], "block")
                    self.assertEqual(result["category"], "destructive-git")
                    self.assertEqual(result["rule"], "forced-clean")

    def test_global_options_are_normalized_for_other_destructive_git_subcommands(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            cases = {
                "git -C . reset --hard HEAD~1": "hard-reset",
                "git -c advice.detachedHead=false push --force-with-lease origin main": "force-push",
                "git --git-dir=.git branch -D old-branch": "force-delete-branch",
                "git -C . worktree remove --force ../old": "force-remove-worktree",
            }
            for command, rule in cases.items():
                with self.subTest(command=command):
                    result = self._classify(repo, command)
                    self.assertIsNotNone(result)
                    self.assertEqual(result["rule"], rule)

    def test_dry_run_clean_is_not_misclassified_as_forced(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            self.assertIsNone(self._classify(repo, "git -C . clean -ndx"))

    def test_protect_honors_explicit_setup_adapter_scope(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            state = repo / ".git" / "diffwitness"
            state.mkdir(parents=True)
            (state / "setup-scope.json").write_text(
                json.dumps({"schema": "diffwitness.setup-scope.v1", "adapters": ["codex"]}),
                encoding="utf-8",
            )
            with mock.patch("diffwitness.protect.shutil.which", return_value="/usr/bin/fake-agent"):
                status = set_protect_mode(repo, "builtin", policy="standard", force=True)
            self.assertEqual(list(status["adapters"]), ["codex"])
            self.assertTrue((repo / ".codex" / "hooks.json").is_file())
            self.assertFalse((repo / ".claude" / "settings.local.json").exists())


if __name__ == "__main__":
    unittest.main()
