from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.local_git_state import ensure_local_integration_excludes
from diffwitness.setup import SetupError, setup_install


class LocalGitStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "local-state@diffwitness.local")
        self.git("config", "user.name", "Local State Test")
        (self.repo / "app.py").write_text("value = 1\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-qm", "root")

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

    def test_local_excludes_are_idempotent_preserve_user_rules_and_keep_tracked_files_visible(self) -> None:
        exclude_path = Path(self.git("rev-parse", "--git-path", "info/exclude"))
        if not exclude_path.is_absolute():
            exclude_path = self.repo / exclude_path
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_path.write_text("# user rule\n*.scratch\n", encoding="utf-8")

        ensure_local_integration_excludes(self.repo)
        ensure_local_integration_excludes(self.repo)
        text = exclude_path.read_text(encoding="utf-8")
        self.assertIn("# user rule\n*.scratch", text)
        self.assertEqual(text.count("# >>> DiffWitness local integration >>>"), 1)
        self.assertEqual(text.count("# <<< DiffWitness local integration <<<"), 1)
        self.assertIn(".idleproof/", text)
        self.assertIn(".claude/settings.local.json", text)

        (self.repo / ".idleproof").mkdir()
        (self.repo / ".idleproof" / "project.json").write_text("{}\n", encoding="utf-8")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
        (self.repo / "ignored.scratch").write_text("local\n", encoding="utf-8")
        (self.repo / "visible.txt").write_text("visible\n", encoding="utf-8")
        status = self.git("status", "--porcelain", "--untracked-files=all")
        self.assertIn("visible.txt", status)
        self.assertNotIn(".idleproof", status)
        self.assertNotIn("settings.local.json", status)
        self.assertNotIn("ignored.scratch", status)

        tracked = self.repo / ".idleproof" / "tracked.json"
        tracked.write_text("{\"version\":1}\n", encoding="utf-8")
        self.git("add", "-f", ".idleproof/tracked.json")
        self.git("commit", "-qm", "track explicit idleproof fixture")
        tracked.write_text("{\"version\":2}\n", encoding="utf-8")
        status = self.git("status", "--porcelain", "--untracked-files=all")
        self.assertIn(".idleproof/tracked.json", status)

    def test_setup_install_prepares_local_excludes_before_sidecar_runs(self) -> None:
        calls: list[str] = []

        def exclude(repo: Path) -> Path:
            calls.append("exclude")
            self.assertEqual(repo, self.repo.resolve())
            return self.repo / ".git" / "info" / "exclude"

        def run_sidecar(*_args, **_kwargs):
            calls.append("sidecar")
            return subprocess.CompletedProcess(["idleproof"], 0, stdout="", stderr="")

        with (
            mock.patch("diffwitness.setup.ensure_local_integration_excludes", side_effect=exclude),
            mock.patch("diffwitness.setup._idleproof_executable", return_value="idleproof"),
            mock.patch("diffwitness.setup._run_sidecar", side_effect=run_sidecar),
            mock.patch("diffwitness.setup._status", return_value={"healthy": True}),
        ):
            result = setup_install(cwd=self.repo.resolve(), agent="all")
        self.assertTrue(result["healthy"])
        self.assertEqual(calls[:2], ["exclude", "sidecar"])

    def test_setup_install_fails_before_sidecar_if_git_metadata_cannot_be_prepared(self) -> None:
        from diffwitness.local_git_state import LocalGitStateError

        with (
            mock.patch(
                "diffwitness.setup.ensure_local_integration_excludes",
                side_effect=LocalGitStateError("read-only git metadata"),
            ),
            mock.patch("diffwitness.setup._idleproof_executable", side_effect=AssertionError("must not resolve sidecar")),
        ):
            with self.assertRaises(SetupError) as raised:
                setup_install(cwd=self.repo.resolve(), agent="all")
        self.assertIn("non-invasive local Git state", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
