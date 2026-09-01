from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.gitops import snapshot_worktree


class IdleProofSoulSnapshotTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def test_untracked_soul_preferences_do_not_change_candidate_tree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "soul@diffwitness.local")
            self.git(repo, "config", "user.name", "Soul Snapshot")
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "base")
            head_tree = self.git(repo, "rev-parse", "HEAD^{tree}")

            (repo / ".idleproof").mkdir()
            (repo / ".idleproof" / "soul.md").write_text("Explain like I am new to code.\n", encoding="utf-8")
            (repo / ".diffwitness").mkdir()
            (repo / ".diffwitness" / "soul.md").write_text("Be concise.\n", encoding="utf-8")

            snapshot = snapshot_worktree(repo)
            candidate_tree = self.git(repo, "rev-parse", f"{snapshot}^{{tree}}")
            self.assertEqual(candidate_tree, head_tree)

    def test_tracked_soul_remains_part_of_the_software_tree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "tracked-soul@diffwitness.local")
            self.git(repo, "config", "user.name", "Tracked Soul")
            (repo / ".diffwitness").mkdir()
            soul = repo / ".diffwitness" / "soul.md"
            soul.write_text("Be concise.\n", encoding="utf-8")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "base")
            head_tree = self.git(repo, "rev-parse", "HEAD^{tree}")

            soul.write_text("Explain every tradeoff.\n", encoding="utf-8")
            snapshot = snapshot_worktree(repo)
            candidate_tree = self.git(repo, "rev-parse", f"{snapshot}^{{tree}}")
            self.assertNotEqual(candidate_tree, head_tree)


if __name__ == "__main__":
    unittest.main()
