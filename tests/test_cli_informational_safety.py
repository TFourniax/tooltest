from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class InformationalSafetyTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    def fixture(self, root: Path, state: str) -> Path:
        repo = root / state
        repo.mkdir()
        if state == "outside":
            return repo
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.name", "Safety Test")
        self.git(repo, "config", "user.email", "safety@example.test")
        self.git(repo, "config", "gc.auto", "0")
        self.git(repo, "config", "maintenance.auto", "false")
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        if state != "unborn":
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "baseline")
        if state in {"tests-only", "dirty", "unborn"}:
            (repo / "tests").mkdir()
            (repo / "tests/test_marker.py").write_text(
                "from pathlib import Path\nimport unittest\n"
                f"Path({str(root / 'executed')!r}).write_text('executed')\n"
                "class T(unittest.TestCase):\n"
                "    def test_ok(self): self.assertTrue(True)\n", encoding="utf-8",
            )
        if state == "dirty":
            (repo / "module.py").write_text("x = 1\n", encoding="utf-8")
        metadata = repo / ".git/diffwitness"
        metadata.mkdir()
        (metadata / "latest-gate-certificate.json").write_text("historical evidence\n", encoding="utf-8")
        return repo

    @staticmethod
    def inventory(repo: Path) -> dict[str, str]:
        return {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in repo.rglob("*") if p.is_file()}

    def invoke(self, repo: Path, args: list[str], module: str = "diffwitness.entry"):
        return subprocess.run(
            [sys.executable, "-c", f"from {module} import main; raise SystemExit(main())", *args],
            cwd=repo, text=True, capture_output=True, timeout=30,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                 "GITHUB_ACTIONS": "false"},
        )

    def test_help_and_version_preserve_repository_and_historical_evidence(self):
        for state in ("outside", "clean", "tests-only", "dirty", "unborn"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                repo = self.fixture(root, state)
                for args in (["--help"], ["--version"], ["gate", "--help"],
                             ["prove", "--help"], ["gate", "-h"], ["prove", "-h"],
                             ["gate", "--config", "absent.toml", "--help"],
                             ["prove", "--config", "absent.toml", "--help"]):
                    with self.subTest(args=args):
                        before = self.inventory(repo)
                        result = self.invoke(repo, args)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        expected = "diffwitness" if len(args) == 1 else "usage"
                        self.assertIn(expected, result.stdout.lower())
                        self.assertFalse((root / "executed").exists(), result.stdout)
                        self.assertEqual(self.inventory(repo), before)

    def test_invalid_options_fail_before_execution_or_certificate_deletion(self):
        for verb in ("gate", "prove"):
            for options in (["--unknown"], ["--timeout", "invalid"], ["--test"], ["--", "--help"]):
                with self.subTest(verb=verb, options=options), tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    repo = self.fixture(root, "tests-only")
                    before = self.inventory(repo)
                    result = self.invoke(repo, [verb, "--base", "HEAD", *options])
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertFalse((root / "executed").exists())
                    self.assertEqual(self.inventory(repo), before)

    def test_direct_frontends_also_parse_before_preflight_or_discovery(self):
        for module, verb in (("diffwitness.frontend", "gate"),
                             ("diffwitness.frontend", "prove"),
                             ("diffwitness.proof_cli", "prove")):
            with self.subTest(module=module, verb=verb), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                repo = self.fixture(root, "tests-only")
                before = self.inventory(repo)
                result = self.invoke(repo, [verb, "--help"], module)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage", result.stdout.lower())
                self.assertFalse((root / "executed").exists())
                self.assertEqual(self.inventory(repo), before)

    def test_help_inside_explicit_test_command_still_executes(self):
        for verb in ("gate", "prove"):
            with self.subTest(verb=verb), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                repo = self.fixture(root, "tests-only")
                certificate = root / "proof.json"
                command = f'"{sys.executable}" -m unittest discover -s tests -q --help'
                # The help belongs to the evidence process, not to DiffWitness.
                result = self.invoke(repo, [verb, "--base", "HEAD", "--candidate", "WORKTREE",
                    "--test", command, "--stability-runs", "1", "--certificate", str(certificate)])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("validation-only", result.stdout)
                self.assertTrue(certificate.is_file())

    def test_explicit_proof_still_executes_repository_tests(self):
        for verb in ("gate", "prove"):
            with self.subTest(verb=verb), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                repo = self.fixture(root, "tests-only")
                result = self.invoke(repo, [verb, "--base", "HEAD", "--candidate", "WORKTREE",
                    "--test", f'"{sys.executable}" -m unittest discover -s tests -q',
                    "--stability-runs", "1", "--certificate", str(root / "proof.json")])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((root / "executed").is_file())
                self.assertTrue((root / "proof.json").is_file())


if __name__ == "__main__":
    unittest.main()
