from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.entry import main
from diffwitness.view_mode import DEFAULT_VIEW_MODE, get_view_mode, set_view_mode, view_cli


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


@contextlib.contextmanager
def _cwd(path: Path):
    before = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


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

    def test_defaults_to_guided_for_first_run(self) -> None:
        repo = self.make_repo()
        self.assertEqual(DEFAULT_VIEW_MODE, "guided")
        self.assertEqual(get_view_mode(repo), "guided")

    def test_switch_persists_inside_git_metadata_without_dirtying_repository(self) -> None:
        repo = self.make_repo()
        head_before = _git(repo, "rev-parse", "HEAD")
        status_before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(set_view_mode(repo, "technical"), "technical")
        self.assertEqual(get_view_mode(repo), "technical")
        self.assertTrue((repo / ".git" / "diffwitness" / "ui-preferences.json").exists())
        self.assertEqual(_git(repo, "rev-parse", "HEAD"), head_before)
        self.assertEqual(_git(repo, "status", "--porcelain=v1", "--untracked-files=all"), status_before)
        self.assertEqual(set_view_mode(repo, "guided"), "guided")
        self.assertEqual(get_view_mode(repo), "guided")

    def test_cli_can_switch_both_directions_and_report_machine_state(self) -> None:
        repo = self.make_repo()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(view_cli(["technical", "--repo", str(repo)]), 0)
        self.assertIn("technical", output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(view_cli(["guided", "--repo", str(repo), "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["view"], "guided")

    def test_root_help_is_guided_first_but_technical_is_one_command_away(self) -> None:
        repo = self.make_repo()
        with _cwd(repo):
            guided = io.StringIO()
            with contextlib.redirect_stdout(guided):
                self.assertEqual(main([]), 0)
            self.assertIn("Guided view", guided.getvalue())
            self.assertIn("dw status", guided.getvalue())
            self.assertIn("dw view technical", guided.getvalue())
            self.assertNotIn("dw prove [options]", guided.getvalue())

            set_view_mode(repo, "technical")
            technical = io.StringIO()
            with contextlib.redirect_stdout(technical):
                self.assertEqual(main([]), 0)
            self.assertIn("Core workflow", technical.getvalue())
            self.assertIn("dw prove", technical.getvalue())

    def test_invalid_stored_preference_fails_soft_to_guided(self) -> None:
        repo = self.make_repo()
        path = repo / ".git" / "diffwitness" / "ui-preferences.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json", encoding="utf-8")
        self.assertEqual(get_view_mode(repo), "guided")


if __name__ == "__main__":
    unittest.main()
