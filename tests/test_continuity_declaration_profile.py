from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_cli import decision_cli, failed_approach_cli, invariant_cli, objective_cli
from diffwitness.continuity_context import compile_context
from diffwitness.continuity_contract import project_memory_contract
from diffwitness.continuity_events import (
    ContinuityError, _canonical, _event_hash, _event_id, append_project_events,
    continuity_paths, read_project_events,
)
from diffwitness.continuity_state import ensure_state, rebuild_state
from diffwitness.continuity_transport import _parse, _serialize

PROFILE = "project-memory-declaration-1"
PROFILE_KEY = "diffwitness_profile"


class DeclarationProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        self.legacy = {
            "event_type": "objective.declared",
            "subject": {"id": "OBJ-LEGACY", "kind": "objective", "label": "Legacy refunds"},
            "epistemic_status": "DECLARED",
            "payload": {"why": "Support refunds", "priority": "normal"},
            "provenance": {"producer": "test", "source": "fixture"},
            "actor": {"kind": "human", "id": "test"},
            "timestamp": "2026-09-01T10:00:00Z",
        }
        append_project_events(repo=self.repo, events=[self.legacy])
        self.path = continuity_paths(self.repo).events
        self.original = self.path.read_bytes()

    def typed(self):
        value = copy.deepcopy(self.legacy)
        value["subject"]["id"] = "OBJ-TYPED"
        value["provenance"][PROFILE_KEY] = PROFILE
        return value

    def invalid_history(self):
        event = json.loads(self.original)
        event["provenance"][PROFILE_KEY] = PROFILE
        event["payload"]["why"] = ["not", "a", "string"]
        event["event_id"] = _event_id(event)
        event["event_hash"] = _event_hash(event)
        return (_canonical(event) + "\n").encode("utf-8")

    def test_native_commands_adopt_profile_and_keep_declared_authority(self):
        commands = (
            (objective_cli, ["add", "Refunds", "--id", "OBJ-NEW", "--component", "refunds.py"]),
            (decision_cli, ["record", "Idempotency", "--id", "DEC-NEW", "--objective", "OBJ-NEW",
                            "--component", "refunds.py", "--created-debt", "DW-NEW", "--alternative", "Retries"]),
            (invariant_cli, ["add", "Refund limit", "--id", "INV-NEW", "--critical",
                             "--objective", "OBJ-NEW", "--component", "refunds.py"]),
            (failed_approach_cli, ["record", "Direct mutation", "--id", "FAIL-NEW", "--reason", "Duplicate refunds",
                                   "--decision", "DEC-NEW", "--component", "refunds.py", "--debt", "DW-NEW"]),
        )
        for command, args in commands:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(command([*args, "--repo", str(self.repo)]), 0)
        events = read_project_events(self.path)
        self.assertEqual(len(events), 5)
        self.assertTrue(self.path.read_bytes().startswith(self.original))
        for event in events[1:]:
            self.assertEqual(event["provenance"].get(PROFILE_KEY), PROFILE)
            self.assertEqual(event["epistemic_status"], "DECLARED")
            self.assertTrue(all(edge["epistemic_status"] == "DECLARED" for edge in event["relations"]))

    def test_invalid_profile_batch_fails_before_any_append(self):
        changes = {
            "subject-kind": lambda e: e["subject"].update(kind="decision"),
            "payload-type": lambda e: e["payload"].update(why=["invalid"]),
            "unknown-version": lambda e: e["provenance"].update({PROFILE_KEY: "project-memory-declaration-999"}),
            "missing-source": lambda e: e["provenance"].pop("source"),
            "actor-id": lambda e: e["actor"].update(id=42),
            "status": lambda e: e.update(epistemic_status="VERIFIED"),
            "status-object": lambda e: e.update(epistemic_status={"status": "DECLARED"}),
            "priority": lambda e: e["payload"].update(priority="surprise"),
            "missing-field": lambda e: e["payload"].pop("why"),
            "lifecycle": lambda e: e["payload"].update(lifecycle="invented"),
            "alternatives": lambda e: e.update(event_type="decision.recorded",
                subject={"id": "DEC-X", "kind": "decision"}, payload={"why": None, "alternatives": [42]}),
            "critical": lambda e: e.update(event_type="invariant.declared",
                subject={"id": "INV-X", "kind": "invariant"}, payload={"why": None, "critical": 1}),
            "reason": lambda e: e.update(event_type="approach.failed",
                subject={"id": "FAIL-X", "kind": "failed-approach"}, payload={"reason": None}),
            "relation-status": lambda e: e.update(relations=[{
                "predicate": "served_by", "target": {"id": "COMP-X", "kind": "component"},
                "epistemic_status": "VERIFIED"}]),
            "relation-status-object": lambda e: e.update(relations=[{
                "predicate": "served_by", "target": {"id": "COMP-X", "kind": "component"},
                "epistemic_status": ["DECLARED"]}]),
            "relation-kind": lambda e: e.update(relations=[{
                "predicate": "served_by", "target": {"id": "DEC-X", "kind": "decision"}}]),
            "relation-predicate": lambda e: e.update(relations=[{
                "predicate": "proves", "target": {"id": "CHANGE-X", "kind": "change"}}]),
        }
        for name, change in changes.items():
            with self.subTest(case=name):
                self.path.write_bytes(self.original)
                invalid = self.typed()
                change(invalid)
                with self.assertRaises(ContinuityError):
                    append_project_events(repo=self.repo, events=[self.typed(), invalid])
                self.assertEqual(self.path.read_bytes(), self.original)

    def test_both_readers_reject_profile_mismatch_even_with_valid_hashes(self):
        raw = self.invalid_history()
        self.path.write_bytes(raw)
        for name, read in (("journal", lambda: read_project_events(self.path)), ("checkpoint", lambda: _parse(raw))):
            with self.subTest(reader=name), self.assertRaises(ContinuityError):
                read()
        self.assertEqual(self.path.read_bytes(), raw)

    def test_cache_from_json_only_validation_cannot_skip_profile_admission(self):
        state = ensure_state(self.repo)
        raw = self.invalid_history()
        self.path.write_bytes(raw)
        with contextlib.closing(sqlite3.connect(state)) as conn:
            conn.execute("delete from meta where key like '%file_sha256%'")
            conn.execute("insert into meta(key,value) values(?,?)", (
                "strict_json_event_file_sha256", hashlib.sha256(raw).hexdigest()))
            conn.commit()
        with self.assertRaises(ContinuityError):
            compile_context(self.repo, "refunds", refresh_structure=False)

    def test_legacy_extensions_and_typed_events_share_history_without_rewriting(self):
        extension = copy.deepcopy(self.legacy)
        extension.update(event_type="vendor.recorded", subject={"id": "EXT-OLD", "kind": "vendor-kind"},
                         payload={"why": ["historical", "extension"]})
        append_project_events(repo=self.repo, events=[extension, self.typed()])
        before = self.path.read_bytes()
        expected = read_project_events(self.path)
        self.assertNotIn(PROFILE_KEY, expected[0]["provenance"])
        self.assertNotIn(PROFILE_KEY, expected[1]["provenance"])
        self.assertEqual(_parse(_serialize(expected)), expected)
        rebuild_state(self.repo)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(before.startswith(self.original))
        self.assertEqual(read_project_events(self.path), expected)

    def test_descriptor_exposes_opt_in_profile_without_claiming_proof_authority(self):
        profile = project_memory_contract()["admission_profiles"][PROFILE]
        self.assertEqual(profile["provenance_field"], PROFILE_KEY)
        self.assertEqual(profile["epistemic_status"], "DECLARED")
        self.assertEqual(set(profile["event_types"]), {
            "objective.declared", "decision.recorded", "invariant.declared", "approach.failed"})
        self.assertFalse(profile["grants_proof_authority"])
        profile["event_types"]["objective.declared"]["subject_kind"] = "decision"
        self.assertEqual(project_memory_contract()["admission_profiles"][PROFILE]
                         ["event_types"]["objective.declared"]["subject_kind"], "objective")


if __name__ == "__main__":
    unittest.main()
