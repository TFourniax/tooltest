from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.analysis import run_analysis
from diffwitness.diffing import make_mutations, parse_file_patches
from diffwitness.gitops import diff_text, resolve_ref, snapshot_worktree
from diffwitness.reporting import build_report


def run(*args: str, cwd: Path) -> str:
    proc = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout


def commit(repo: Path, message: str) -> None:
    run("git", "add", "-A", cwd=repo)
    run("git", "-c", "user.email=test@example.com", "-c", "user.name=DiffWitness Test", "commit", "-q", "-m", message, cwd=repo)


def test_command() -> str:
    return f'"{sys.executable}" -m unittest discover -s tests -q'


class IntegrationTests(unittest.TestCase):
    def test_minimal_sufficient_core_and_surplus_hunk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            run("git", "init", "-q", cwd=repo)
            baseline = (
                "def left(x):\n    return x - 1\n"
                + "\n" * 10
                + "def right(x):\n    return x - 1\n"
                + "\n" * 10
                + "def total(x):\n    return left(x) + right(x)\n"
                + "\n" * 10
                + "def label():\n    return 'calc'\n"
            )
            (repo / "calc.py").write_text(baseline, encoding="utf-8")
            commit(repo, "buggy baseline")
            base = resolve_ref(repo, "HEAD")

            candidate_text = baseline.replace("x - 1", "x + 1").replace("return 'calc'", "return 'calculator'")
            (repo / "calc.py").write_text(candidate_text, encoding="utf-8")
            tests = repo / "tests"
            tests.mkdir()
            (tests / "test_calc.py").write_text(
                "import unittest\nfrom calc import total\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_total(self):\n"
                "        self.assertEqual(total(1), 4)\n",
                encoding="utf-8",
            )

            candidate = snapshot_worktree(repo)
            files = parse_file_patches(diff_text(repo, base, candidate))
            mutations = make_mutations(files)
            self.assertEqual(len(mutations), 3)

            outcome = run_analysis(
                source_repo=repo,
                base_sha=base,
                candidate_sha=candidate,
                files=files,
                mutations=mutations,
                test_command=test_command(),
                timeout=30,
                prepare_command=None,
                shared_paths=[],
                overlay_candidate_tests=True,
                minimize=True,
                stability_runs=2,
                search_sufficient=True,
                max_subset_order=2,
                max_subset_runs=20,
                search_interactions=True,
                max_interaction_runs=10,
            )
            self.assertTrue(outcome.candidate.passed)
            self.assertTrue(outcome.baseline.failed)
            self.assertEqual(outcome.test_files, ["tests/test_calc.py"])
            statuses = [r.status for r in outcome.mutation_results]
            self.assertEqual(statuses.count("witnessed"), 2)
            self.assertEqual(statuses.count("unwitnessed"), 1)
            self.assertEqual(outcome.sufficient_search.found_order, 2)
            sufficient = [r for r in outcome.sufficient_search.results if r.status == "sufficient"]
            self.assertEqual(len(sufficient), 1)
            self.assertEqual(len(sufficient[0].mutation_ids), 2)
            self.assertTrue(outcome.sufficient_search.exhaustive_at_found_order)
            self.assertEqual(len(outcome.minimized_removed_ids or []), 1)

            report = build_report(
                repo=repo,
                base_ref="HEAD",
                base_sha=base,
                candidate_ref="WORKTREE",
                candidate_sha=candidate,
                test_command=test_command(),
                outcome=outcome,
                ignored_count=0,
                config={},
            )
            self.assertEqual(report["summary"]["surplus_candidate_hunks"], 1)
            self.assertTrue(report["certificate_id"].startswith("dw2_"))

    def test_mutual_backup_pair_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            run("git", "init", "-q", cwd=repo)
            baseline = (
                "def primary():\n    return False\n"
                + "\n" * 10
                + "def fallback():\n    return False\n"
                + "\n" * 10
                + "def available():\n    return primary() or fallback()\n"
            )
            (repo / "feature.py").write_text(baseline, encoding="utf-8")
            commit(repo, "unavailable baseline")
            base = resolve_ref(repo, "HEAD")

            candidate_text = baseline.replace("return False", "return True")
            (repo / "feature.py").write_text(candidate_text, encoding="utf-8")
            (repo / "tests").mkdir()
            (repo / "tests" / "test_feature.py").write_text(
                "import unittest\nfrom feature import available\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_available(self):\n"
                "        self.assertTrue(available())\n",
                encoding="utf-8",
            )
            candidate = snapshot_worktree(repo)
            files = parse_file_patches(diff_text(repo, base, candidate))
            mutations = make_mutations(files)
            self.assertEqual(len(mutations), 2)

            outcome = run_analysis(
                source_repo=repo,
                base_sha=base,
                candidate_sha=candidate,
                files=files,
                mutations=mutations,
                test_command=test_command(),
                timeout=30,
                prepare_command=None,
                shared_paths=[],
                overlay_candidate_tests=True,
                minimize=False,
                stability_runs=1,
                search_sufficient=True,
                max_subset_order=1,
                max_subset_runs=10,
                search_interactions=True,
                max_interaction_runs=10,
            )
            self.assertEqual([r.status for r in outcome.mutation_results], ["unwitnessed", "unwitnessed"])
            sufficient = [r for r in outcome.sufficient_search.results if r.status == "sufficient"]
            self.assertEqual(len(sufficient), 2)
            backups = [r for r in outcome.interaction_search.results if r.status == "mutual-backup"]
            self.assertEqual(len(backups), 1)
            self.assertEqual(set(backups[0].mutation_ids), {m.id for m in mutations})

    def test_worktree_snapshot_does_not_require_persistent_git_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            run("git", "init", "-q", cwd=repo)
            (repo / "a.txt").write_text("one\n", encoding="utf-8")
            commit(repo, "initial")
            # No repository user.name/user.email was configured; commit() used one-shot -c values.
            probe = subprocess.run(["git", "config", "--get", "user.name"], cwd=repo, text=True, stdout=subprocess.PIPE)
            self.assertNotEqual(probe.returncode, 0)
            (repo / "a.txt").write_text("two\n", encoding="utf-8")
            sha = snapshot_worktree(repo)
            self.assertEqual(len(sha), 40)


if __name__ == "__main__":
    unittest.main()
