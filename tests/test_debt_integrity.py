from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtSignal
from diffwitness.debt_verify import recheck_mutation_necessity
from diffwitness.ledger import LedgerItem
from diffwitness.project_scan import scan_project


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init_repo(repo: Path, files: dict[str, str]) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "integrity@example.com")
    git(repo, "config", "user.name", "Integrity Test")
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return git(repo, "rev-parse", "HEAD")


class DebtIntegrityTests(unittest.TestCase):
    def test_health_scan_is_bound_to_the_dirty_worktree_it_actually_reads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            head = init_repo(repo, {"app.py": "def parse(value):\n    return value\n"})
            head_tree = git(repo, "rev-parse", "HEAD^{tree}")

            # Deliberately do not commit the risky worktree change.
            (repo / "app.py").write_text(
                "def parse(value):\n    return eval(value)\n",
                encoding="utf-8",
            )
            report = scan_project(repo=repo, duplicate_scan=False)
            rules = {signal.rule_id for signal in report.signals}

            self.assertIn("security.dynamic-eval", rules)
            self.assertEqual(report.metadata["scan_source"], "worktree-snapshot")
            self.assertEqual(report.candidate_sha, report.metadata["snapshot_sha"])
            self.assertNotEqual(report.candidate_sha, head)
            self.assertNotEqual(report.candidate_tree, head_tree)
            self.assertEqual(
                report.candidate_tree,
                git(repo, "rev-parse", f"{report.candidate_sha}^{{tree}}"),
            )

    def test_mutation_recheck_cleans_control_run_side_effects_before_counterfactual(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            base = init_repo(
                repo,
                {
                    "app.py": "VALUE = 1\n",
                    "state.txt": "clean\n",
                    "check.py": (
                        "import app\n"
                        "from pathlib import Path\n"
                        "state = Path('state.txt').read_text(encoding='utf-8').strip()\n"
                        "Path('state.txt').write_text('dirty\\n', encoding='utf-8')\n"
                        "raise SystemExit(0 if app.VALUE == 2 or state == 'clean' else 1)\n"
                    ),
                },
            )
            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            git(repo, "add", "app.py")
            git(repo, "commit", "-q", "-m", "candidate")
            candidate = git(repo, "rev-parse", "HEAD")
            patch = git(repo, "diff", base, candidate, "--", "app.py") + "\n"

            signal = DebtSignal(
                category="evidence",
                rule_id="proof.unwitnessed-mutation",
                title="Behaviorally unwitnessed change",
                severity="medium",
                measurement="causal",
                anchor="mutation-side-effect-test",
                explanation="test",
                path="app.py",
                verification={"type": "mutation-necessity", "mutation_patch": patch},
            )
            item = LedgerItem.from_signal(signal, timestamp="2026-08-20T00:00:00+00:00")

            result = recheck_mutation_necessity(
                item,
                repo=repo,
                current_sha=candidate,
                test_command="python check.py",
                stability_runs=1,
                timeout=30.0,
                prepare_command=None,
                shared_paths=[],
            )
            # The counterfactual starts from state.txt=clean. Without the reset between control
            # and counterfactual, the control run leaves it dirty and produces a false resolution.
            self.assertEqual(result.status, "open")
            self.assertEqual(result.verification["without_mutation"]["classification"], "stable-pass")


if __name__ == "__main__":
    unittest.main()
