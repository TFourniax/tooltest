from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.gitops import snapshot_worktree


class NestedLocalToolArtifactsTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def test_nested_idleproof_and_agent_hook_state_are_not_software_changes(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "nested@diffwitness.local")
            self.git(repo, "config", "user.name", "Nested Plumbing")
            package = repo / "packages" / "billing"
            package.mkdir(parents=True)
            (package / "app.ts").write_text("export const value = 1;\n", encoding="utf-8")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "base")
            head_tree = self.git(repo, "rev-parse", "HEAD^{tree}")

            (package / ".idleproof").mkdir()
            (package / ".idleproof" / "receipt.json").write_text("{}\n", encoding="utf-8")
            (package / ".claude").mkdir()
            (package / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
            (package / ".codex").mkdir()
            (package / ".codex" / "hooks.json").write_text("{}\n", encoding="utf-8")
            (package / ".cursor" / "rules").mkdir(parents=True)
            (package / ".cursor" / "hooks.json").write_text("{}\n", encoding="utf-8")
            (package / ".cursor" / "rules" / "idleproof-continuity.mdc").write_text("local rule\n", encoding="utf-8")

            snapshot = snapshot_worktree(repo)
            candidate_tree = self.git(repo, "rev-parse", f"{snapshot}^{{tree}}")
            self.assertEqual(
                candidate_tree,
                head_tree,
                "nested local IdleProof/agent plumbing changed the DiffWitness candidate tree",
            )


if __name__ == "__main__":
    unittest.main()
