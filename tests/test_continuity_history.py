from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import test_continuity_kernel as fixtures
from diffwitness import continuity_events as journal
from diffwitness.continuity_cli import state_cli
from diffwitness.continuity_history import (MAX_HISTORY_BYTES, entity_history, why_entity,
                                           event_detail, render_history, render_why)
from diffwitness.continuity_lifecycle import lifecycle_spec
from diffwitness.language import presentation


class MemoryNavigationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temp.name))
        self.paths = journal.continuity_paths(self.repo)

    def record(self, identity, *, label=None, payload=None, relations=None, status="DECLARED", kind="objective"):
        event, _ = journal.append_project_event(
            repo=self.repo, event_type="objective.declared",
            subject={"id": identity, "kind": kind, "label": label or identity},
            epistemic_status=status, payload=payload or {}, relations=relations or [],
            provenance={"producer": "navigation-fixture"}, actor={"kind": "human", "id": "fixture"})
        return event

    def relation(self, source, target, *, predicate="related_to", note="Declared connection", status="DECLARED"):
        return journal.append_project_event(
            repo=self.repo, event_type="relation.declared", subject={"id": source, "kind": "objective"},
            epistemic_status=status, payload={},
            relations=[{"predicate": predicate, "target": {"id": target, "kind": "objective"},
                        "epistemic_status": status, "metadata": {"note": note, "basis": "synthetic-fixture"}}],
            provenance={"producer": "navigation-fixture"}, actor={"kind": "human", "id": "fixture"})[0]

    def test_history_retains_exact_events_and_pages_a_stable_prefix_across_appends(self):
        first = self.record("OBJ-A", payload={"why": "Première raison"})
        self.record("OBJ-B")
        second = self.record("OBJ-A", payload={"why": "Deuxième raison"})
        third = self.record("OBJ-A", payload={"why": "Troisième raison"})
        raw = self.paths.events.read_bytes()
        page = entity_history(self.repo, "OBJ-A", limit=2)
        self.assertEqual([item["event"] for item in page["events"]], [third, second])
        self.assertTrue(page["hasMore"])
        self.assertEqual(page["anchor"]["eventCount"], 4)
        self.assertEqual(raw, self.paths.events.read_bytes())
        later = self.record("OBJ-A")
        next_page = entity_history(self.repo, "OBJ-A", limit=2, cursor=page["nextCursor"])
        self.assertEqual([item["event"] for item in next_page["events"]], [first])
        self.assertEqual(next_page["anchor"], page["anchor"])
        self.assertEqual(next_page["validatedJournal"]["eventCount"], 5)
        self.assertFalse(next_page["hasMore"])
        self.assertIsNone(next_page["nextCursor"])
        self.assertEqual(entity_history(self.repo, "OBJ-A")["events"][0]["event"], later)
        self.assertFalse(self.paths.state.exists(), "navigation must not create a derived database")

    def test_cursor_rejects_wrong_identity_truncation_and_valid_divergent_prefix(self):
        self.record("OBJ-A"); self.record("OBJ-A")
        page = entity_history(self.repo, "OBJ-A", limit=1)
        cursor = page["nextCursor"]
        for invalid in ("", "@not-base64", cursor + "=", "x" * 2049):
            with self.subTest(cursor=invalid[:20]), self.assertRaises(journal.ContinuityError):
                entity_history(self.repo, "OBJ-A", cursor=invalid)
        with self.assertRaises(journal.ContinuityError):
            entity_history(self.repo, "OBJ-B", cursor=cursor)
        events = journal.read_project_events(self.paths.events)
        self.paths.events.write_bytes((journal._canonical(events[0]) + "\n").encode())
        with self.assertRaises(journal.ContinuityError):
            entity_history(self.repo, "OBJ-A", cursor=cursor)
        previous = None
        for event in events:
            event["payload"] = {"why": "Different valid history"}
            event["prev_hash"] = previous
            event["event_id"] = journal._event_id(event)
            event["event_hash"] = journal._event_hash(event)
            previous = event["event_hash"]
        self.paths.events.write_bytes("".join(journal._canonical(e) + "\n" for e in events).encode())
        self.assertEqual(len(journal.read_project_events(self.paths.events)), 2)
        with self.assertRaises(journal.ContinuityError):
            entity_history(self.repo, "OBJ-A", cursor=cursor)

    def test_exact_citation_opens_original_event_and_rejects_wrong_hash_or_missing_id(self):
        original = self.record("OBJ-A", payload={"why": "Citation exacte"})
        result = event_detail(self.repo, original["event_id"], expected_hash=original["event_hash"])
        self.assertEqual(result["event"], original)
        self.assertEqual(result["sequence"], 1)
        for identity, digest in ((original["event_id"], "0" * 64), ("dwev_" + "0" * 24, None)):
            with self.subTest(identity=identity), self.assertRaises(journal.ContinuityError):
                event_detail(self.repo, identity, expected_hash=digest)
        for identity, digest in (("invalid", None), (original["event_id"], "bad")):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                event_detail(self.repo, identity, expected_hash=digest)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(state_cli(["event", original["event_id"], "--hash", original["event_hash"],
                                        "--repo", str(self.repo), "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["event"], original)

    def test_history_byte_bound_preserves_whole_events_and_all_pages(self):
        originals = [self.record("OBJ-LARGE", payload={"why": "é" * 100000}) for _ in range(7)]
        cursor, collected = None, []
        while True:
            page = entity_history(self.repo, "OBJ-LARGE", limit=200, cursor=cursor)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()), MAX_HISTORY_BYTES)
            collected.extend(item["event"] for item in page["events"])
            cursor = page["nextCursor"]
            if cursor is None:
                break
        self.assertEqual(collected, list(reversed(originals)))

    def test_why_traverses_both_directions_and_preserves_separate_authorities_and_reasons(self):
        a = self.record("OBJ-A", payload={"why": "Préserver les remboursements"})
        b = self.record("OBJ-B", status="OBSERVED")
        self.record("OBJ-C", status="INFERRED")
        incoming = self.relation("OBJ-A", "OBJ-B", predicate="motivates", note="Intention explicite")
        outgoing = self.relation("OBJ-B", "OBJ-C", predicate="constrains", status="OBSERVED")
        self.relation("OBJ-C", "OBJ-A")
        result = why_entity(self.repo, "OBJ-B")
        nodes = {node["id"]: node for node in result["nodes"]}
        self.assertEqual(set(nodes), {"OBJ-A", "OBJ-B", "OBJ-C"})
        self.assertEqual(nodes["OBJ-A"]["source"]["eventHash"], a["event_hash"])
        self.assertEqual(nodes["OBJ-A"]["epistemicStatus"], "DECLARED")
        self.assertEqual(nodes["OBJ-B"]["source"]["eventId"], b["event_id"])
        self.assertEqual(nodes["OBJ-C"]["epistemicStatus"], "INFERRED")
        edges = {edge["predicate"]: edge for edge in result["relationships"]}
        self.assertEqual(edges["motivates"]["source"]["eventHash"], incoming["event_hash"])
        self.assertEqual(edges["motivates"]["reason"]["text"], "Intention explicite")
        self.assertEqual(edges["constrains"]["source"]["eventId"], outgoing["event_id"])
        self.assertEqual(edges["constrains"]["epistemicStatus"], "OBSERVED")
        self.assertFalse(result["coverage"]["truncated"])
        self.assertIn("do not establish causal Proof", result["authority"])

    def test_latest_edge_is_selected_with_its_own_source_and_old_event_remains_in_history(self):
        self.record("OBJ-A"); self.record("OBJ-B")
        old = self.relation("OBJ-A", "OBJ-B", note="Old")
        latest = self.relation("OBJ-A", "OBJ-B", note="New", status="INFERRED")
        result = why_entity(self.repo, "OBJ-A")
        self.assertEqual(len(result["relationships"]), 1)
        edge = result["relationships"][0]
        self.assertEqual(edge["source"]["eventId"], latest["event_id"])
        self.assertEqual(edge["epistemicStatus"], "INFERRED")
        self.assertEqual(edge["reason"]["text"], "New")
        self.assertIn(old, [item["event"] for item in entity_history(self.repo, "OBJ-A")["events"]])

    def test_review_does_not_replace_assertion_and_inactive_memory_stays_explicit(self):
        assertion = self.record("OBJ-A", payload={"why": "Original reason"})
        self.record("OBJ-B")
        self.relation("OBJ-A", "OBJ-B")
        review = journal.append_project_events(repo=self.repo, events=[
            lifecycle_spec(self.repo, "objective", "OBJ-A", "retire", "No longer applies")])[0][0]
        node = next(node for node in why_entity(self.repo, "OBJ-B")["nodes"] if node["id"] == "OBJ-A")
        self.assertEqual(node["source"]["eventHash"], assertion["event_hash"])
        self.assertEqual(node["reason"]["text"], "Original reason")
        self.assertEqual(node["applicability"]["source"]["eventHash"], review["event_hash"])
        self.assertFalse(node["applicability"]["active"])
        self.assertEqual(node["epistemicStatus"], "DECLARED")
        self.assertIn("Inactive memory", render_why(why_entity(self.repo, "OBJ-A")))

    def test_bounds_cycles_unknown_nodes_and_repeated_calls_are_deterministic(self):
        self.record("OBJ-A")
        for identity in ("OBJ-B", "OBJ-C", "OBJ-D"):
            self.relation("OBJ-A", identity)
        self.relation("OBJ-D", "OBJ-A")
        first = why_entity(self.repo, "OBJ-A", max_nodes=2)
        self.assertEqual(first, why_entity(self.repo, "OBJ-A", max_nodes=2))
        self.assertEqual(len(first["nodes"]), 2)
        self.assertTrue(first["coverage"]["truncated"])
        self.assertFalse(first["nodes"][1]["hasRecordedAssertion"])
        self.assertIsNone(first["nodes"][1]["epistemicStatus"])
        limited = why_entity(self.repo, "OBJ-A", max_edges=1)
        self.assertEqual(len(limited["relationships"]), 1)
        self.assertTrue(limited["coverage"]["truncated"])
        for options in ({"depth": 0}, {"depth": 5}, {"max_nodes": True}, {"max_edges": 201}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                why_entity(self.repo, "OBJ-A", **options)
        for limit in (0, 201, True):
            with self.assertRaises(ValueError):
                entity_history(self.repo, "OBJ-A", limit=limit)

    def test_corrupt_journal_cannot_supply_history_or_reasons(self):
        self.record("OBJ-A")
        raw = self.paths.events.read_bytes().replace(b'"epistemic_status":"DECLARED"',
            b'"epistemic_status":"VERIFIED","epistemic_status":"DECLARED"')
        self.paths.events.write_bytes(raw)
        for operation in (entity_history, why_entity):
            with self.subTest(operation=operation.__name__), self.assertRaises(journal.ContinuityError):
                operation(self.repo, "OBJ-A")
        self.assertEqual(self.paths.events.read_bytes(), raw)
        self.assertFalse(self.paths.state.exists())

    def test_depth_and_reason_truncation_are_explicit(self):
        self.record("OBJ-A", payload={"why": "R" * 2100})
        self.relation("OBJ-A", "OBJ-B", note="N" * 2100)
        self.relation("OBJ-B", "OBJ-C")
        result = why_entity(self.repo, "OBJ-A", depth=1)
        self.assertEqual({node["id"] for node in result["nodes"]}, {"OBJ-A", "OBJ-B"})
        self.assertTrue(result["coverage"]["truncated"])
        self.assertTrue(result["nodes"][0]["reason"]["truncated"])
        self.assertTrue(result["relationships"][0]["reason"]["truncated"])
        self.assertEqual(len(result["relationships"][0]["reason"]["text"]), 2000)
        self.assertIn("shortened", render_why(result))
        self.assertEqual(entity_history(self.repo, "OBJ-A")["events"][0]["event"]["relations"][0]["metadata"]["note"], "N" * 2100)

    def test_empty_history_and_unknown_identity_are_explicit_without_persistence(self):
        self.assertFalse(entity_history(self.repo, "OBJ-UNKNOWN")["events"])
        result = why_entity(self.repo, "OBJ-UNKNOWN")
        self.assertFalse(result["nodes"][0]["hasRecordedAssertion"])
        self.assertEqual(result["relationships"], [])
        self.assertFalse(self.paths.root.exists())

    def test_public_cli_rejects_non_repository_without_traceback_or_files(self):
        with tempfile.TemporaryDirectory() as empty:
            for command in ("history", "why"):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    self.assertEqual(state_cli([command, "OBJ-A", "--repo", empty]), 2)
                self.assertEqual(out.getvalue(), "")
                self.assertIn("Memory navigation rejected", err.getvalue())
                self.assertNotIn("Traceback", err.getvalue())
            self.assertEqual(list(Path(empty).iterdir()), [])

    def test_public_cli_json_and_french_text_are_read_only_and_escape_recorded_controls(self):
        event = self.record("OBJ-A", label="Safe\n\x1b[2J\u202e\u2028 title", payload={"why": "Raison sûre"})
        raw = self.paths.events.read_bytes()
        for command in ("history", "why"):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = state_cli([command, "OBJ-A", "--repo", str(self.repo), "--json"])
            self.assertEqual(rc, 0, err.getvalue())
            self.assertIn(event["event_hash"], out.getvalue())
            json.loads(out.getvalue())
            out = io.StringIO()
            with presentation("fr"), redirect_stdout(out):
                self.assertEqual(state_cli([command, "OBJ-A", "--repo", str(self.repo)]), 0)
            self.assertIn("enregistr", out.getvalue())
            self.assertNotIn("\x1b", out.getvalue())
            self.assertNotIn("\u202e", out.getvalue())
            self.assertNotIn("\u2028", out.getvalue())
        self.assertEqual(self.paths.events.read_bytes(), raw)
        self.assertFalse(self.paths.state.exists())


if __name__ == "__main__":
    unittest.main()
