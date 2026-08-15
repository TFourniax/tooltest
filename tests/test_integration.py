from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.analysis import run_analysis
from diffwitness.diffing import make_mutations, parse_file_patches
from diffwitness.gitops import diff_text, resolve_ref, snapshot_worktree


def run(*args: str, cwd: Path) -> str:
    proc = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout


class IntegrationTests(unittest.TestCase):
    def test_finds_witnessed_and_unwitnessed_hunks_with_new_untracked_test(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            run("git", "init", "-q", cwd=repo)
            run("git", "config", "user.email", "test@example.com", cwd=repo)
            run("git", "config", "user.name", "Diff Witness Test", cwd=repo)
            (repo / "calc.py").write_text(
                "def add(a, b):\n    return a - b\n\n\n\n\n\n\n\n\ndef label():\n    return 'calc'\n",
                encoding="utf-8",
            )
            run("git", "add", "calc.py", cwd=repo)
            run("git", "commit", "-q", "-m", "buggy baseline", cwd=repo)
            base = resolve_ref(repo, "HEAD")

            # Fix plus a deliberately unrelated second hunk.
            (repo / "calc.py").write_text(
                "def add(a, b):\n    return a + b\n\n\n\n\n\n\n\n\ndef label():\n    return 'calculator'\n",
                encoding="utf-8",
            )
            tests = repo / "tests"
            tests.mkdir()
            (tests / "test_calc.py").write_text(
                "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )

            candidate = snapshot_worktree(repo)
            files = parse_file_patches(diff_text(repo, base, candidate))
            mutations = make_mutations(files)
            self.assertEqual(len(mutations), 2)

            candidate_result, baseline_result, results, test_files, _, _ = run_analysis(
                source_repo=repo,
                base_sha=base,
                candidate_sha=candidate,
                files=files,
                mutations=mutations,
                test_command="python -m unittest discover -s tests -q",
                timeout=30,
                prepare_command=None,
                shared_paths=[],
                overlay_candidate_tests=True,
                minimize=False,
            )
            self.assertTrue(candidate_result.passed)
            self.assertFalse(baseline_result.passed)
            self.assertEqual(test_files, ["tests/test_calc.py"])
            statuses = {r.mutation.label: r.status for r in results}
            self.assertEqual(sorted(statuses.values()), ["unwitnessed", "witnessed"])


if __name__ == "__main__":
    unittest.main()
