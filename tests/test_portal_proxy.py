from __future__ import annotations

import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from diffwitness.portal_proxy import portal_cli


class PortalProxyTests(unittest.TestCase):
    def local_state(self):
        return (
            patch("diffwitness.portal_proxy.repo_root", return_value=Path("/tmp/repo")),
            patch("diffwitness.portal_proxy.ensure_local_integration_excludes"),
        )

    def test_help_exposes_only_diffwitness_commands(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = portal_cli(["--help"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("dw portal configure", text)
        self.assertIn("--token-stdin", text)
        self.assertIn("no config/network", text)
        self.assertNotIn("idleproof portal", text)

    def test_missing_sidecar_is_actionable(self) -> None:
        err = io.StringIO()
        repo_patch, exclude_patch = self.local_state()
        with repo_patch, exclude_patch as ensure, patch("diffwitness.portal_proxy.shutil.which", return_value=None), redirect_stderr(err):
            rc = portal_cli(["status", "--json"])
        self.assertEqual(rc, 127)
        ensure.assert_called_once_with(Path("/tmp/repo"))
        self.assertIn("Reinstall the matching DiffWitness wheel", err.getvalue())

    def test_snapshot_is_local_and_does_not_require_sidecar_or_portal_config(self) -> None:
        snapshot = {
            "schema": "idleproof.portal-snapshot.v1",
            "snapshotId": "ipsnap_0123456789abcdef01234567",
            "project": {"localId": "0123456789abcdef01234567"},
            "privacy": {
                "sourceCodeIncluded": False,
                "rawDiffIncluded": False,
                "rawPromptIncluded": False,
            },
        }
        out = io.StringIO()
        repo_patch, exclude_patch = self.local_state()
        with (
            repo_patch,
            exclude_patch as ensure,
            patch("diffwitness.portal_proxy.build_portal_snapshot", return_value=snapshot) as build,
            patch("diffwitness.portal_proxy.shutil.which", side_effect=AssertionError("snapshot must not resolve sidecar")),
            redirect_stdout(out),
        ):
            rc = portal_cli(["snapshot", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), snapshot)
        ensure.assert_called_once_with(Path("/tmp/repo"))
        build.assert_called_once()

    def test_snapshot_rejects_unknown_options_without_network_or_sidecar(self) -> None:
        err = io.StringIO()
        repo_patch, exclude_patch = self.local_state()
        with (
            repo_patch,
            exclude_patch,
            patch("diffwitness.portal_proxy.shutil.which", side_effect=AssertionError("snapshot must not resolve sidecar")),
            redirect_stderr(err),
        ):
            rc = portal_cli(["snapshot", "--upload"])
        self.assertEqual(rc, 2)
        self.assertIn("unsupported option", err.getvalue())

    def test_proxy_forwards_argv_without_shell_or_token_rewriting(self) -> None:
        completed = subprocess.CompletedProcess(["idleproof"], 0)
        repo_patch, exclude_patch = self.local_state()
        with (
            repo_patch,
            exclude_patch as ensure,
            patch("diffwitness.portal_proxy.shutil.which", return_value="/usr/bin/idleproof"),
            patch("diffwitness.portal_proxy.subprocess.run", return_value=completed) as run,
        ):
            rc = portal_cli(["configure", "--endpoint", "https://portal.example.test/ingest", "--token-stdin"])
        self.assertEqual(rc, 0)
        ensure.assert_called_once_with(Path("/tmp/repo"))
        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            [
                "/usr/bin/idleproof",
                "portal",
                "configure",
                "--endpoint",
                "https://portal.example.test/ingest",
                "--token-stdin",
            ],
        )
        self.assertNotIn("shell", kwargs)
        self.assertFalse(kwargs.get("check", True))

    def test_local_git_exclude_failure_blocks_state_creating_commands(self) -> None:
        err = io.StringIO()
        repo_patch, exclude_patch = self.local_state()
        with (
            repo_patch,
            exclude_patch as ensure,
            patch("diffwitness.portal_proxy.shutil.which", side_effect=AssertionError("sidecar must not run")),
            redirect_stderr(err),
        ):
            from diffwitness.local_git_state import LocalGitStateError

            ensure.side_effect = LocalGitStateError("read-only git metadata")
            rc = portal_cli(["id", "--json"])
        self.assertEqual(rc, 2)
        self.assertIn("non-invasive local Git state", err.getvalue())

    def test_unknown_sidecar_surface_is_rejected(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            rc = portal_cli(["reset-everything"])
        self.assertEqual(rc, 2)
        self.assertIn("unsupported command", err.getvalue())


if __name__ == "__main__":
    unittest.main()
