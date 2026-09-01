from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.idleproof_entry import build_portal_snapshot


class IdleProofProtectProjectionTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
        return repo

    def test_snapshot_projects_only_bounded_aggregate_protection(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            status = {
                "mode": "builtin",
                "policy": "standard",
                "health": "ready",
                "receipts": {
                    "count": 4,
                    "integrity": True,
                    "decisions": {"block": 2, "observed": 2},
                    "categories": {"destructive-git": 1},
                },
            }
            with mock.patch("diffwitness.protect.protect_status", return_value=status):
                snapshot = build_portal_snapshot(repo)
            self.assertEqual(snapshot["protection"]["blocked"], 2)
            self.assertEqual(snapshot["protection"]["observed"], 2)
            self.assertEqual(snapshot["protection"]["asked"], 0)
            self.assertFalse(snapshot["privacy"]["rawCommandsIncluded"])
            rendered = json.dumps(snapshot)
            self.assertNotIn("categories", rendered)
            self.assertNotIn("destructive-git", rendered)
            self.assertNotIn("tool", snapshot["protection"])

    def test_snapshot_omits_invalid_local_protection_projection(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            status = {
                "mode": "builtin",
                "policy": "standard",
                "health": "ready",
                "receipts": {
                    "count": 1,
                    "integrity": True,
                    "decisions": {"block": 1, "observed": 1},
                },
            }
            with mock.patch("diffwitness.protect.protect_status", return_value=status):
                snapshot = build_portal_snapshot(repo)
            self.assertNotIn("protection", snapshot)
            self.assertFalse(snapshot["privacy"]["rawCommandsIncluded"])


if __name__ == "__main__":
    unittest.main()
