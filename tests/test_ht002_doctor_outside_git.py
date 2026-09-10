from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from diffwitness.entry import main


class DoctorOutsideGitActionabilityTests(unittest.TestCase):
    def invoke(self, root: Path, language: str, view: str = "guided") -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = main([
                "--language",
                language,
                "doctor",
                "--repo",
                str(root),
                "--view",
                view,
            ])
        return rc, out.getvalue()

    def test_guided_english_explains_how_to_reach_a_valid_doctor_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dw-ht002-") as td:
            root = Path(td).resolve()
            before = sorted(root.iterdir())
            rc, text = self.invoke(root, "en")
            after = sorted(root.iterdir())

        self.assertEqual(rc, 2, text)
        self.assertEqual(before, after)
        self.assertIn("not a Git repository", text)
        self.assertIn("Run `dw doctor` inside a Git repository", text)
        self.assertIn("`git init`", text)
        self.assertNotIn("ready", text.lower())
        self.assertNotIn("verified", text.lower())

    def test_guided_french_has_the_same_actionable_failure_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dw-ht002-") as td:
            root = Path(td).resolve()
            rc, text = self.invoke(root, "fr")

        self.assertEqual(rc, 2, text)
        self.assertIn("not a Git repository", text)
        self.assertIn("Exécutez `dw doctor` dans un dépôt Git", text)
        self.assertIn("`git init`", text)
        self.assertNotIn("prêt", text.lower())
        self.assertNotIn("verified", text.lower())

    def test_technical_outside_git_still_fails_without_inventing_readiness(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dw-ht002-") as td:
            root = Path(td).resolve()
            rc, text = self.invoke(root, "en", view="technical")

        self.assertEqual(rc, 2, text)
        self.assertIn("not a Git repository", text)
        self.assertNotIn("ready=true", text.lower())
        self.assertNotIn("verified=true", text.lower())


if __name__ == "__main__":
    unittest.main()
