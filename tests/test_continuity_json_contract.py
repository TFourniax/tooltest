from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_context import compile_context
from diffwitness.continuity_events import (
    ContinuityError, append_project_events, continuity_paths, read_project_events,
)
from diffwitness.continuity_state import ensure_state, rebuild_state
from diffwitness.continuity_transport import DEFAULT_CONTINUITY_REF, _parse, restore_checkpoint


def legacy_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ContinuityJSONContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for args in (("init", "-q"), ("config", "user.name", "JSON Test"),
                     ("config", "user.email", "json@example.test")):
            self.git(*args)
        self.spec = {
            "event_type": "objective.declared",
            "subject": {"id": "OBJ-JSON", "kind": "objective", "label": "Refund café"},
            "epistemic_status": "DECLARED",
            "payload": {"nested": {"budget": 1}, "values": [None, True, 3.25]},
            "provenance": {"producer": "test", "source": "fixture"},
            "actor": {"kind": "human", "id": "json-test"},
            "timestamp": "2026-09-01T10:00:00Z",
        }
        append_project_events(repo=self.repo, events=[self.spec])
        self.path = continuity_paths(self.repo).events
        self.original = self.path.read_bytes()

    def git(self, *args, data=None):
        result = subprocess.run(["git", *args], cwd=self.repo, input=data,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return result.stdout.strip()

    def rejected_by_both_readers(self, raw):
        self.path.write_bytes(raw)
        readers = {"journal": lambda: read_project_events(self.path), "checkpoint": lambda: _parse(raw)}
        for name, read in readers.items():
            with self.subTest(reader=name), self.assertRaises(ContinuityError):
                read()

    def test_duplicate_members_are_rejected_at_every_nesting_level(self):
        variants = {
            "status": self.original.replace(b"{", b'{"epistemic_status":"VERIFIED",', 1),
            "subject": self.original.replace(b'"id":"OBJ-JSON"', b'"id":"OTHER","id":"OBJ-JSON"'),
            "provenance": self.original.replace(b'"producer":"test"', b'"producer":"other","producer":"test"'),
            "payload": self.original.replace(b'"budget":1', b'"budget":999,"budget":1'),
            "escaped-key": self.original.replace(b'"budget":1', b'"bu\\u0064get":999,"budget":1'),
        }
        for name, raw in variants.items():
            with self.subTest(case=name):
                self.rejected_by_both_readers(raw)

    def test_non_finite_writer_rejects_entire_batch_before_append(self):
        for number in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(number=number):
                before = self.path.read_bytes()
                invalid = {**self.spec, "payload": {"nested": [{"measurement": number}]}}
                with self.assertRaises(ContinuityError):
                    append_project_events(repo=self.repo, events=[self.spec, invalid])
                self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_non_finite_history_is_rejected_even_with_valid_old_hashes(self):
        for number in (float("nan"), float("inf"), float("-inf")):
            event = json.loads(self.original)
            event["payload"]["measurement"] = number
            stable = {k: v for k, v in event.items() if k not in {"event_id", "event_hash"}}
            event["event_id"] = "dwev_" + hashlib.sha256(legacy_json(stable).encode()).hexdigest()[:24]
            stable = {k: v for k, v in event.items() if k != "event_hash"}
            event["event_hash"] = hashlib.sha256(legacy_json(stable).encode()).hexdigest()
            raw = (legacy_json(event) + "\n").encode()
            with self.subTest(number=number):
                self.rejected_by_both_readers(raw)
            if number == float("inf"):
                with self.subTest(number="exponent-overflow"):
                    self.rejected_by_both_readers(raw.replace(b"Infinity", b"1e999"))

    def test_cache_from_permissive_parser_cannot_bypass_strict_validation(self):
        state = ensure_state(self.repo)
        ambiguous = self.original.replace(b"{", b'{"epistemic_status":"VERIFIED",', 1)
        self.path.write_bytes(ambiguous)
        conn = sqlite3.connect(state)
        try:
            conn.execute("delete from meta where key like '%file_sha256%'")
            conn.execute("insert into meta(key,value) values(?,?)", (
                "validated_event_file_sha256", hashlib.sha256(ambiguous).hexdigest()))
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(ContinuityError):
            compile_context(self.repo, "Refund", refresh_structure=False)

    def test_invalid_checkpoint_does_not_rewrite_local_journal(self):
        append_project_events(repo=self.repo, events=[{
            **self.spec, "subject": {"id": "OBJ-SECOND", "kind": "objective", "label": "Second refund"},
        }])
        ambiguous = self.path.read_bytes().replace(b"{", b'{"epistemic_status":"VERIFIED",', 1)
        self.path.write_bytes(self.original)
        blob = self.git("hash-object", "-w", "--stdin", data=ambiguous)
        tree = self.git("mktree", data=b"100644 blob " + blob + b"\tevents.jsonl\n")
        commit = self.git("commit-tree", tree.decode(), "-m", "ambiguous checkpoint fixture")
        self.git("update-ref", DEFAULT_CONTINUITY_REF, commit.decode())
        with self.assertRaises(ContinuityError):
            restore_checkpoint(repo=self.repo)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.git("rev-parse", DEFAULT_CONTINUITY_REF), commit)

    def test_valid_history_keeps_exact_bytes_identifiers_and_reconstruction(self):
        # Frozen by the previous main, before strict JSON admission was implemented.
        golden = Path(__file__).with_name("fixtures") / "project-event-1-valid.jsonl"
        canonical_fixture = golden.read_bytes().replace(b"\r\n", b"\n")
        # Existing os.open/os.write append uses the platform's native line ending.
        self.assertEqual(self.original, canonical_fixture.replace(b"\n", os.linesep.encode("ascii")))
        original_event = json.loads(self.original)
        for ending in (b"\n", b"\r\n", b"\r"):
            with self.subTest(ending=ending):
                raw = canonical_fixture.replace(b"\n", ending)
                self.path.write_bytes(raw)
                self.assertEqual(read_project_events(self.path), [original_event])
                self.assertEqual(_parse(raw), [original_event])
                rebuild_state(self.repo)
                self.assertEqual(self.path.read_bytes(), raw)
                context = compile_context(self.repo, "Refund", refresh_structure=False)
                self.assertEqual(context["state"]["eventHead"], original_event["event_hash"])
                self.assertEqual(context["objectives"][0]["epistemicStatus"], "DECLARED")

    def test_unicode_line_separators_inside_strings_do_not_split_events(self):
        append_project_events(repo=self.repo, events=[{
            **self.spec, "payload": {"text": "a\u2028b\u2029c\u0085d"},
        }])
        expected = read_project_events(self.path)
        self.assertEqual(_parse(self.path.read_bytes()), expected)


if __name__ == "__main__":
    unittest.main()
