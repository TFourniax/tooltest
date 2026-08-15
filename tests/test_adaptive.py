from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.adaptive import find_adaptive_core
from diffwitness.diffing import make_mutations, parse_file_patches
from diffwitness.gitops import diff_text, resolve_ref, snapshot_worktree


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout


class AdaptiveCoreTests(unittest.TestCase):
    def test_finds_one_hunk_core_without_testing_every_surplus_hunk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "adaptive@example.com", cwd=repo)
            git("config", "user.name", "Adaptive Test", cwd=repo)

            (repo / "core.py").write_text("def value():\n    return 0\n", encoding="utf-8")
            for index in range(7):
                (repo / f"extra_{index}.txt").write_text("old\n", encoding="utf-8")
            git("add", ".", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)
            base = resolve_ref(repo, "HEAD")

            (repo / "core.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            for index in range(7):
                (repo / f"extra_{index}.txt").write_text("new\n", encoding="utf-8")
            (repo / "tests").mkdir()
            (repo / "tests" / "test_core.py").write_text(
                "import unittest\nfrom core import value\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_value(self):\n"
                "        self.assertEqual(value(), 1)\n",
                encoding="utf-8",
            )

            candidate = snapshot_worktree(repo)
            files = parse_file_patches(diff_text(repo, base, candidate))
            mutations = make_mutations(files)
            self.assertEqual(len(mutations), 8)

            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            result = find_adaptive_core(
                source_repo=repo,
                base_sha=base,
                candidate_sha=candidate,
                files=files,
                mutations=mutations,
                test_command=command,
                stability_runs=1,
                budget=12,
            )

            self.assertTrue(result.contrast)
            self.assertTrue(result.one_minimal)
            self.assertEqual(len(result.core_mutation_ids), 1)
            self.assertEqual(len(result.removable_mutation_ids), 7)
            self.assertLess(result.attempts, len(mutations) + 2)


if __name__ == "__main__":
    unittest.main()
