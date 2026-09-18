from __future__ import annotations

import hashlib
import contextlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diffwitness import continuity_context, continuity_events, continuity_state
from diffwitness.continuity_context import compile_context
from diffwitness.continuity_events import ContinuityError, append_project_event, continuity_paths
from diffwitness.continuity_state import ensure_state, rebuild_state


class ContinuityContextCacheTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "context-cache@example.test")
        self.git(repo, "config", "user.name", "Context Cache Test")
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        return repo

    def add_objective(self, repo: Path, identity: str, label: str) -> None:
        append_project_event(
            repo=repo,
            event_type="objective.declared",
            subject={"id": identity, "kind": "objective", "label": label},
            epistemic_status="DECLARED",
            payload={"priority": "high"},
            provenance={"producer": "test", "source": "unit"},
            actor={"kind": "human", "id": "test"},
            dedupe_key="objective:" + identity,
        )

    def test_hot_cache_detects_historical_tampering_before_serving_context(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.add_objective(repo, "OBJ-FIRST", "Support safe refunds")
            self.add_objective(repo, "OBJ-SECOND", "Keep payments idempotent")
            first = compile_context(repo, "safe refunds", refresh_structure=True)
            self.assertIn("OBJ-FIRST", {item["id"] for item in first["objectives"]})

            events_path = continuity_paths(repo).events
            lines = events_path.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(lines[0])
            tampered["payload"]["priority"] = "critical"
            lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            # The last event text/hash is unchanged. Detection therefore proves that the hot path is
            # anchored to the full-file SHA-256, not merely the journal tail.
            with self.assertRaises(ContinuityError):
                compile_context(repo, "safe refunds", refresh_structure=True)

    def test_legitimate_append_invalidates_cache_and_rebuilds_strictly(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.add_objective(repo, "OBJ-ONE", "Support refunds")
            first = compile_context(repo, "refunds", refresh_structure=True)
            self.assertIn("OBJ-ONE", {item["id"] for item in first["objectives"]})

            self.add_objective(repo, "OBJ-TWO", "Preserve refund idempotency")
            second = compile_context(repo, "refund idempotency", refresh_structure=True)
            self.assertIn("OBJ-TWO", {item["id"] for item in second["objectives"]})
            self.assertNotEqual(first["state"]["eventHead"], second["state"]["eventHead"])

    def test_append_after_validation_is_visible_on_next_context(self):
        for existing_cache in (False, True):
            with self.subTest(existing_cache=existing_cache), tempfile.TemporaryDirectory() as td:
                repo = self.repo(Path(td))
                self.add_objective(repo, "OBJ-ONE", "Support refunds")
                if existing_cache:
                    compile_context(repo, "refund", refresh_structure=False)
                    self.add_objective(repo, "OBJ-MIDDLE", "Review refund scope")

                def append_after_validation(*args, **kwargs):
                    state = ensure_state(*args, **kwargs)
                    self.add_objective(repo, "OBJ-TWO", "Preserve refund idempotency")
                    return state

                with patch.object(continuity_context, "ensure_state", side_effect=append_after_validation) as scheduled:
                    first = compile_context(repo, "refund", refresh_structure=False)
                scheduled.assert_called_once()
                second = compile_context(repo, "refund", refresh_structure=False)
                self.assertIn("OBJ-TWO", {item["id"] for item in second["objectives"]})
                self.assertNotEqual(first["state"]["eventHead"], second["state"]["eventHead"])

    def test_corruption_after_validation_never_becomes_a_trusted_cache_anchor(self):
        for existing_cache in (False, True):
            with self.subTest(existing_cache=existing_cache), tempfile.TemporaryDirectory() as td:
                repo = self.repo(Path(td))
                self.add_objective(repo, "OBJ-ONE", "Support refunds")
                if existing_cache:
                    compile_context(repo, "refund", refresh_structure=False)
                    self.add_objective(repo, "OBJ-MIDDLE", "Review refund scope")

                def corrupt_after_validation(*args, **kwargs):
                    state = ensure_state(*args, **kwargs)
                    path = continuity_paths(repo).events
                    path.write_bytes(path.read_bytes().replace(b"Support refunds", b"Forged refunds!"))
                    return state

                with patch.object(continuity_context, "ensure_state", side_effect=corrupt_after_validation) as scheduled:
                    compile_context(repo, "refund", refresh_structure=False)
                scheduled.assert_called_once()
                with self.assertRaises(ContinuityError):
                    compile_context(repo, "refund", refresh_structure=False)

    def test_legacy_unvalidated_digest_is_not_trusted_after_upgrade(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.add_objective(repo, "OBJ-ONE", "Support refunds")
            state = ensure_state(repo)
            path = continuity_paths(repo).events
            path.write_bytes(path.read_bytes().replace(b"Support refunds", b"Forged refunds!"))
            conn = sqlite3.connect(state)
            try:
                # Model a cache previously poisoned by the demonstrated validation/stamp race.
                conn.execute("delete from meta where key like '%file_sha256'")
                conn.execute("insert into meta(key,value) values(?,?)", (
                    "context_event_file_sha256", hashlib.sha256(path.read_bytes()).hexdigest()))
                conn.commit()
            finally:
                conn.close()
            with self.assertRaises(ContinuityError):
                compile_context(repo, "refund", refresh_structure=False)

    def test_rebuilt_state_digest_belongs_to_the_bytes_that_were_validated(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.add_objective(repo, "OBJ-ONE", "Support refunds")
            path = continuity_paths(repo).events
            # Whitespace and CRLF must be hashed exactly, not canonicalized or newline-translated.
            original = b"\r\n" + path.read_bytes().replace(b"\n", b"\r\n")
            path.write_bytes(original)
            validate = continuity_events.validate_project_events

            def mutate_after_read(events):
                validate(events)
                path.write_bytes(original.replace(b"Support refunds", b"Forged refunds!"))

            with patch.object(continuity_events, "validate_project_events", side_effect=mutate_after_read):
                state = rebuild_state(repo)
            conn = sqlite3.connect(state)
            try:
                meta = dict(conn.execute("select key,value from meta"))
                self.assertEqual(meta.get(continuity_context._CONTEXT_DIGEST_META),
                                 hashlib.sha256(original).hexdigest())
            finally:
                conn.close()
            with self.assertRaises(ContinuityError):
                compile_context(repo, "refund", refresh_structure=False)

    def test_unchanged_cache_does_not_reparse_the_journal(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.add_objective(repo, "OBJ-ONE", "Support refunds")
            first = compile_context(repo, "refund", refresh_structure=False)
            with patch.object(continuity_context, "ensure_state", side_effect=AssertionError("unexpected replay")):
                second = compile_context(repo, "refund", refresh_structure=False)
            self.assertEqual(first["state"], second["state"])
            self.assertEqual(first["objectives"], second["objectives"])

    def test_concurrent_rebuild_cannot_inherit_another_snapshot_digest(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.add_objective(repo, "OBJ-ONE", "Support refund scope")
            conn = sqlite3.connect(ensure_state(repo))
            try:
                conn.execute("delete from meta where key=?", (continuity_context._CONTEXT_DIGEST_META,))
                conn.commit()
            finally:
                conn.close()
            read_meta = continuity_state._meta
            state_lock = continuity_state._state_lock

            @contextlib.contextmanager
            def replace_state_before_lock(paths):
                # The materializer now reads/validates only after serializing
                # writers. Schedule the other reconstruction before acquisition.
                self.add_objective(repo, "OBJ-TWO", "Preserve refund idempotency")
                with patch.object(continuity_state, "_state_lock", state_lock):
                    rebuild_state(repo)
                with state_lock(paths):
                    yield

            with patch.object(continuity_state, "_state_lock", side_effect=replace_state_before_lock):
                state = ensure_state(repo)
            expected = hashlib.sha256(continuity_paths(repo).events.read_bytes()).hexdigest()
            self.assertEqual(read_meta(state).get(continuity_context._CONTEXT_DIGEST_META), expected)
            context = compile_context(repo, "refund", refresh_structure=False)
            self.assertEqual({item["id"] for item in context["objectives"]}, {"OBJ-ONE", "OBJ-TWO"})


if __name__ == "__main__":
    unittest.main()
