from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import diffwitness.entry
from diffwitness.entry import main


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


class PublicFrontendTests(unittest.TestCase):
    def test_entry_resolves_to_v03_package_frontend(self) -> None:
        location = Path(diffwitness.entry.__file__ or "")
        self.assertEqual(location.name, "__init__.py")
        self.assertEqual(location.parent.name, "entry")

    def test_preservation_certificate_is_integrity_and_tree_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            git("init", "-q", cwd=repo)
            git("config", "user.email", "frontend@example.com", cwd=repo)
            git("config", "user.name", "Frontend Test", cwd=repo)
            (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            tests = repo / "tests"
            tests.mkdir()
            (tests / "test_calc.py").write_text(
                "import unittest\nfrom calc import add\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = git("rev-parse", "HEAD", cwd=repo)

            (repo / "calc.py").write_text(
                "def add(a, b):\n    return sum((a, b))\n", encoding="utf-8"
            )
            certificate = root / "assurance.json"
            test_command = f'"{sys.executable}" -m unittest discover -s tests -q'
            self.assertEqual(
                main(
                    [
                        "gate",
                        "--repo",
                        str(repo),
                        "--base",
                        base,
                        "--candidate",
                        "WORKTREE",
                        "--test",
                        test_command,
                        "--policy",
                        "balanced",
                        "--stability-runs",
                        "1",
                        "--certificate",
                        str(certificate),
                        "--no-github-actions",
                    ]
                ),
                0,
            )
            payload = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertEqual(payload["classification"], "preservation-evidence")
            self.assertTrue(payload["certificate_id"].startswith("dwa1_"))
            self.assertTrue(payload["base"].get("tree"))
            self.assertTrue(payload["candidate"].get("tree"))
            self.assertEqual(
                main(["verify", str(certificate), "--repo", str(repo)]),
                0,
            )


if __name__ == "__main__":
    unittest.main()
