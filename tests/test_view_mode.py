from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.view_mode import DEFAULT_VIEW_MODE, get_view_mode, set_view_mode, view_cli


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


class ViewModeTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="dw-view-"))
        _git(root, "init")
        _git(root, "config", "user.email", "view@example.invalid")
        _git(root, "config", "user.name", "View Tests")
        (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "initial")
        return root

    def test_defaults_to_technical_for_existing_diffwitness_users(self) -> None:
        repo = self.make_repo()
        self.assertEqual(DEFAULT_VIEW_MODE, "technical")
        self.assertEqual(get_view_mode(repo), "technical")

    def test_switch_persists_inside_git_metadata_without_dirtying_repository(self) -> None:
        repo = self.make_repo()
        head_before = _git(repo, "rev-parse", "HEAD")
        status_before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(set_view_mode(repo, "guided"), "guided")
        self.assertEqual(get_view_mode(repo), "guided")
        self.assertTrue((repo / ".git" / "diffwitness" / "ui-preferences.json").exists())
        self.assertEqual(_git(repo, "rev-parse", "HEAD"), head_before)
        self.assertEqual(_git(repo, "status", "--porcelain=v1", "--untracked-files=all"), status_before)
        self.assertEqual(set_view_mode(repo, "technical"), "technical")
        self.assertEqual(get_view_mode(repo), "technical")

    def test_cli_can_switch_both_directions_and_report_machine_state(self) -> None:
        repo = self.make_repo()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(view_cli(["guided", "--repo", str(repo)]), 0)
        self.assertIn("guided", output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(view_cli(["technical", "--repo", str(repo), "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["view"], "technical")

    def test_invalid_stored_preference_fails_soft_to_technical(self) -> None:
        repo = self.make_repo()
        path = repo / ".git" / "diffwitness" / "ui-preferences.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json", encoding="utf-8")
        self.assertEqual(get_view_mode(repo), "technical")


if __name__ == "__main__":
    unittest.main()
