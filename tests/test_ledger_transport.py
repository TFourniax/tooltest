from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.gitops import GitError
from diffwitness.ledger import DebtLedger, LedgerError
from diffwitness.ledger_transport import (
    DEFAULT_LEDGER_REF,
    checkpoint_ledger,
    pull_checkpoint,
    push_checkpoint,
    read_checkpoint,
    restore_checkpoint,
)


def run(repo: Path, *args: str) -> str:
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


def init_git(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    for args in (
        ("init", "-q"),
        ("config", "user.email", "ledger@example.com"),
        ("config", "user.name", "Ledger Test"),
    ):
        run(repo, *args)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    run(repo, "add", "README.md")
    run(repo, "commit", "-q", "-m", "base")


def add_remote(repo: Path, remote: Path) -> None:
    run(repo, "remote", "add", "origin", str(remote))


def init_bare(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "init", "--bare", "-q", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)


def ledger_for(repo: Path) -> DebtLedger:
    return DebtLedger.load(repo / ".git" / "diffwitness" / "debt-ledger.jsonl")


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
            repo = Path(td) / "repo"
            init_git(repo)
            head_before = run(repo, "rev-parse", "HEAD")
            path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            ledger = DebtLedger.load(path)
            ledger.record_report(DebtReport(scope="change", signals=[signal("a")]))
            commit = checkpoint_ledger(repo=repo, ledger=ledger)
            self.assertTrue(commit)
            self.assertEqual(run(repo, "rev-parse", "HEAD"), head_before)

            path.unlink()
            empty = DebtLedger.load(path)
            self.assertEqual(restore_checkpoint(repo=repo, ledger=empty), "restored")
            self.assertEqual(empty.active_points(), 3)
            checkpoint = read_checkpoint(repo=repo, ledger_path=path)
            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint.last_hash, empty.last_hash)

    def test_checkpoint_is_idempotent_for_unchanged_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_git(repo)
            ledger = ledger_for(repo)
            ledger.record_report(DebtReport(scope="change", signals=[signal("a")]))
            first = checkpoint_ledger(repo=repo, ledger=ledger)
            second = checkpoint_ledger(repo=repo, ledger=ledger)
            self.assertEqual(first, second)

    def test_checkpoint_history_is_fast_forward_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
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

    def test_remote_push_and_fresh_pull_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            remote = root / "remote.git"
            source = root / "source"
            consumer = root / "consumer"
            init_bare(remote)
            init_git(source)
            init_git(consumer)
            add_remote(source, remote)
            add_remote(consumer, remote)

            source_ledger = ledger_for(source)
            source_ledger.record_report(DebtReport(scope="change", signals=[signal("shared")]))
            push_checkpoint(repo=source, ledger=source_ledger)

            consumer_ledger = ledger_for(consumer)
            self.assertEqual(pull_checkpoint(repo=consumer, ledger=consumer_ledger), "restored")
            self.assertEqual(consumer_ledger.last_hash, source_ledger.last_hash)
            self.assertEqual(consumer_ledger.active_points(), 3)

    def test_remote_concurrent_update_never_force_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            remote = root / "remote.git"
            first_repo = root / "first"
            second_repo = root / "second"
            init_bare(remote)
            init_git(first_repo)
            init_git(second_repo)
            add_remote(first_repo, remote)
            add_remote(second_repo, remote)

            first = ledger_for(first_repo)
            first.record_report(DebtReport(scope="change", signals=[signal("base")]))
            push_checkpoint(repo=first_repo, ledger=first)

            second = ledger_for(second_repo)
            self.assertEqual(pull_checkpoint(repo=second_repo, ledger=second), "restored")
            second.record_report(DebtReport(scope="change", signals=[signal("remote-new")]))
            push_checkpoint(repo=second_repo, ledger=second)

            # The first writer is now stale. Its push must fail rather than force-overwrite the
            # remote branch, and the subsequent pull must surface the divergent event histories.
            first.record_report(DebtReport(scope="change", signals=[signal("local-new")]))
            with self.assertRaises(GitError):
                push_checkpoint(repo=first_repo, ledger=first)
            with self.assertRaisesRegex(LedgerError, "diverged"):
                pull_checkpoint(repo=first_repo, ledger=first)

    def test_missing_remote_ref_cannot_reuse_stale_tracking_ref(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            remote = root / "remote.git"
            source = root / "source"
            consumer = root / "consumer"
            init_bare(remote)
            init_git(source)
            init_git(consumer)
            add_remote(source, remote)
            add_remote(consumer, remote)

            source_ledger = ledger_for(source)
            source_ledger.record_report(DebtReport(scope="change", signals=[signal("once")]))
            push_checkpoint(repo=source, ledger=source_ledger)
            consumer_ledger = ledger_for(consumer)
            self.assertEqual(pull_checkpoint(repo=consumer, ledger=consumer_ledger), "restored")

            run(remote, "update-ref", "-d", DEFAULT_LEDGER_REF)
            # A stale local tracking ref from the previous successful fetch must not make this
            # second pull appear successful after the remote checkpoint was deleted.
            self.assertEqual(pull_checkpoint(repo=consumer, ledger=consumer_ledger), "missing")


if __name__ == "__main__":
    unittest.main()
