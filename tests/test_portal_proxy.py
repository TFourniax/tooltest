from __future__ import annotations

import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from diffwitness.portal_proxy import portal_cli


class PortalProxyTests(unittest.TestCase):
    def test_help_exposes_only_diffwitness_commands(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = portal_cli(["--help"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("dw portal configure", text)
        self.assertIn("--token-stdin", text)
        self.assertNotIn("idleproof portal", text)

    def test_missing_sidecar_is_actionable(self) -> None:
        err = io.StringIO()
        with patch("diffwitness.portal_proxy.shutil.which", return_value=None), redirect_stderr(err):
            rc = portal_cli(["status", "--json"])
        self.assertEqual(rc, 127)
        self.assertIn("dw setup", err.getvalue())

    def test_proxy_forwards_argv_without_shell_or_token_rewriting(self) -> None:
        completed = subprocess.CompletedProcess(["idleproof"], 0)
        with (
            patch("diffwitness.portal_proxy.shutil.which", return_value="/usr/bin/idleproof"),
            patch("diffwitness.portal_proxy.subprocess.run", return_value=completed) as run,
        ):
            rc = portal_cli(["configure", "--endpoint", "https://portal.example.test/ingest", "--token-stdin"])
        self.assertEqual(rc, 0)
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

    def test_unknown_sidecar_surface_is_rejected(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            rc = portal_cli(["reset-everything"])
        self.assertEqual(rc, 2)
        self.assertIn("unsupported command", err.getvalue())


if __name__ == "__main__":
    unittest.main()
