from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_cli import plan_cli, repay_cli
from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.ledger import DebtLedger, LedgerError


def run(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    run(repo, "init", "-q")
    run(repo, "config", "user.email", "planning@example.com")
    run(repo, "config", "user.name", "Planning Test")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    run(repo, "add", "README.md")
    run(repo, "commit", "-q", "-m", "base")


def signal(anchor: str, verification_type: str, *, category: str = "evidence") -> DebtSignal:
    return DebtSignal(
        category=category,
        rule_id=f"test.{anchor}",
        title=f"Debt {anchor}",
        severity="medium",
        measurement="causal" if verification_type == "mutation-necessity" else "heuristic",
        anchor=anchor,
        explanation="planning contract",
        verification={"type": verification_type},
    )


class DebtPlanningTests(unittest.TestCase):
    def test_plan_separates_automatic_repayment_from_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            ledger = DebtLedger.load(repo / ".git" / "diffwitness" / "debt-ledger.jsonl")
            automatic = signal("automatic", "project-rule", category="architecture")
            manual = signal("manual", "change-review", category="complexity")
            ledger.record_report(DebtReport(scope="project", signals=[automatic, manual]))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = plan_cli(["--repo", str(repo), "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual([item["debt_id"] for item in payload["selected"]], [automatic.debt_id])
            self.assertEqual([item["debt_id"] for item in payload["manual_review"]], [manual.debt_id])
            self.assertEqual(payload["selected_points"], automatic.points)
            self.assertEqual(payload["manual_review_points"], manual.points)

    def test_repay_refuses_lineage_without_automatic_closure_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            ledger = DebtLedger.load(repo / ".git" / "diffwitness" / "debt-ledger.jsonl")
            manual = signal("manual-only", "change-review", category="complexity")
            ledger.record_report(DebtReport(scope="change", signals=[manual]))

            with self.assertRaisesRegex(LedgerError, "cannot prove closure"):
                repay_cli([manual.debt_id, "--repo", str(repo), "--prompt-only"])

    def test_repay_all_ignores_manual_backlog_instead_of_promising_closure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_repo(repo)
            ledger = DebtLedger.load(repo / ".git" / "diffwitness" / "debt-ledger.jsonl")
            automatic = signal("automatic-all", "project-rule", category="architecture")
            manual = signal("manual-all", "change-review", category="complexity")
            ledger.record_report(DebtReport(scope="project", signals=[automatic, manual]))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = repay_cli(["--repo", str(repo), "--all", "--prompt-only"])
            self.assertEqual(rc, 0)
            prompt = stdout.getvalue()
            self.assertIn(automatic.debt_id, prompt)
            self.assertNotIn(manual.debt_id, prompt)


if __name__ == "__main__":
    unittest.main()
