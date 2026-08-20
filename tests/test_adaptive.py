from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.adaptive import find_adaptive_core
from diffwitness.analysis import AnalysisError
from diffwitness.diffing import make_mutations, parse_file_patches
from diffwitness.gitops import diff_text, resolve_ref, snapshot_worktree


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout


def build_surplus_repo(repo: Path, extras: int = 7):
    git("init", "-q", cwd=repo)
    git("config", "user.email", "adaptive@example.com", cwd=repo)
    git("config", "user.name", "Adaptive Test", cwd=repo)

    (repo / "core.py").write_text("def value():\n    return 0\n", encoding="utf-8")
    for index in range(extras):
        (repo / f"extra_{index}.txt").write_text("old\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    base = resolve_ref(repo, "HEAD")

    (repo / "core.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    for index in range(extras):
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
    command = f'"{sys.executable}" -m unittest discover -s tests -q'
    return base, candidate, files, mutations, command


class AdaptiveCoreTests(unittest.TestCase):
    def test_finds_one_hunk_core_without_testing_every_surplus_hunk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base, candidate, files, mutations, command = build_surplus_repo(repo)
            self.assertEqual(len(mutations), 8)

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

    def test_advisory_partition_can_spend_tiny_budget_but_public_runner_still_proves_removal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base, candidate, files, mutations, command = build_surplus_repo(repo)
            core = next(item for item in mutations if item.path == "core.py")
            extras = [item for item in mutations if item.id != core.id]
            ordered = [item.id for item in extras] + [core.id]
            partitions = [[item.id for item in extras], [core.id]]

            result = find_adaptive_core(
                source_repo=repo,
                base_sha=base,
                candidate_sha=candidate,
                files=files,
                mutations=mutations,
                test_command=command,
                stability_runs=1,
                budget=2,
                ordered_mutation_ids=ordered,
                preferred_partitions=partitions,
            )

            self.assertTrue(result.one_minimal)
            self.assertEqual(result.core_mutation_ids, [core.id])
            self.assertEqual(result.attempts, 2)
            # One experiment rebuilt the full patch and one independently proved the proposed
            # surplus partition removable. The advisor never directly altered the verdict.
            self.assertEqual(len(result.attempts_log), 2)
            self.assertEqual(result.attempts_log[-1].kept_ids, [core.id])
            self.assertEqual(result.attempts_log[-1].classification, "stable-pass")

    def test_invalid_advisory_plan_fails_before_any_search(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base, candidate, files, mutations, command = build_surplus_repo(repo, extras=2)
            with self.assertRaisesRegex(AnalysisError, "every production mutation"):
                find_adaptive_core(
                    source_repo=repo,
                    base_sha=base,
                    candidate_sha=candidate,
                    files=files,
                    mutations=mutations,
                    test_command=command,
                    stability_runs=1,
                    budget=5,
                    ordered_mutation_ids=[mutations[0].id],
                )


if __name__ == "__main__":
    unittest.main()
