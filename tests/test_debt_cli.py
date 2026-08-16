from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from diffwitness.debt_cli import debt_cli, health_cli, ledger_cli, plan_cli


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode: raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init(repo: Path) -> str:
    git("init", "-q", cwd=repo); git("config", "user.email", "c@example.com", cwd=repo); git("config", "user.name", "C", cwd=repo)
    (repo / "app.py").write_text("def add(a,b):\n    return a-b\n", encoding="utf-8"); git("add", "-A", cwd=repo); git("commit", "-q", "-m", "base", cwd=repo); return git("rev-parse", "HEAD", cwd=repo)


class DebtCliTests(unittest.TestCase):
    def test_debt_records_local_git_ledger_and_plan_surfaces_it(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); base = init(repo); (repo / "app.py").write_text("def add(a,b):\n    return a+b\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output): rc = debt_cli(["--repo", str(repo), "--base", base, "--candidate", "WORKTREE"])
            self.assertEqual(rc, 0); self.assertTrue((repo / ".git/diffwitness/debt-ledger.jsonl").exists()); self.assertIn("Debt impact:", output.getvalue())
            output = io.StringIO()
            with redirect_stdout(output): rc = plan_cli(["--repo", str(repo)])
            self.assertEqual(rc, 0); self.assertIn("Repayment plan", output.getvalue())

    def test_health_reconciles_project_rule_and_acceptance_requires_reason(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); init(repo); (repo / "auth.py").write_text('value = eval("1+1")\n', encoding="utf-8"); git("add", "auth.py", cwd=repo); git("commit", "-q", "-m", "risk", cwd=repo)
            with redirect_stdout(io.StringIO()): self.assertEqual(health_cli(["--repo", str(repo)]), 0)
            output = io.StringIO()
            with redirect_stdout(output): ledger_cli(["--repo", str(repo), "list"])
            debt_ids = [line.split()[0] for line in output.getvalue().splitlines() if line.startswith("DW-")]; self.assertTrue(debt_ids)
            with redirect_stdout(io.StringIO()): self.assertEqual(ledger_cli(["--repo", str(repo), "accept", debt_ids[0], "--reason", "temporary migration constraint"]), 0)


if __name__ == "__main__": unittest.main()
