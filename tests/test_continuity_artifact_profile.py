from __future__ import annotations

import contextlib
import copy
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures

from diffwitness.continuity_bridge import record_change_envelope
from diffwitness.continuity_contract import project_memory_contract
from diffwitness.continuity_context import compile_context
from diffwitness.continuity_events import (
    ContinuityError, _canonical, _event_hash, _event_id,
    append_project_events, continuity_paths, read_project_events,
)
from diffwitness.continuity_state import ensure_state, rebuild_state
from diffwitness.continuity_transport import _parse, _serialize

PROFILE = "project-memory-artifact-1"
KEY = "diffwitness_profile"


class ArtifactProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        fixture = fixtures.ContinuityKernelTests()
        self.repo = fixture.repo(Path(temp.name))
        self.envelope, self.cid = fixture.envelope(self.repo)
        self.path = continuity_paths(self.repo).events
        with patch("diffwitness.continuity_bridge.append_project_events") as append:
            append.side_effect = lambda *, repo, events: [(event, True) for event in events]
            record_change_envelope(repo=self.repo, envelope=self.envelope)
            self.specs = copy.deepcopy(append.call_args.kwargs["events"])
        # The pre-profile bridge's exact semantic fields, not rewritten history.
        for spec in self.specs:
            spec["provenance"].pop(KEY, None)
        self.typed = copy.deepcopy(self.specs)
        for spec in self.typed:
            spec["provenance"][KEY] = PROFILE

    def reset_history(self):
        if self.path.exists():
            self.path.unlink()

    def test_native_producer_profiles_all_five_types_without_promoting_imports(self):
        record_change_envelope(repo=self.repo, envelope=self.envelope)
        events = read_project_events(self.path)
        self.assertEqual({e["event_type"] for e in events}, {
            "change.observed", "proof.completed", "debt.snapshot", "debt.observed", "understanding.recorded"})
        self.assertTrue(all(e["provenance"].get(KEY) == PROFILE for e in events))
        self.assertTrue(all(e["epistemic_status"] == "OBSERVED" for e in events))
        self.assertEqual(_parse(_serialize(events)), events)
        before = self.path.read_bytes()
        rebuild_state(self.repo)
        self.assertEqual(before, self.path.read_bytes())

    def test_compatible_legacy_reimport_preserves_original_events_and_bytes(self):
        for old, new in ((self.specs, self.typed), (self.typed, self.specs)):
            with self.subTest(old_profile=old[0]["provenance"].get(KEY)):
                self.reset_history()
                original = append_project_events(repo=self.repo, events=old)
                before = self.path.read_bytes()
                result = append_project_events(repo=self.repo, events=new)
                self.assertTrue(all(not created for _, created in result))
                self.assertEqual([e for e, _ in result], [e for e, _ in original])
                self.assertEqual(self.path.read_bytes(), before)

    def test_legacy_digest_and_ephemeral_sha_exceptions_survive_profile_adoption(self):
        append_project_events(repo=self.repo, events=self.specs)
        before = self.path.read_bytes()
        self.typed[0]["payload"].update(base_sha="new-base", candidate_sha="new-candidate")
        for event in self.typed:
            event["provenance"]["artifact_digest"] = "sha256:" + "a" * 64
        result = append_project_events(repo=self.repo, events=self.typed)
        self.assertTrue(all(not created for _, created in result))
        self.assertEqual(self.path.read_bytes(), before)

    def test_native_reimport_adopts_legacy_without_rewriting_it(self):
        append_project_events(repo=self.repo, events=self.specs)
        before = self.path.read_bytes()
        result = record_change_envelope(repo=self.repo, envelope=self.envelope)
        self.assertEqual(sum(result["created"].values()), 0)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_legacy_cannot_gain_profile_compatibility_via_ignored_fields(self):
        for section, field, value in (("payload", "base_sha", False),
                                      ("provenance", "artifact_digest", [])):
            with self.subTest(field=field):
                self.reset_history()
                old = copy.deepcopy(self.specs[0])
                old[section][field] = value
                append_project_events(repo=self.repo, events=[old])
                before = self.path.read_bytes()
                with self.assertRaises(ContinuityError):
                    append_project_events(repo=self.repo, events=self.typed[:1])
                self.assertEqual(self.path.read_bytes(), before)

    def test_declaration_and_relation_json_conflicts_fail_atomically(self):
        declaration = {
            "event_type": "objective.declared", "subject": {"id": "OBJ-TYPE", "kind": "objective"},
            "epistemic_status": "DECLARED", "payload": {"why": None, "priority": "normal", "extension": True},
            "provenance": {"producer": "test", "source": "fixture", KEY: "project-memory-declaration-1"},
            "actor": {"kind": "human", "id": "test"}, "dedupe_key": "objective:type",
        }
        changed = copy.deepcopy(declaration)
        changed["payload"]["extension"] = 1
        with self.assertRaises(ContinuityError):
            append_project_events(repo=self.repo, events=[declaration, changed])
        self.assertFalse(self.path.exists())
        old = copy.deepcopy(self.typed[0])
        old["relations"][0]["metadata"]["extension"] = True
        append_project_events(repo=self.repo, events=[old])
        before = self.path.read_bytes()
        changed = copy.deepcopy(old)
        changed["relations"][0]["metadata"]["extension"] = 1
        with self.assertRaises(ContinuityError):
            append_project_events(repo=self.repo, events=[self.typed[1], changed])
        self.assertEqual(self.path.read_bytes(), before)

    def test_json_type_conflicts_are_not_silently_deduped(self):
        for section in ("payload", "provenance", "actor"):
            for first, second in ((True, 1), (False, 0), ([True], [1]), ({"x": False}, {"x": 0}), (1, 1.0)):
                with self.subTest(section=section, first=first, second=second):
                    self.reset_history()
                    old = copy.deepcopy(self.specs[0])
                    old[section]["extension_value"] = first
                    append_project_events(repo=self.repo, events=[old])
                    before = self.path.read_bytes()
                    new = copy.deepcopy(old)
                    new[section]["extension_value"] = second
                    with self.assertRaises(ContinuityError):
                        append_project_events(repo=self.repo, events=[new])
                    self.assertEqual(self.path.read_bytes(), before)

    def test_profile_does_not_hide_real_conflicts_or_other_profiles(self):
        changes = (
            lambda e: e["provenance"].update(producer="other"),
            lambda e: e["payload"].update(changed_files=[]),
            lambda e: e["actor"].update(id="another-agent"),
            lambda e: e["provenance"].update({KEY: "project-memory-artifact-999"}),
            lambda e: e["provenance"].update({KEY: "project-memory-declaration-1"}),
        )
        append_project_events(repo=self.repo, events=self.specs)
        before = self.path.read_bytes()
        for change in changes:
            with self.subTest(change=change):
                new = copy.deepcopy(self.typed[0])
                change(new)
                with self.assertRaises(ContinuityError):
                    append_project_events(repo=self.repo, events=[new])
                self.assertEqual(self.path.read_bytes(), before)

    def test_malformed_profile_batches_are_atomic(self):
        cases = (
            (0, lambda e: e["subject"].update(kind="objective")),
            (0, lambda e: e["subject"].update(id="dwchg_wrong")),
            (0, lambda e: e["payload"].update(base_tree="other")),
            (0, lambda e: e["payload"].update(changed_files=[1])),
            (0, lambda e: e["payload"].update(base_sha=False)),
            (0, lambda e: e["relations"][0]["target"].update(kind="change")),
            (0, lambda e: e["provenance"].update(source="other")),
            (0, lambda e: e["actor"].update(id=1)),
            (0, lambda e: e["payload"].update(lifecycle=[])),
            (1, lambda e: e["payload"].update(accepted=1)),
            (1, lambda e: e["payload"].update(certificate_schema=True)),
            (1, lambda e: e["payload"].update(authoritative_validation="false")),
            (1, lambda e: e.update(epistemic_status="VERIFIED")),
            (1, lambda e: e["provenance"].update(authoritative_validation=True)),
            (1, lambda e: e["relations"][0]["metadata"].update(authoritative_validation=True)),
            (1, lambda e: e["relations"][0]["target"].update(id="dwchg_other")),
            (1, lambda e: e["relations"][0].update(epistemic_status="VERIFIED")),
            (1, lambda e: e.update(relations=[])),
            (2, lambda e: e["payload"].update(points=True)),
            (2, lambda e: e["payload"].update(obligations=-1)),
            (2, lambda e: e["payload"].update(budget_passed=1)),
            (2, lambda e: e["payload"].update(change_id="dwchg_other")),
            (3, lambda e: e["subject"].update(id="OTHER-DEBT")),
            (3, lambda e: e["relations"][0].update(predicate="proves")),
            (4, lambda e: e["payload"].update(coverage=101)),
            (4, lambda e: e["payload"].update(feature_debt=False)),
            (4, lambda e: e["payload"].update(receipt_digest=[])),
            (4, lambda e: e["subject"].update(id="understanding:other")),
        )
        for index, change in cases:
            with self.subTest(index=index, change=change):
                self.reset_history()
                invalid = copy.deepcopy(self.typed[index])
                change(invalid)
                with self.assertRaises(ContinuityError):
                    append_project_events(repo=self.repo, events=[self.typed[0], invalid])
                self.assertFalse(self.path.exists())

    def test_consumed_input_types_are_checked_before_projection(self):
        for section, field in (("actor", "kind"), ("actor", "agent"), ("actor", "id"),
                               ("proof", "certificate_id"), ("proof", "claim"),
                               ("proof", "certificate_schema"), ("base", "sha"),
                               ("understanding", "receipt_digest")):
            for value in (False, 1.5, [], {}):
                with self.subTest(section=section, field=field, value=value):
                    self.reset_history()
                    envelope = copy.deepcopy(self.envelope)
                    envelope.setdefault(section, {})[field] = value
                    with self.assertRaises(ContinuityError):
                        record_change_envelope(repo=self.repo, envelope=envelope)
                    self.assertFalse(self.path.exists())
        for kwargs in ({"trusted_proof": "false"}, {"trusted_proof": 1}, {"actor": 42}):
            with self.subTest(kwargs=kwargs):
                self.reset_history()
                with self.assertRaises(ContinuityError):
                    record_change_envelope(repo=self.repo, envelope=self.envelope, **kwargs)
                self.assertFalse(self.path.exists())

    def test_authoritative_flag_consistency_preserves_existing_runner_boundary(self):
        for trusted, accepted in ((False, True), (True, True), (True, False)):
            with self.subTest(trusted=trusted, accepted=accepted):
                self.reset_history()
                envelope = copy.deepcopy(self.envelope)
                envelope["proof"]["accepted"] = accepted
                record_change_envelope(repo=self.repo, envelope=envelope, trusted_proof=trusted)
                proof = next(e for e in read_project_events(self.path) if e["event_type"] == "proof.completed")
                self.assertEqual(proof["epistemic_status"], "VERIFIED" if trusted and accepted else "OBSERVED")
                self.assertIs(proof["payload"]["authoritative_validation"], trusted)

    def test_mixed_history_replay_and_checkpoint_preserve_legacy_extensions(self):
        legacy = copy.deepcopy(self.specs[2])
        legacy["payload"]["extension"] = {"old": [True, 1]}
        append_project_events(repo=self.repo, events=[legacy, self.typed[0], self.typed[1]])
        before = self.path.read_bytes()
        events = read_project_events(self.path)
        self.assertEqual(_parse(_serialize(events)), events)
        rebuild_state(self.repo)
        self.assertEqual(self.path.read_bytes(), before)

    def test_readers_and_old_cache_cannot_bypass_typed_validation(self):
        # A valid hash is integrity evidence, never a bypass of typed admission.
        append_project_events(repo=self.repo, events=self.specs[:1])
        state = ensure_state(self.repo)
        event = read_project_events(self.path)[0]
        event["provenance"][KEY] = PROFILE
        event["payload"]["changed_files"] = [False]
        event["event_id"] = _event_id(event)
        event["event_hash"] = _event_hash(event)
        raw = (_canonical(event) + "\n").encode()
        self.path.write_bytes(raw)
        for reader in (lambda: read_project_events(self.path), lambda: _parse(raw)):
            with self.assertRaises(ContinuityError):
                reader()
        with contextlib.closing(sqlite3.connect(state)) as conn:
            conn.execute("delete from meta where key like '%file_sha256%'")
            conn.execute("insert into meta(key,value) values(?,?)", (
                "declaration_profile_event_file_sha256", hashlib.sha256(raw).hexdigest()))
            conn.commit()
        with self.assertRaises(ContinuityError):
            compile_context(self.repo, "refund", refresh_structure=False)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_descriptor_advertises_profile_without_new_proof_authority(self):
        profile = project_memory_contract()["admission_profiles"][PROFILE]
        self.assertEqual(set(profile["event_types"]), {e["event_type"] for e in self.specs})
        self.assertFalse(profile["grants_proof_authority"])
        profile["event_types"].clear()
        self.assertEqual(len(project_memory_contract()["admission_profiles"][PROFILE]["event_types"]), 5)


if __name__ == "__main__":
    unittest.main()
