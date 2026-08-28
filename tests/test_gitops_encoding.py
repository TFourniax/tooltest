from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.gitops import git_result


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


class GitTextEncodingTests(unittest.TestCase):
    def test_git_show_decodes_utf8_source_independently_of_host_locale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "encoding@example.invalid")
            _git(repo, "config", "user.name", "Encoding Test")
            source = "# UTF-8 marker deliberately contains byte 0x8f in its encoding: Ϗ\nVALUE = 1\n"
            (repo / "unicode_source.py").write_text(source, encoding="utf-8")
            _git(repo, "add", "unicode_source.py")
            _git(repo, "commit", "-q", "-m", "unicode source")
            head = _git(repo, "rev-parse", "HEAD")

            result = git_result(repo, "show", f"{head}:unicode_source.py")

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, source)
            self.assertNotIn("�", result.stdout)


if __name__ == "__main__":
    unittest.main()
