from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_continuity_kernel as fixtures
from diffwitness.continuity_events import append_project_event, append_project_events, continuity_paths, read_project_events, ContinuityError, _event_id, _event_hash
from diffwitness.continuity_context_enriched import compile_context
from diffwitness.continuity_state import ensure_state, rebuild_state
from diffwitness.continuity_transport import _parse, _serialize


class MemoryLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temp.name))
        self.path = continuity_paths(self.repo).events

    def declare(self, identity, kind="decision", status="DECLARED", relations=None):
        prefix = "approach" if kind == "failed-approach" else kind
        suffix = {"decision": "recorded", "failed-approach": "failed"}.get(kind, "declared")
        return append_project_event(repo=self.repo, event_type=f"{prefix}.{suffix}",
            subject={"id": identity, "kind": kind, "label": "Refund " + identity},
            epistemic_status=status, payload={"why": "Preserve idempotency", "critical": kind == "invariant"},
            relations=relations or [], provenance={"producer": "legacy-fixture"}, actor={"kind": "human", "id": "tester"})[0]

    def cli(self, kind, *args, expected=0):
        result = subprocess.run([sys.executable, "-m", "diffwitness.entry", kind, *args,
                                 "--repo", str(self.repo), "--json"], text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if expected == 0 else result

    def test_all_four_kinds_confirm_retire_and_reconsider_preserve_assertion(self):
        for kind in ("objective", "decision", "invariant", "failed-approach"):
            with self.subTest(kind=kind):
                identity = "MEM-" + kind
                original = self.declare(identity, kind)
                self.cli(kind, "confirm", identity, "--reason", "Reviewed against current needs")
                shown = self.cli(kind, "show", identity)
                self.assertEqual(shown["assertion"]["event_id"], original["event_id"])
                self.assertEqual(shown["lifecycle"]["action"], "confirmed")
                self.assertEqual(shown["lifecycle"]["epistemicStatus"], "DECLARED")
                self.cli(kind, "retire", identity, "--reason", "No longer applicable")
                self.assertFalse(self.cli(kind, "show", identity)["lifecycle"]["active"])
                self.cli(kind, "confirm", identity, "--reason", "Applicable again after review")
                self.assertTrue(self.cli(kind, "show", identity)["lifecycle"]["active"])
        self.assertEqual(_parse(_serialize(read_project_events(self.path))), read_project_events(self.path))

    def test_rejected_memory_and_edges_do_not_seed_context_but_history_remains(self):
        self.declare("INV-LIMIT", "invariant", relations=[{"predicate": "related_to", "target": {"id": "DEC-KEEP", "kind": "decision"}}])
        self.declare("DEC-KEEP")
        self.cli("invariant", "reject", "INV-LIMIT", "--reason", "The assumption was incorrect")
        context = compile_context(self.repo, "Refund", refresh_structure=False)
        self.assertNotIn("INV-LIMIT", [x["id"] for x in context["invariants"]])
        self.assertFalse(any(x["source"] == "INV-LIMIT" or x["target"] == "INV-LIMIT" for x in context["relations"]))
        shown = self.cli("invariant", "show", "INV-LIMIT")
        self.assertEqual(shown["lifecycle"]["action"], "rejected")
        self.assertEqual(shown["assertion"]["payload"]["why"], "Preserve idempotency")
        self.cli("invariant", "confirm", "INV-LIMIT", "--reason", "Reconsidered explicitly")
        self.assertIn("INV-LIMIT", [x["id"] for x in compile_context(self.repo, "Refund", refresh_structure=False)["invariants"]])

    def test_supersession_is_immutable_and_bidirectional_with_exact_replacement_reference(self):
        old = self.declare("DEC-OLD")
        new = self.declare("DEC-NEW")
        before = self.path.read_bytes()
        self.cli("decision", "supersede", "DEC-OLD", "--with", "DEC-NEW", "--reason", "Safer retry policy")
        self.assertTrue(self.path.read_bytes().startswith(before))
        shown = self.cli("decision", "show", "DEC-OLD")
        self.assertEqual(shown["assertion"], old)
        self.assertEqual(shown["lifecycle"]["replacementId"], "DEC-NEW")
        self.assertEqual(shown["lifecycle"]["replacementEventId"], new["event_id"])
        self.assertEqual(self.cli("decision", "show", "DEC-NEW")["supersedes"], ["DEC-OLD"])
        frozen = self.path.read_bytes()
        self.cli("decision", "confirm", "DEC-OLD", "--reason", "Cannot revive replaced identity", expected=2)
        self.cli("decision", "supersede", "DEC-NEW", "--with", "DEC-OLD", "--reason", "Cannot make a cycle", expected=2)
        self.assertEqual(self.path.read_bytes(), frozen)

    def test_invalid_replacements_and_unknown_kind_fail_without_partial_history(self):
        self.declare("DEC-ONE")
        self.declare("INV-ONE", "invariant")
        self.declare("DEC-RETIRED")
        self.cli("decision", "retire", "DEC-RETIRED", "--reason", "Expired")
        before = self.path.read_bytes()
        for replacement in ("DEC-ONE", "INV-ONE", "DEC-MISSING", "DEC-RETIRED"):
            self.cli("decision", "supersede", "DEC-ONE", "--with", replacement, "--reason", "Invalid replacement", expected=2)
        self.cli("objective", "confirm", "DEC-ONE", "--reason", "Wrong kind", expected=2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_stale_revision_is_rejected_atomically_and_source_cannot_be_overwritten(self):
        from diffwitness.continuity_lifecycle import lifecycle_spec
        self.declare("DEC-ONE")
        stale = lifecycle_spec(self.repo, "decision", "DEC-ONE", "retire", "Old review")
        self.cli("decision", "confirm", "DEC-ONE", "--reason", "New review")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ContinuityError, "revision"):
            append_project_events(repo=self.repo, events=[stale])
        with self.assertRaisesRegex(ContinuityError, "immutable"):
            self.declare("DEC-ONE")
        self.assertEqual(self.path.read_bytes(), before)

    def test_confirmation_does_not_promote_or_replace_original_assertion_authority(self):
        original = self.declare("INV-OBSERVED", "invariant", "OBSERVED")
        self.cli("invariant", "confirm", "INV-OBSERVED", "--reason", "Reviewed as policy")
        state = rebuild_state(self.repo)
        with contextlib.closing(sqlite3.connect(state)) as conn:
            row = conn.execute("select epistemic_status,payload_json,source_event_id from entities where entity_id='INV-OBSERVED'").fetchone()
        self.assertEqual(row[0], "OBSERVED")
        self.assertEqual(json.loads(row[1]), original["payload"])
        self.assertEqual(row[2], original["event_id"])
        context = compile_context(self.repo, "Refund", refresh_structure=False)
        self.assertEqual(context["invariants"][0]["lifecycle"]["epistemicStatus"], "DECLARED")

    def test_hash_valid_invalid_revision_is_rejected_by_checkpoint_and_old_cache(self):
        self.declare("DEC-ONE")
        self.cli("decision", "retire", "DEC-ONE", "--reason", "Reviewed")
        state = ensure_state(self.repo)
        events = read_project_events(self.path)
        events[-1]["payload"]["previous_revision_event_id"] = "dwev_" + "f" * 24
        events[-1]["event_id"] = _event_id(events[-1])
        events[-1]["event_hash"] = _event_hash(events[-1])
        raw = _serialize(events)
        self.path.write_bytes(raw)
        for reader in (lambda: read_project_events(self.path), lambda: _parse(raw), lambda: rebuild_state(self.repo)):
            with self.assertRaises(ContinuityError):
                reader()
        with contextlib.closing(sqlite3.connect(state)) as conn:
            conn.execute("delete from meta where key like '%file_sha256%'")
            conn.execute("insert into meta(key,value) values(?,?)", ("task_profile_event_file_sha256", hashlib.sha256(raw).hexdigest()))
            conn.commit()
        with self.assertRaises(ContinuityError):
            compile_context(self.repo, "Refund", refresh_structure=False)

    def test_profile_cannot_promote_judgment_or_smuggle_replacement_relations(self):
        from diffwitness.continuity_lifecycle import lifecycle_spec
        self.declare("DEC-ONE")
        spec = lifecycle_spec(self.repo, "decision", "DEC-ONE", "confirm", "Reviewed")
        before = self.path.read_bytes()
        for mutate in (lambda e: e.update(epistemic_status="VERIFIED"),
                       lambda e: e["payload"].update(reason=True),
                       lambda e: e["payload"].update(replacement_id="DEC-FAKE"),
                       lambda e: e["relations"].append({"predicate": "proves", "target": {"id": "DEC-ONE", "kind": "decision"}})):
            invalid = copy.deepcopy(spec)
            mutate(invalid)
            with self.assertRaises(ContinuityError):
                append_project_events(repo=self.repo, events=[invalid])
            self.assertEqual(self.path.read_bytes(), before)

    def test_public_redeclaration_of_managed_identity_is_a_controlled_rejection(self):
        self.declare("DEC-ONE")
        self.cli("decision", "confirm", "DEC-ONE", "--reason", "Reviewed")
        before = self.path.read_bytes()
        result = subprocess.run([sys.executable, "-m", "diffwitness.entry", "decision", "record", "Overwrite",
                                 "--id", "DEC-ONE", "--repo", str(self.repo)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("immutable", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.path.read_bytes(), before)

    def test_installed_presentations_retain_failed_approaches_and_distinct_review_authority(self):
        self.declare("FAIL-RETRY", "failed-approach", "OBSERVED")
        self.cli("failed-approach", "confirm", "FAIL-RETRY", "--reason", "Still relevant after review")
        json_results = []
        for language in ("en", "fr"):
            for view in ("guided", "technical"):
                for args in (("failed-approach", "show", "FAIL-RETRY"), ("context", "Refund", "--no-refresh-structure")):
                    result = subprocess.run([sys.executable, "-m", "diffwitness.entry", "--language", language,
                                             *args, "--repo", str(self.repo), "--view", view], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Refund FAIL-RETRY", result.stdout)
                    self.assertIn("OBSERVED", result.stdout)
                    self.assertIn("DECLARED", result.stdout)
                    self.assertIn("Still relevant after review", result.stdout)
            result = subprocess.run([sys.executable, "-m", "diffwitness.entry", "--language", language,
                                     "failed-approach", "show", "FAIL-RETRY", "--repo", str(self.repo), "--json"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            json_results.append(json.loads(result.stdout))
        self.assertEqual(json_results[0], json_results[1])


if __name__ == "__main__":
    unittest.main()
