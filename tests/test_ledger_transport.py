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


def run_bytes(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
    return proc.stdout


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
    # Local test remotes are deleted immediately after each test. `git receive-pack` normally
    # starts automatic maintenance after a successful push; on slower/macOS runners that detached
    # maintenance can still be touching objects while TemporaryDirectory begins removal. Disable
    # remote-side auto maintenance here so cleanup cannot race an irrelevant background Git task.
    run(path, "config", "receive.autogc", "false")
    run(path, "config", "gc.auto", "0")


def ledger_for(repo: Path) -> DebtLedger:
    return DebtLedger.load(repo / ".git" / "diffwitness" / "debt-ledger.jsonl")


def signal(anchor: str) -> DebtSignal:
    return DebtSignal(
        category="test",
        measurement="deterministic",
        title=f"test debt {anchor}",
        detail="fixture",
        path=f"src/{anchor}.py",
        anchor=anchor,
        points=3,
        confidence="high",
    )


class LedgerTransportTests(unittest.TestCase):
    def test_checkpoint_tree_and_blob_are_platform_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_git(repo)
            path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            ledger = DebtLedger.load(path)
            ledger.record_report(DebtReport(scope="change", signals=[signal("a")]))
            commit = checkpoint_ledger(repo=repo, ledger=ledger)
            tree = run_bytes(repo, "ls-tree", "-z", commit)
            self.assertIn(b"\tledger.jsonl\x00", tree)
            self.assertNotIn(b"ledger.jsonl\r", tree)
            blob = run_bytes(repo, "show", f"{commit}:ledger.jsonl")
            self.assertNotIn(b"\r\n", blob)
            self.assertTrue(blob.endswith(b"\n"))

    def test_checkpoint_is_idempotent_for_unchanged_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_git(repo)
            path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            ledger = DebtLedger.load(path)
            ledger.record_report(DebtReport(scope="change", signals=[signal("a")]))
            first = checkpoint_ledger(repo=repo, ledger=ledger)
            second = checkpoint_ledger(repo=repo, ledger=ledger)
            self.assertEqual(first, second)

    def test_checkpoint_restores_into_empty_clone_state_without_touching_head(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            init_git(repo)
            head = run(repo, "rev-parse", "HEAD")
            source_path = repo / ".git" / "diffwitness" / "debt-ledger.jsonl"
            source = DebtLedger.load(source_path)
            source.record_report(DebtReport(scope="change", signals=[signal("a")]))
            checkpoint_ledger(repo=repo, ledger=source)

            fresh_path = repo / ".git" / "diffwitness" / "fresh.jsonl"
            fresh = DebtLedger.load(fresh_path)
            status = restore_checkpoint(repo=repo, ledger=fresh)
            self.assertEqual(status, "restored")
            self.assertEqual(fresh.last_hash, source.last_hash)
            self.assertEqual(run(repo, "rev-parse", "HEAD"), head)

    def test_project_reconciliation_only_closes_project_rules(self) -> None:
        # Kept in ledger tests; this file focuses on transport semantics.
        pass

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
            self.assertEqual(pull_checkpoint(repo=consumer, ledger=consumer_ledger), "missing")


if __name__ == "__main__":
    unittest.main()
