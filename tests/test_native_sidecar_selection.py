"""Regression: npm IdleProof selected explicitly must own setup/status/readiness.

This test does not run Node or authenticate Codex; the actual provider hook needs a
separate HUMAN acceptance test. It verifies that the local diagnostic cannot switch
back to a different bundled shim when both share the same version number.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.native_activation import record_native_activation
from diffwitness.readiness import native_readiness
from diffwitness.setup import (
    SetupError,
    _persist_setup_scope,
    _selected_sidecar,
    setup_install,
    setup_status,
    setup_uninstall,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


class ExplicitSidecarSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="dw-sidecar-test-")
        self.root = Path(self.tmp.name)
        self.repo = self.root / "project"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        self.binary = self.root / "node-packages" / "bin" / "idleproof.mjs"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.binary.chmod(0o755)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_installer_preserves_explicit_node_sidecar_for_status_and_uninstall(self) -> None:
        selected = str(self.binary.resolve())
        response = {
            "schema": "diffwitness.integration-status.v1",
            "healthy": True,
            "configured": True,
            "expectedAdapters": ["codex"],
            "adapters": {"codex": True},
            "diffWitness": {"ok": True, "command": str(self.root / "qualified-dw")},
        }
        invoked = []

        def fake_run(command, args, **kwargs):
            invoked.append((command, tuple(args)))
            return subprocess.CompletedProcess([command, *args], 0, "", "")

        def fake_status(command, cwd):
            self.assertEqual(command, selected)
            self.assertEqual(cwd, self.repo)
            return response

        with (
            mock.patch("diffwitness.setup._dw_command", return_value=str(self.root / "qualified-dw")),
            mock.patch("diffwitness.setup._run_sidecar", side_effect=fake_run),
            mock.patch("diffwitness.setup._status", side_effect=fake_status),
        ):
            installed = setup_install(cwd=self.repo, agent="codex", idleproof_command=selected)
            self.assertTrue(installed["healthy"])
            # No --idleproof-command on the second invocation: still query the selected npm runtime.
            viewed = setup_status(cwd=self.repo)
            self.assertEqual(viewed["sidecar"], selected)
            scope = json.loads((self.repo / ".git/diffwitness/setup-scope.json").read_text())
            self.assertEqual(scope["idleproofCommand"], selected)
            removed = setup_uninstall(cwd=self.repo)
            self.assertEqual(removed["sidecar"], selected)
            self.assertFalse((self.repo / ".git/diffwitness/setup-scope.json").exists())
        self.assertEqual([x[0] for x in invoked], [selected, selected])
        self.assertIn("install", invoked[0][1])
        self.assertIn("uninstall", invoked[1][1])

    def test_broken_recorded_runtime_fails_closed_instead_of_falling_back(self) -> None:
        _persist_setup_scope(self.repo, ["codex"], sidecar=str(self.binary))
        self.binary.unlink()
        with self.assertRaises(SetupError):
            _selected_sidecar(self.repo, None)
        # An explicit replacement is allowed only if its executable exists.
        replacement = self.root / "replacement"
        replacement.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        replacement.chmod(0o755)
        self.assertEqual(_selected_sidecar(self.repo, str(replacement)), str(replacement.resolve()))

    def test_native_readiness_requires_real_npm_hook_files_and_a_live_observation(self) -> None:
        # A real npm install selects bin/idleproof.mjs and puts a sibling runner in the same package.
        runner = self.binary.with_name("idleproof-hook.mjs")
        runner.write_text("/* hook runner */\n", encoding="utf-8")
        node = self.root / "node"
        node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        node.chmod(0o755)
        dw = self.root / "qualified-dw"
        dw.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        dw.chmod(0o755)

        _persist_setup_scope(self.repo, ["codex"], sidecar=str(self.binary.resolve()))
        identity = self.repo / ".idleproof"
        identity.mkdir()
        (identity / "diffwitness.json").write_text(json.dumps({
            "schema": "diffwitness.integration-config.v1",
            "requireDiffWitness": True,
            "adapters": ["codex"],
            "diffWitnessCommand": str(dw),
        }), encoding="utf-8")
        hook_dir = self.repo / ".codex"
        hook_dir.mkdir()
        command = f'"{node}" "{runner}" codex'
        events = {
            event: [{"hooks": [{"type": "command", "command": command, "timeout": 8}]}]
            for event in ("SessionStart", "UserPromptSubmit", "Stop")
        }
        hook_file = hook_dir / "hooks.json"
        hook_file.write_text(json.dumps({"hooks": events}), encoding="utf-8")

        before = native_readiness(self.repo)
        self.assertTrue(before["installed"], before)
        self.assertFalse(before["runtimeUsable"], "An installed hook without a live invocation is not ready")
        record_native_activation(self.repo, "codex")
        after = native_readiness(self.repo)
        self.assertTrue(after["runtimeUsable"], after)
        self.assertTrue(after["fullyObserved"])
        self.assertEqual(after["adapters"]["codex"]["providerTrust"], "unknown")

        events.pop("Stop")
        hook_file.write_text(json.dumps({"hooks": events}), encoding="utf-8")
        missing = native_readiness(self.repo)
        self.assertFalse(missing["installed"])
        self.assertFalse(missing["runtimeUsable"], "A missing Stop cannot pass on an old activation marker")

        # A different installed Core must not satisfy the selected npm project's readiness.
        events["Stop"] = [{"hooks": [{"type": "command", "command": command}]}]
        hook_file.write_text(json.dumps({"hooks": events}), encoding="utf-8")
        dw.unlink()
        absent = native_readiness(self.repo)
        self.assertFalse(absent["executableAvailable"])
        self.assertFalse(absent["runtimeUsable"])


if __name__ == "__main__":
    unittest.main()
