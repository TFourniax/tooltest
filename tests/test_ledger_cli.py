from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.entry import main as entry_main
from diffwitness.ledger import DebtLedger
from diffwitness.ledger_transport import DEFAULT_LEDGER_REF


def init_git(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    commands = (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "ledger-cli@example.com"],
        ["git", "config", "user.name", "Ledger CLI Test"],
    )
    for command in commands:
        subprocess.run(command, cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)


def signal() -> DebtSignal:
    return DebtSignal(
        category="evidence",
        rule_id="cli.lineage",
        title="CLI debt",
        severity="medium",
        measurement="causal",
        anchor="cli",
        explanation="test public ledger CLI",
    )


class LedgerCliTests(unittest.TestCase):
    def test_checkpoint_and_status_are_exposed_through_dw(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_git(repo)
            ledger_path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            ledger = DebtLedger.load(ledger_path)
            ledger.record_report(DebtReport(scope="change", signals=[signal()]))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = entry_main(["ledger", "--repo", str(repo), "checkpoint"])
            self.assertEqual(rc, 0)
            self.assertIn(DEFAULT_LEDGER_REF, stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = entry_main(["ledger", "--repo", str(repo), "status", "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["checkpoint_relation"], "equal")
            self.assertEqual(payload["ledger"]["active_points"], 3)

    def test_missing_remote_is_reported_as_cli_error_not_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_git(repo)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = entry_main(["ledger", "--repo", str(repo), "pull", "--remote", "does-not-exist"])
            self.assertEqual(rc, 2)
            self.assertIn("DiffWitness:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
