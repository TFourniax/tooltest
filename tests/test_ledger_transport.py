from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.ledger import DebtLedger, LedgerError
from diffwitness.ledger_transport import checkpoint_ledger, read_checkpoint, restore_checkpoint


def init_git(repo: Path) -> None:
    import subprocess

    for args in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "ledger@example.com"],
        ["git", "config", "user.name", "Ledger Test"],
    ):
        proc = subprocess.run(args, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode:
            raise RuntimeError(proc.stderr)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)


def signal(anchor: str) -> DebtSignal:
    return DebtSignal(
        category="evidence",
        rule_id="test.lineage",
        title="Tracked obligation",
        severity="medium",
        measurement="causal",
        anchor=anchor,
        explanation="test",
    )


class LedgerTransportTests(unittest.TestCase):
    def test_checkpoint_restores_into_empty_clone_state_without_touching_head(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            init_git(repo)
            head_before = __import__("subprocess").check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            ledger = DebtLedger.load(path)
            ledger.record_report(DebtReport(scope="change", signals=[signal("a")]))
            commit = checkpoint_ledger(repo=repo, ledger=ledger)
            self.assertTrue(commit)
            self.assertEqual(
                __import__("subprocess").check_output(
                    ["git", "rev-parse", "HEAD"], cwd=repo, text=True
                ).strip(),
                head_before,
            )

            path.unlink()
            empty = DebtLedger.load(path)
            self.assertEqual(restore_checkpoint(repo=repo, ledger=empty), "restored")
            self.assertEqual(empty.active_points(), 3)
            checkpoint = read_checkpoint(repo=repo, ledger_path=path)
            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint.last_hash, empty.last_hash)

    def test_checkpoint_history_is_fast_forward_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            init_git(repo)
            path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            ledger = DebtLedger.load(path)
            ledger.record_report(DebtReport(scope="change", signals=[signal("a")]))
            first = checkpoint_ledger(repo=repo, ledger=ledger)
            ledger.record_report(DebtReport(scope="change", signals=[signal("b")]))
            second = checkpoint_ledger(repo=repo, ledger=ledger)
            self.assertNotEqual(first, second)

            old = read_checkpoint(repo=repo, ledger_path=path)
            self.assertIsNotNone(old)
            self.assertEqual(len(old.events), 2)

            # Manufacture a valid but divergent local chain from the first event and a different
            # second event. Restore must refuse to guess how to merge histories.
            divergent_path = repo / ".git" / "diffwitness" / "divergent.jsonl"
            divergent = DebtLedger(divergent_path, ledger.events[:1])
            divergent._persist()
            divergent.record_report(DebtReport(scope="change", signals=[signal("c")]))
            with self.assertRaisesRegex(LedgerError, "diverged"):
                restore_checkpoint(repo=repo, ledger=divergent)


if __name__ == "__main__":
    unittest.main()
