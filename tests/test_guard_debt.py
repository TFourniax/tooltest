from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.config import load_config
from diffwitness.debt_budget import ledger_path, merged_debt_config
from diffwitness.entry import main
from diffwitness.ledger import DebtLedger


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init_repo(repo: Path, *, max_per_change: int) -> None:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "guard-debt@example.com", cwd=repo)
    git("config", "user.name", "Guard Debt Test", cwd=repo)
    source = repo / "auth" / "session.py"
    source.parent.mkdir(parents=True)
    source.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / ".diffwitness.toml").write_text(
        "[diffwitness]\n"
        "stability_runs = 1\n"
        "\n[debt]\n"
        f"max_per_change = {max_per_change}\n",
        encoding="utf-8",
    )
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)


def agent_script() -> str:
    return (
        "from pathlib import Path; "
        "p=Path('auth/session.py'); "
        "p.write_text('def add(a, b):\\n    return a + b\\n', encoding='utf-8'); "
        "t=Path('tests/test_session.py'); t.parent.mkdir(exist_ok=True); "
        "t.write_text(\"import unittest\\nfrom auth.session import add\\n\\nclass T(unittest.TestCase):\\n    def test_add(self):\\n        self.assertEqual(add(2, 3), 5)\\n\", encoding='utf-8')"
    )


def guard_args(repo: Path) -> list[str]:
    command = f'"{sys.executable}" -m unittest discover -s tests -q'
    return [
        "guard",
        "--repo", str(repo),
        "--test", command,
        "--policy", "strict",
        "--stability-runs", "1",
        "--",
        sys.executable,
        "-c",
        agent_script(),
    ]


class GuardDebtTests(unittest.TestCase):
    def test_guard_records_agent_provenance_after_proof(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            init_repo(repo, max_per_change=10)
            rc = main(guard_args(repo))
            self.assertEqual(rc, 0)

            config = load_config(repo)
            ledger = DebtLedger.load(ledger_path(repo, merged_debt_config(config.get("debt") or {})))
            active = ledger.active_items()
            sensitive = next(item for item in active if item.rule_id == "security.sensitive-surface-change")
            self.assertEqual(sensitive.measurement, "heuristic")
            self.assertEqual(sensitive.introduced_by.get("source"), "guard")
            self.assertEqual(sensitive.introduced_by.get("executable"), Path(sys.executable).name)
            self.assertEqual(sensitive.introduced_by.get("agent"), Path(sys.executable).name)
            self.assertNotIn("-c", sensitive.introduced_by.values())

    def test_guard_rejects_over_budget_patch_without_admitting_rejected_debt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            init_repo(repo, max_per_change=0)
            rc = main(guard_args(repo))
            self.assertEqual(rc, 1)
            # Guard is a verifier, not a destructive rollback tool: the agent's working-tree
            # change remains inspectable even though it was rejected for admission.
            self.assertIn("return a + b", (repo / "auth/session.py").read_text(encoding="utf-8"))

            config = load_config(repo)
            ledger = DebtLedger.load(ledger_path(repo, merged_debt_config(config.get("debt") or {})))
            # A rejected candidate is not part of the accepted project history. Recording it as
            # durable project debt would pollute budgets and let repeated rejected attempts ratchet
            # the ledger upward even though none was admitted.
            self.assertEqual(ledger.active_points(), 0)
            self.assertEqual(ledger.events, [])


if __name__ == "__main__":
    unittest.main()