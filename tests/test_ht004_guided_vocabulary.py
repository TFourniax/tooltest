from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.setup import _guided_setup_error


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
        env=env,
    )


def _entrypoint(name: str) -> str | None:
    suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).parent / f"{name}{suffix}"
    if sibling.is_file():
        return str(sibling)
    return shutil.which(name)


def _dw(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    scripts = str(Path(sys.executable).parent)
    env["PATH"] = scripts + os.pathsep + env.get("PATH", "")
    dw = _entrypoint("dw")
    if dw:
        env["DIFFWITNESS_BIN"] = dw
    return _run([sys.executable, "-m", "diffwitness.entry", *args], cwd=repo, env=env)


class HT004GuidedVocabularyTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        init = _run(["git", "init", "-q"], cwd=repo)
        self.assertEqual(init.returncode, 0, init.stderr)
        return repo

    def test_guided_setup_hides_internal_sidecar_term_without_changing_machine_or_technical_detail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))

            guided = _dw(repo, "view", "guided")
            self.assertEqual(guided.returncode, 0, guided.stderr)

            # sys.executable is deliberately a valid executable but not an IdleProof command.
            # This reaches the real subprocess boundary and deterministically exercises the
            # integration-rejected error path without inventing a mock-only product state.
            human = _dw(
                repo,
                "setup",
                "--agent",
                "codex",
                "--idleproof-command",
                sys.executable,
            )
            self.assertEqual(human.returncode, 2)
            self.assertNotIn("sidecar", human.stderr.lower())
            self.assertIn("DiffWitness", human.stderr)

            french = _dw(
                repo,
                "--language",
                "fr",
                "setup",
                "--agent",
                "codex",
                "--idleproof-command",
                sys.executable,
            )
            self.assertEqual(french.returncode, 2)
            self.assertNotIn("sidecar", french.stderr.lower())
            self.assertIn("intégration DiffWitness", french.stderr)

            machine = _dw(
                repo,
                "setup",
                "--agent",
                "codex",
                "--idleproof-command",
                sys.executable,
                "--json",
            )
            self.assertEqual(machine.returncode, 2)
            payload = json.loads(machine.stdout)
            self.assertEqual(payload["schema"], "diffwitness.setup-error.v1")
            # HT-004 is presentation-only: retain the established diagnostic in the
            # machine contract instead of silently rewriting JSON facts/messages.
            self.assertIn("sidecar", payload["error"].lower())

            technical = _dw(repo, "view", "technical")
            self.assertEqual(technical.returncode, 0, technical.stderr)
            technical_error = _dw(
                repo,
                "setup",
                "--agent",
                "codex",
                "--idleproof-command",
                sys.executable,
            )
            self.assertEqual(technical_error.returncode, 2)
            self.assertIn("sidecar", technical_error.stderr.lower())

    def test_every_diffwitness_owned_sidecar_diagnostic_has_a_guided_rendering(self) -> None:
        raw_messages = (
            "DiffWitness sidecar command failed to start: executable missing",
            "DiffWitness sidecar rejected the operation: exit 2",
            "DiffWitness sidecar returned an invalid status payload: nope",
            "DiffWitness sidecar is incompatible with this release (unexpected integration status schema).",
            "This DiffWitness installation has no bundled understanding sidecar. Install the matching bundle.",
        )
        for raw in raw_messages:
            with self.subTest(raw=raw):
                rendered = _guided_setup_error(raw)
                self.assertNotIn("sidecar", rendered.lower())
                self.assertNotEqual(rendered, raw)

    def test_idleproof_help_does_not_expose_internal_sidecar_architecture(self) -> None:
        idleproof = _entrypoint("idleproof")
        self.assertIsNotNone(idleproof, "installed package must expose the idleproof entrypoint")
        proc = _run([str(idleproof), "--help"], cwd=Path.cwd())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("sidecar", proc.stdout.lower())
        self.assertIn("IdleProof", proc.stdout)


if __name__ == "__main__":
    unittest.main()
