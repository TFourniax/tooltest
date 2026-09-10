from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
        env=os.environ.copy(),
    )


def _git(repo: Path, *args: str) -> str:
    proc = _run(["git", *args], cwd=repo)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def _entrypoint(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).parent / f"{name}{suffix}"
    if sibling.is_file():
        return str(sibling.resolve())
    value = shutil.which(name)
    if not value:
        raise AssertionError(f"installed-product qualification requires {name}")
    return str(Path(value).resolve())


class HT007ProviderScopeQualificationTests(unittest.TestCase):
    def test_explicit_codex_setup_bounds_protect_scope_when_claude_is_detectable(self) -> None:
        """Public setup scope must win over broader provider auto-detection in Protect."""
        dw = _entrypoint("dw")
        idleproof = _entrypoint("idleproof")

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "ht007@example.test")
            _git(repo, "config", "user.name", "HT-007 Qualification")
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            _git(repo, "add", "app.py")
            _git(repo, "commit", "-qm", "baseline")

            # Make Claude independently detectable before setup. Historically, Protect's
            # broader auto-detection saw this alongside the Codex integration and expanded
            # an explicit Codex-only setup into Claude + Codex.
            claude_dir = repo / ".claude"
            claude_dir.mkdir()
            sentinel = claude_dir / "existing-provider-marker.txt"
            sentinel_bytes = b"claude-environment-must-remain-untouched\n"
            sentinel.write_bytes(sentinel_bytes)
            claude_settings = claude_dir / "settings.local.json"
            self.assertFalse(claude_settings.exists())

            setup = _run(
                [
                    dw,
                    "setup",
                    "--agent",
                    "codex",
                    "--idleproof-command",
                    idleproof,
                    "--json",
                ],
                cwd=repo,
            )
            self.assertEqual(setup.returncode, 0, setup.stderr)
            setup_payload = json.loads(setup.stdout)
            self.assertTrue(setup_payload["healthy"])
            self.assertEqual(setup_payload["expectedAdapters"], ["codex"])
            self.assertTrue((repo / ".codex" / "hooks.json").is_file())
            self.assertFalse(claude_settings.exists())
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

            scope_raw = _git(repo, "rev-parse", "--git-path", "diffwitness/setup-scope.json")
            scope_path = Path(scope_raw)
            if not scope_path.is_absolute():
                scope_path = repo / scope_path
            scope = json.loads(scope_path.read_text(encoding="utf-8"))
            self.assertEqual(scope["schema"], "diffwitness.setup-scope.v1")
            self.assertEqual(scope["adapters"], ["codex"])

            enabled = _run(
                [dw, "protect", "enable", "--policy", "standard", "--json"],
                cwd=repo,
            )
            self.assertEqual(enabled.returncode, 0, enabled.stderr)
            protect_payload = json.loads(enabled.stdout)
            self.assertEqual(protect_payload["mode"], "builtin")
            self.assertEqual(set(protect_payload["adapters"]), {"codex"})
            self.assertTrue(protect_payload["adapters"]["codex"]["installed"])
            self.assertEqual(
                protect_payload["adapters"]["codex"]["activation"],
                "awaiting-first-observation",
            )
            self.assertFalse(claude_settings.exists())
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

            protect_status = _run([dw, "protect", "status", "--json"], cwd=repo)
            self.assertEqual(protect_status.returncode, 0, protect_status.stderr)
            protect_status_payload = json.loads(protect_status.stdout)
            self.assertEqual(set(protect_status_payload["adapters"]), {"codex"})

            setup_status = _run(
                [
                    dw,
                    "setup",
                    "status",
                    "--idleproof-command",
                    idleproof,
                    "--json",
                ],
                cwd=repo,
            )
            self.assertEqual(setup_status.returncode, 0, setup_status.stderr)
            setup_status_payload = json.loads(setup_status.stdout)
            self.assertEqual(setup_status_payload["expectedAdapters"], ["codex"])
            self.assertEqual(set(setup_status_payload["protect"]["adapters"]), {"codex"})
            self.assertFalse(claude_settings.exists())
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

            disabled = _run([dw, "protect", "disable", "--json"], cwd=repo)
            self.assertEqual(disabled.returncode, 0, disabled.stderr)
            self.assertFalse(claude_settings.exists())
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

            # Native Codex setup remains owned by setup; disabling optional Protect must not
            # remove the independently installed native integration.
            codex_rendered = (repo / ".codex" / "hooks.json").read_text(encoding="utf-8")
            self.assertIn("ide-hook", codex_rendered)
            self.assertNotIn("protect-pre", codex_rendered)
            self.assertNotIn("protect-post", codex_rendered)


if __name__ == "__main__":
    unittest.main()
