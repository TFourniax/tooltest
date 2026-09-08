from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.runtime_executable import ExecutableResolutionError, resolve_dw_command, resolve_idleproof_command
from diffwitness.protect import set_protect_mode


class RuntimeExecutableTests(unittest.TestCase):
    def executable(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_explicit_launcher_wins_over_other_installation_on_path(self):
        with tempfile.TemporaryDirectory() as td:
            a = self.executable(Path(td) / "A space" / ("dw.exe" if os.name == "nt" else "dw"))
            b = self.executable(Path(td) / "B" / a.name)
            with mock.patch.dict(os.environ, {"PATH": str(b.parent)}, clear=True), mock.patch.object(sys, "argv", [str(a)]):
                self.assertEqual(resolve_dw_command(), str(a.resolve()))

    def test_windows_console_launcher_recovers_stripped_exe_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            a = self.executable(Path(td) / "Scripts" / "dw.exe")
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "argv", [str(a.with_suffix(""))]), mock.patch("diffwitness.runtime_executable._WINDOWS", True):
                self.assertEqual(resolve_dw_command(), str(a.resolve()))

    def test_frozen_binary_uses_bootloader_not_argv_or_extraction_dir(self):
        with tempfile.TemporaryDirectory() as td:
            a = self.executable(Path(td) / "portable" / "renamed-dw")
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(a)), mock.patch.object(sys, "argv", ["/temporary/_MEI/dw_entry.py"]):
                self.assertEqual(resolve_dw_command(), str(a.resolve()))

    def test_explicit_override_is_resolved_once_and_not_treated_as_shell_text(self):
        with tempfile.TemporaryDirectory() as td:
            b = self.executable(Path(td) / "B space" / ("dw.exe" if os.name == "nt" else "dw"))
            with mock.patch.dict(os.environ, {"DIFFWITNESS_BIN": str(b)}, clear=True):
                self.assertEqual(resolve_dw_command(), str(b.resolve()))
            with mock.patch.dict(os.environ, {"DIFFWITNESS_BIN": str(b) + " --version"}, clear=True):
                with self.assertRaises(ExecutableResolutionError):
                    resolve_dw_command()

    def test_unknown_programmatic_entry_cannot_fall_back_to_path(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "argv", ["dw"]), mock.patch("diffwitness.runtime_executable._distribution_entrypoint", return_value=None), mock.patch("diffwitness.runtime_executable.shutil.which", side_effect=AssertionError("implicit PATH lookup")):
            with self.assertRaisesRegex(ExecutableResolutionError, "DIFFWITNESS_BIN"):
                resolve_dw_command()

    @unittest.skipIf(os.name == "nt", "POSIX pipx symlink contract")
    def test_symlink_freezes_the_actual_installation(self):
        with tempfile.TemporaryDirectory() as td:
            real = self.executable(Path(td) / "venv" / "bin" / "dw")
            link = Path(td) / "dw"
            link.symlink_to(real)
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "argv", [str(link)]):
                self.assertEqual(resolve_dw_command(), str(real.resolve()))

    def test_metadata_for_another_loaded_distribution_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            dist = mock.Mock()
            dist.locate_file.return_value = Path(td) / "another" / "diffwitness" / "__init__.py"
            dist.read_text.return_value = None
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "argv", ["__main__.py"]), mock.patch("importlib.metadata.distribution", return_value=dist), mock.patch("diffwitness.runtime_executable.shutil.which", side_effect=AssertionError("implicit PATH lookup")):
                with self.assertRaises(ExecutableResolutionError):
                    resolve_dw_command()

    def test_frozen_setup_requires_explicit_sidecar_instead_of_path(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "frozen", True, create=True), mock.patch("diffwitness.runtime_executable.shutil.which", side_effect=AssertionError("implicit PATH lookup")):
            with self.assertRaisesRegex(ExecutableResolutionError, "DIFFWITNESS_IDLEPROOF_BIN"):
                resolve_idleproof_command()

    def test_missing_override_does_not_remove_existing_hooks(self):
        with tempfile.TemporaryDirectory() as td:
            import subprocess
            repo = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / ".codex").mkdir()
            set_protect_mode(repo, "builtin", force=True)
            hooks = repo / ".codex" / "hooks.json"
            before = hooks.read_bytes()
            with mock.patch.dict(os.environ, {"DIFFWITNESS_BIN": str(repo / "missing-dw")}):
                with self.assertRaises(ExecutableResolutionError):
                    set_protect_mode(repo, "builtin", force=True)
                self.assertEqual(hooks.read_bytes(), before)
                # Cleanup uses the recorded owner even if the current override is broken.
                set_protect_mode(repo, "off")
            self.assertFalse(hooks.exists())


if __name__ == "__main__":
    unittest.main()
