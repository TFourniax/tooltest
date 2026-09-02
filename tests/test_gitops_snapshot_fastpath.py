from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.gitops import diff_text, snapshot_worktree


class SnapshotFastPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "snapshot-fastpath@example.test")
        self.git("config", "user.name", "Snapshot Fastpath")
        (self.repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-qm", "base")
        self.head = self.git("rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return proc.stdout.strip()

    def test_clean_worktree_reuses_head_exactly(self) -> None:
        self.assertEqual(snapshot_worktree(self.repo), self.head)

    def test_only_known_untracked_runtime_artifacts_still_reuse_head(self) -> None:
        cache = self.repo / "__pycache__"
        cache.mkdir()
        (cache / "app.cpython-313.pyc").write_bytes(b"runtime-cache")
        hooks = self.repo / ".claude"
        hooks.mkdir()
        (hooks / "settings.local.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(snapshot_worktree(self.repo), self.head)

    def test_meaningful_untracked_file_forces_exact_snapshot(self) -> None:
        (self.repo / "notes.txt").write_text("meaningful\n", encoding="utf-8")
        candidate = snapshot_worktree(self.repo)
        self.assertNotEqual(candidate, self.head)
        self.assertIn("notes.txt", diff_text(self.repo, self.head, candidate))

    def test_tracked_worktree_change_forces_exact_snapshot(self) -> None:
        (self.repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        candidate = snapshot_worktree(self.repo)
        self.assertNotEqual(candidate, self.head)
        self.assertEqual(self.git("show", f"{candidate}:app.py"), "VALUE = 2")

    def test_staged_change_is_not_mistaken_for_clean_state(self) -> None:
        (self.repo / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
        self.git("add", "app.py")
        candidate = snapshot_worktree(self.repo)
        self.assertNotEqual(candidate, self.head)
        self.assertEqual(self.git("show", f"{candidate}:app.py"), "VALUE = 3")

    def test_tracked_cache_like_file_is_never_filtered(self) -> None:
        cache = self.repo / "__pycache__"
        cache.mkdir()
        tracked = cache / "tracked.pyc"
        tracked.write_bytes(b"v1")
        self.git("add", "-f", "__pycache__/tracked.pyc")
        self.git("commit", "-qm", "track cache-like fixture")
        head = self.git("rev-parse", "HEAD")
        tracked.write_bytes(b"v2")
        candidate = snapshot_worktree(self.repo)
        self.assertNotEqual(candidate, head)


if __name__ == "__main__":
    unittest.main()
