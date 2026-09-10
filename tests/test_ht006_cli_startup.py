from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock


class HT006CliStartupTests(unittest.TestCase):
    def test_importing_public_entry_does_not_eagerly_load_full_frontend(self) -> None:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import diffwitness.entry; "
                    "print('loaded' if 'diffwitness.frontend' in sys.modules else 'not-loaded')"
                ),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(
            probe.stdout.strip(),
            "not-loaded",
            "the lightweight public entrypoint should not eagerly import the full proof frontend",
        )

    def test_frontend_error_public_export_remains_available_on_demand(self) -> None:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import diffwitness.entry as entry; "
                    "before='diffwitness.frontend' in sys.modules; "
                    "name=entry.FrontendError.__name__; "
                    "after='diffwitness.frontend' in sys.modules; "
                    "print(f'{before}|{name}|{after}')"
                ),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), "False|FrontendError|True")

    def test_version_fast_path_does_not_run_git(self) -> None:
        from diffwitness.entry import main

        real_run = subprocess.run
        git_calls: list[list[str]] = []

        def observed_run(command, *args, **kwargs):
            if (
                isinstance(command, (list, tuple))
                and command
                and str(command[0]).lower() in {"git", "git.exe"}
            ):
                git_calls.append([str(part) for part in command])
            return real_run(command, *args, **kwargs)

        for version_flag in ("--version", "-V"):
            with self.subTest(version_flag=version_flag):
                git_calls.clear()
                stdout = io.StringIO()
                stderr = io.StringIO()
                with mock.patch("subprocess.run", side_effect=observed_run):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        rc = main([version_flag])

                self.assertEqual(rc, 0)
                self.assertEqual(stdout.getvalue(), "diffwitness 0.4.0a1\n")
                self.assertEqual(stderr.getvalue(), "")
                self.assertEqual(
                    git_calls,
                    [],
                    f"`dw {version_flag}` should not resolve repository state or launch Git before printing a static version",
                )

    def test_version_output_contract_remains_exact(self) -> None:
        from diffwitness.entry import main

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = main(["--version"])

        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue(), "diffwitness 0.4.0a1\n")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
