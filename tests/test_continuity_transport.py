from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_events import ContinuityError, append_project_event, continuity_paths, read_project_events
from diffwitness.continuity_transport import (
    DEFAULT_CONTINUITY_REF,
    checkpoint_events,
    pull_checkpoint,
    push_checkpoint,
    read_checkpoint,
)
from diffwitness.gitops import GitError


class ContinuityTransportTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.STDOUT).strip()

    def init_repo(self, root: Path, name: str = "source") -> Path:
        repo = root / name
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "continuity-transport@example.test")
        self.git(repo, "config", "user.name", "Continuity Transport")
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        return repo

    def add_event(self, repo: Path, identity: str, label: str) -> None:
        append_project_event(
            repo=repo,
            event_type="decision.recorded",
            subject={"id": identity, "kind": "decision", "label": label},
            epistemic_status="DECLARED",
            payload={"why": "transport fixture"},
            provenance={"producer": "test", "source": "unit"},
            actor={"kind": "human", "id": "test"},
            dedupe_key="decision:" + identity,
        )

    def bare_remote(self, root: Path, source: Path) -> Path:
        bare = root / "remote.git"
        subprocess.check_call(["git", "init", "--bare", "-q", str(bare)])
        self.git(source, "remote", "add", "origin", str(bare))
        self.git(source, "push", "-u", "origin", "HEAD")
        return bare

    def clone(self, root: Path, bare: Path, name: str) -> Path:
        target = root / name
        subprocess.check_call(["git", "clone", "-q", str(bare), str(target)])
        self.git(target, "config", "user.email", f"{name}@example.test")
        self.git(target, "config", "user.name", name)
        return target

    def test_checkpoint_is_idempotent_and_never_moves_head(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.init_repo(Path(td))
            self.add_event(repo, "DEC-ONE", "Keep refunds idempotent")
            self.add_event(repo, "DEC-TWO", "Preserve evidence boundaries")
            head = self.git(repo, "rev-parse", "HEAD")
            first = checkpoint_events(repo=repo)
            second = checkpoint_events(repo=repo)
            self.assertEqual(first, second)
            self.assertEqual(self.git(repo, "rev-parse", "HEAD"), head)
            checkpoint = read_checkpoint(repo=repo)
            self.assertIsNotNone(checkpoint)
            self.assertEqual(len(checkpoint[1]), 2)
            self.assertEqual(
                self.git(repo, "rev-parse", DEFAULT_CONTINUITY_REF + "^{commit}"),
                first,
            )

    def test_push_then_fresh_clone_pull_restores_exact_history_without_touching_code_head(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.init_repo(root)
            bare = self.bare_remote(root, source)
            self.add_event(source, "DEC-ONE", "Keep refunds idempotent")
            self.add_event(source, "DEC-TWO", "Never trust inferred facts as proof")
            source_events = read_project_events(continuity_paths(source).events)
            push_checkpoint(repo=source)

            clone = self.clone(root, bare, "fresh")
            head = self.git(clone, "rev-parse", "HEAD")
            self.assertEqual(read_project_events(continuity_paths(clone).events), [])
            status = pull_checkpoint(repo=clone, missing_ok=False)
            self.assertEqual(status, "restored")
            self.assertEqual(read_project_events(continuity_paths(clone).events), source_events)
            self.assertEqual(self.git(clone, "rev-parse", "HEAD"), head)

    def test_divergent_project_histories_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.init_repo(root)
            bare = self.bare_remote(root, source)
            self.add_event(source, "DEC-ROOT", "Shared starting decision")
            push_checkpoint(repo=source)

            left = self.clone(root, bare, "left")
            right = self.clone(root, bare, "right")
            self.assertEqual(pull_checkpoint(repo=left, missing_ok=False), "restored")
            self.assertEqual(pull_checkpoint(repo=right, missing_ok=False), "restored")

            self.add_event(left, "DEC-LEFT", "Left-only decision")
            push_checkpoint(repo=left)
            self.add_event(right, "DEC-RIGHT", "Right-only decision")

            with self.assertRaises(ContinuityError):
                pull_checkpoint(repo=right, missing_ok=False)
            right_ids = [event["subject"]["id"] for event in read_project_events(continuity_paths(right).events)]
            self.assertEqual(right_ids, ["DEC-ROOT", "DEC-RIGHT"])

    def test_concurrent_remote_update_is_never_force_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self.init_repo(root)
            bare = self.bare_remote(root, source)
            self.add_event(source, "DEC-ROOT", "Shared starting decision")
            push_checkpoint(repo=source)

            left = self.clone(root, bare, "left")
            right = self.clone(root, bare, "right")
            pull_checkpoint(repo=left, missing_ok=False)
            pull_checkpoint(repo=right, missing_ok=False)
            self.add_event(left, "DEC-LEFT", "Left writer")
            self.add_event(right, "DEC-RIGHT", "Right writer")
            push_checkpoint(repo=left)
            with self.assertRaises(GitError):
                push_checkpoint(repo=right)


if __name__ == "__main__":
    unittest.main()
