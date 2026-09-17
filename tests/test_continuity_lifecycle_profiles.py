from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_continuity_debt_bridge as fixtures

from diffwitness.continuity_contract import project_memory_contract
from diffwitness.continuity_context import compile_context
from diffwitness.continuity_debt_bridge import _spec, sync_debt_history
from diffwitness.continuity_events import (
    ContinuityError, _canonical, _event_hash, _event_id, append_project_events,
    continuity_paths, read_project_events,
)
from diffwitness.continuity_relation_cli import relation_cli
from diffwitness.continuity_state import ensure_state, rebuild_state
from diffwitness.continuity_transport import _parse, _serialize
from diffwitness.ledger import DebtLedger

KEY = "diffwitness_profile"
LEDGER = "project-memory-debt-lifecycle-1"
RELATION = "project-memory-relation-1"


class LifecycleProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        fixture = fixtures.ContinuityDebtBridgeTests()
        self.repo, base, candidate, tree = fixture.repo(Path(temp.name))
        self.report, self.signal = fixture.report(self.repo, base, candidate, tree)
        self.ledger = DebtLedger.load(self.repo / ".git" / "diffwitness" / "debt-ledger.jsonl")
        self.ledger.record_report(self.report)
        self.path = continuity_paths(self.repo).events

    def lifecycle(self):
        self.signal.title = "Updated bounded title"
        self.ledger.record_report(self.report)
        self.ledger.accept(self.signal.debt_id, reason="Known tradeoff", actor="user")
        self.ledger.unaccept(self.signal.debt_id, actor="user")
        self.ledger.resolve(self.signal.debt_id, reason="Test added", verification={"result": "absent"})
        self.ledger.record_report(self.report)

    def typed(self):
        specs = [_spec(self.repo, event) for event in self.ledger.events]
        for spec in specs:
            spec["provenance"][KEY] = LEDGER
        return specs

    def declarations(self):
        return append_project_events(repo=self.repo, events=[{
            "event_type": "objective.declared",
            "subject": {"id": identity, "kind": "objective", "label": identity},
            "epistemic_status": status, "payload": {"why": "Original assertion"},
            "provenance": {"producer": "fixture", "source": "legacy"},
        } for identity, status in (("OBJ-SOURCE", "VERIFIED"), ("OBJ-TARGET", "DECLARED"))])

    def relation(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return relation_cli(["add", "OBJ-SOURCE", "related_to", "OBJ-TARGET", "--repo", str(self.repo)])

    def relation_spec(self):
        source = self.declarations()[0][0]
        return {
            "event_type": "relation.declared", "subject": source["subject"],
            "epistemic_status": "DECLARED", "payload": source["payload"],
            "relations": [{"predicate": "related_to", "target": {"id": "OBJ-TARGET", "kind": "objective", "label": "OBJ-TARGET"},
                           "epistemic_status": "DECLARED", "metadata": {"basis": "human-declaration"}}],
            "provenance": {"producer": "diffwitness", "source": "human-cli", "preserves_entity_from_event": source["event_id"]},
            "actor": {"kind": "human", "id": "local-user"},
            "dedupe_key": "relation:OBJ-SOURCE:related_to:OBJ-TARGET",
        }

    def test_real_six_state_lifecycle_is_profiled_idempotent_and_replayable(self):
        self.lifecycle()
        self.assertEqual(sync_debt_history(self.repo)["created"], 6)
        events = read_project_events(self.path)
        self.assertEqual([e["event_type"] for e in events], ["debt." + name for name in (
            "introduced", "refreshed", "accepted", "unaccepted", "resolved", "reopened")])
        self.assertTrue(all(e["provenance"].get(KEY) == LEDGER for e in events))
        self.assertEqual([e["epistemic_status"] for e in events], ["OBSERVED", "OBSERVED", "DECLARED", "DECLARED", "OBSERVED", "OBSERVED"])
        before = self.path.read_bytes()
        self.assertEqual(sync_debt_history(self.repo)["created"], 0)
        self.assertEqual(_parse(_serialize(events)), events)
        state = rebuild_state(self.repo)
        with contextlib.closing(sqlite3.connect(state)) as conn:
            self.assertEqual(conn.execute("select status,accepted,points from debts").fetchone(), ("open", 0, 3))
        self.assertEqual(self.path.read_bytes(), before)

    def test_native_legacy_ledger_reimport_preserves_every_original_byte(self):
        self.lifecycle()
        legacy = self.typed()
        for event in legacy:
            event["provenance"].pop(KEY)
        original = append_project_events(repo=self.repo, events=legacy)
        before = self.path.read_bytes()
        self.assertEqual(sync_debt_history(self.repo)["created"], 0)
        self.assertEqual(read_project_events(self.path), [event for event, _ in original])
        self.assertEqual(self.path.read_bytes(), before)
        self.path.unlink()
        original = append_project_events(repo=self.repo, events=self.typed())
        before = self.path.read_bytes()
        self.assertEqual(append_project_events(repo=self.repo, events=legacy), [(e, False) for e, _ in original])
        self.assertEqual(self.path.read_bytes(), before)

    def test_public_relation_preserves_source_authority_and_payload(self):
        source = self.declarations()[0][0]
        self.assertEqual(self.relation(), 0)
        event = read_project_events(self.path)[-1]
        self.assertEqual(event["provenance"].get(KEY), RELATION)
        self.assertEqual(event["epistemic_status"], "DECLARED")
        before = self.path.read_bytes()
        self.assertEqual(self.relation(), 0)
        with contextlib.closing(sqlite3.connect(ensure_state(self.repo))) as conn:
            row = conn.execute("select epistemic_status,payload_json,source_event_id from entities where entity_id='OBJ-SOURCE'").fetchone()
            self.assertEqual(row, ("VERIFIED", _canonical(source["payload"]), source["event_id"]))
            self.assertEqual(conn.execute("select epistemic_status from relations").fetchone()[0], "DECLARED")
        self.assertEqual(self.path.read_bytes(), before)

    def test_native_legacy_relation_reimport_is_immutable(self):
        spec = self.relation_spec()
        original = append_project_events(repo=self.repo, events=[spec])[0][0]
        before = self.path.read_bytes()
        self.assertEqual(self.relation(), 0)
        self.assertEqual(read_project_events(self.path)[-1], original)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_profiled_ledger_batch_cannot_append_or_promote_authority(self):
        self.lifecycle()
        typed = self.typed()
        cases = (
            (0, lambda e: e["subject"].update(kind="change")),
            (0, lambda e: e["provenance"].update(legacy_event_hash="z" * 64)),
            (0, lambda e: e.update(dedupe_key="legacy-debt:" + "a" * 64)),
            (0, lambda e: e["payload"].update(legacy_event_type="resolved")),
            (0, lambda e: e["payload"]["signal"].update(line=True)),
            (0, lambda e: e["payload"]["signal"].update(points=3.0)),
            (0, lambda e: e["payload"]["signal"].update(title=42)),
            (0, lambda e: e["relations"][0]["target"].update(id="dwchg_wrong")),
            (0, lambda e: e["relations"][0].update(epistemic_status="VERIFIED")),
            (0, lambda e: e["actor"].update(id=42)),
            (2, lambda e: e["payload"].update(reason=42)),
            (2, lambda e: e.update(epistemic_status="OBSERVED")),
            (4, lambda e: e["payload"].update(forced="false")),
            (4, lambda e: e.update(epistemic_status="VERIFIED")),
        )
        for index, mutate in cases:
            with self.subTest(index=index, mutate=mutate):
                invalid = copy.deepcopy(typed[index])
                mutate(invalid)
                with self.assertRaises(ContinuityError):
                    append_project_events(repo=self.repo, events=[typed[1], invalid])
                self.assertFalse(self.path.exists())

    def test_malformed_consumed_ledger_values_are_rejected_before_projection(self):
        base = copy.deepcopy(self.ledger.events)
        cases = (
            ("accepted", {"reason": 42}),
            ("resolved", {"reason": "done", "forced": "false"}),
            ("refreshed", {"signal": self.signal.to_dict(), "report": {"base_sha": False, "candidate_tree": "abc"}}),
            ("refreshed", {"signal": {**self.signal.to_dict(), "line": True}}),
            ("refreshed", {"signal": {**self.signal.to_dict(), "title": 42}}),
        )
        for event_type, payload in cases:
            with self.subTest(event_type=event_type, payload=payload):
                self.path.unlink(missing_ok=True)
                self.ledger.path.unlink(missing_ok=True)
                self.ledger = DebtLedger(self.ledger.path, copy.deepcopy(base))
                self.ledger.append(event_type=event_type, debt_id=self.signal.debt_id, payload=payload)
                with self.assertRaises(ContinuityError):
                    sync_debt_history(self.repo)
                self.assertFalse(self.path.exists())

    def test_missing_historical_git_object_and_zero_points_preserve_absence(self):
        event = copy.deepcopy(self.ledger.events[0])
        event["payload"]["report"]["base_sha"] = "0" * 40
        event["payload"]["signal"].update(points=0, path=None, line=None)
        spec = _spec(self.repo, event)
        spec["provenance"][KEY] = LEDGER
        stored = append_project_events(repo=self.repo, events=[spec])[0][0]
        self.assertIsNone(stored["payload"]["change_id"])
        self.assertEqual(stored["relations"], [])
        self.assertEqual(stored["payload"]["signal"]["points"], 0)
        self.assertNotIn("line", stored["payload"]["signal"])

    def test_relation_profile_rejects_promotion_missing_provenance_and_invalid_edges(self):
        spec = self.relation_spec()
        spec["provenance"][KEY] = RELATION
        before = self.path.read_bytes()
        for mutate in (
            lambda e: e.update(epistemic_status="VERIFIED"),
            lambda e: e["provenance"].pop("preserves_entity_from_event"),
            lambda e: e["provenance"].update(source="change-envelope"),
            lambda e: e.update(relations=[]),
            lambda e: e["relations"][0].update(predicate="proves"),
            lambda e: e["relations"][0].update(epistemic_status="VERIFIED"),
            lambda e: e["relations"][0]["metadata"].update(note=False),
            lambda e: e.update(dedupe_key="unrelated"),
        ):
            invalid = copy.deepcopy(spec)
            mutate(invalid)
            with self.subTest(mutate=mutate), self.assertRaises(ContinuityError):
                append_project_events(repo=self.repo, events=[invalid])
            self.assertEqual(self.path.read_bytes(), before)

    def test_profile_adoption_does_not_mask_real_ledger_or_relation_conflicts(self):
        ledger = self.typed()[0]
        relation = self.relation_spec()
        relation["provenance"][KEY] = RELATION
        for spec in (ledger, relation):
            legacy = copy.deepcopy(spec)
            legacy["provenance"].pop(KEY)
            append_project_events(repo=self.repo, events=[legacy])
            before = self.path.read_bytes()
            changed = copy.deepcopy(spec)
            changed["payload"]["extension"] = "real change"
            with self.assertRaises(ContinuityError):
                append_project_events(repo=self.repo, events=[changed])
            self.assertEqual(self.path.read_bytes(), before)

    def test_readers_checkpoints_and_old_cache_reject_hash_valid_invalid_profile(self):
        spec = self.typed()[0]
        spec["provenance"].pop(KEY)
        append_project_events(repo=self.repo, events=[spec])
        state = ensure_state(self.repo)
        event = read_project_events(self.path)[0]
        event["provenance"][KEY] = LEDGER
        event["epistemic_status"] = "VERIFIED"
        event["event_id"] = _event_id(event)
        event["event_hash"] = _event_hash(event)
        raw = (_canonical(event) + "\n").encode()
        self.path.write_bytes(raw)
        for reader in (lambda: read_project_events(self.path), lambda: _parse(raw)):
            with self.assertRaises(ContinuityError):
                reader()
        with contextlib.closing(sqlite3.connect(state)) as conn:
            conn.execute("delete from meta where key like '%file_sha256%'")
            conn.execute("insert into meta(key,value) values(?,?)", ("artifact_profile_event_file_sha256", hashlib.sha256(raw).hexdigest()))
            conn.commit()
        with self.assertRaises(ContinuityError):
            compile_context(self.repo, "refund", refresh_structure=False)

    def test_contract_exposes_both_profiles_without_proof_authority(self):
        profiles = project_memory_contract()["admission_profiles"]
        self.assertEqual(len(profiles[LEDGER]["event_types"]), 6)
        self.assertEqual(list(profiles[RELATION]["event_types"]), ["relation.declared"])
        for name in (LEDGER, RELATION):
            self.assertFalse(profiles[name]["grants_proof_authority"])
            profiles[name]["event_types"].clear()
            self.assertTrue(project_memory_contract()["admission_profiles"][name]["event_types"])


if __name__ == "__main__":
    unittest.main()
