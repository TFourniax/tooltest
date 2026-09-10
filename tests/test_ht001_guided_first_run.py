from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.entry import main
from diffwitness.view_mode import set_view_mode


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


@contextlib.contextmanager
def _cwd(path: Path):
    before = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


def _run(argv: list[str]) -> str:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = main(argv)
    if rc != 0:
        raise AssertionError(f"dw returned {rc}")
    return output.getvalue()


def _nonblank_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


class GuidedFirstRunDensityTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="dw-ht001-"))
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "ht001@example.invalid")
        _git(root, "config", "user.name", "HT-001")
        (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-q", "-m", "initial")
        return root

    def test_default_guided_root_help_is_a_bounded_onboarding_surface(self) -> None:
        repo = self.make_repo()
        with _cwd(repo):
            first_run = _run([])
            explicit_help = _run(["--help"])

        # The default and explicit Guided root help are the same onboarding surface: enough to
        # start safely, not a second technical manual. Command-specific and Technical help retain
        # the complete surface.
        self.assertEqual(first_run, explicit_help)
        self.assertIn("Guided view", first_run)
        self.assertIn("dw setup", first_run)
        self.assertIn("dw status", first_run)
        self.assertIn("dw explain", first_run)
        self.assertIn("dw protect", first_run)
        self.assertIn("dw view technical", first_run)
        self.assertIn("not proof", first_run.lower())
        self.assertIn("stay local", first_run.lower())
        self.assertLessEqual(len(_nonblank_lines(first_run)), 18)

        # These are useful capabilities, but listing their workflows/provider plumbing on first
        # contact is exactly the HT-001 density defect. They remain available in Technical help.
        self.assertNotIn("dw guard --", first_run)
        self.assertNotIn("dw plan", first_run)
        self.assertNotIn("dw repay", first_run)
        self.assertNotIn("OpenRouter", first_run)
        self.assertNotIn("Current Codex requires", first_run)

    def test_french_guided_root_help_has_the_same_bounded_information_shape(self) -> None:
        repo = self.make_repo()
        with _cwd(repo):
            guided = _run(["--language", "fr", "--help"])

        self.assertIn("Vue guidée", guided)
        self.assertIn("dw setup", guided)
        self.assertIn("dw status", guided)
        self.assertIn("dw explain", guided)
        self.assertIn("dw protect", guided)
        self.assertIn("dw view technical", guided)
        self.assertIn("ne prouve pas", guided.lower())
        self.assertIn("restent locaux", guided.lower())
        self.assertLessEqual(len(_nonblank_lines(guided)), 18)
        self.assertNotIn("dw guard --", guided)
        self.assertNotIn("dw plan", guided)
        self.assertNotIn("dw repay", guided)
        self.assertNotIn("OpenRouter", guided)

    def test_technical_help_keeps_the_complete_engineering_surface(self) -> None:
        repo = self.make_repo()
        set_view_mode(repo, "technical")
        with _cwd(repo):
            technical = _run([])

        self.assertIn("Core workflow", technical)
        self.assertIn("dw prove", technical)
        self.assertIn("dw guard", technical)
        self.assertIn("dw plan", technical)
        self.assertIn("dw repay", technical)
        self.assertIn("openrouter", technical.lower())
        self.assertIn("Project continuity", technical)
        self.assertGreater(len(_nonblank_lines(technical)), 18)


if __name__ == "__main__":
    unittest.main()
