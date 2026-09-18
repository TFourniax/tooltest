from __future__ import annotations
import tempfile
import unittest
import random
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness import continuity_context as context
from diffwitness.continuity_events import append_project_events
from diffwitness.continuity_state import rebuild_state


class IndexedContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temporary.name))

    def spec(self, identity, label=None, kind="objective", payload=None, relations=None):
        return {"event_type": kind + ".declared", "subject": {"id": identity, "kind": kind, **({"label": label} if label else {})},
                "epistemic_status": "DECLARED", "payload": payload or {}, "relations": relations or [],
                "provenance": {"producer": "fixture"}, "actor": {"kind": "human", "id": "fixture"}}

    def test_selective_query_does_not_decode_thousands_of_unrelated_entities(self):
        events = [self.spec(f"OBJ-{i:04d}", f"Historical unrelated work {i}") for i in range(1500)]
        events.append(self.spec("OBJ-REFUND", "Refund idempotency"))
        append_project_events(repo=self.repo, events=events)
        rebuild_state(self.repo)
        with patch.object(context, "_entity_text", wraps=context._entity_text) as decode:
            result = context.compile_context(self.repo, "refund idempotency", refresh_structure=False)
        self.assertEqual([item["id"] for item in result["objectives"]], ["OBJ-REFUND"])
        self.assertLessEqual(decode.call_count, 4, "unrelated history must not be decoded to answer a selective query")

    def test_complete_two_hop_graph_critical_and_component_seeds_survive_selection(self):
        from diffwitness.structure_provider import component_id_for_path
        relation = lambda target: {"predicate": "related_to", "target": {"id": target, "kind": "decision"}}
        events = [self.spec("OBJ-SEED", "Zebra refund", relations=[relation("DEC-HOP1")]),
                  self.spec("DEC-HOP1", "Unrelated first hop", "decision", relations=[relation("DEC-HOP2")]),
                  self.spec("DEC-HOP2", "Unrelated second hop", "decision", relations=[relation("DEC-HOP3")]),
                  self.spec("DEC-HOP3", "Unrelated third hop", "decision"),
                  self.spec("INV-CRITICAL", "Always applicable policy", "invariant", {"critical": True}),
                  self.spec("DEC-COMPONENT", "Code-bound choice", "decision", relations=[{
                      "predicate": "affects", "target": {"id": component_id_for_path("payments/refund.py"), "kind": "component"}}])]
        append_project_events(repo=self.repo, events=events)
        result = context.compile_context(self.repo, "zebra refund", refresh_structure=True)
        decisions = {item["id"]: item for item in result["decisions"]}
        self.assertEqual(decisions["DEC-HOP1"]["relationDepth"], 1)
        self.assertEqual(decisions["DEC-HOP2"]["relationDepth"], 2)
        self.assertNotIn("DEC-HOP3", decisions)
        self.assertIn("DEC-COMPONENT", decisions)
        self.assertIn("INV-CRITICAL", [item["id"] for item in result["invariants"]])

    def test_changed_payload_removes_stale_terms_but_inherited_label_remains_searchable(self):
        append_project_events(repo=self.repo, events=[self.spec("OBJ-ONE", "Persistent label", payload={"why": "oldtoken"})])
        rebuild_state(self.repo)
        append_project_events(repo=self.repo, events=[self.spec("OBJ-ONE", payload={"why": "newtoken"})])
        self.assertFalse(context.compile_context(self.repo, "oldtoken", refresh_structure=False)["objectives"])
        self.assertEqual(context.compile_context(self.repo, "newtoken", refresh_structure=False)["objectives"][0]["id"], "OBJ-ONE")
        self.assertEqual(context.compile_context(self.repo, "Persistent", refresh_structure=False)["objectives"][0]["id"], "OBJ-ONE")

    def test_exact_short_id_and_short_component_seed_do_not_depend_on_lexical_tokens(self):
        from diffwitness.structure_provider import component_id_for_path
        append_project_events(repo=self.repo, events=[self.spec("X", "Alpha"), self.spec("Y", "Other", relations=[{
            "predicate": "affects", "target": {"id": component_id_for_path("payments/refund.py"), "kind": "component"}}])])
        result = context.compile_context(self.repo, "X", refresh_structure=False)
        self.assertEqual(result["objectives"][0]["id"], "X")
        self.assertEqual(result["objectives"][0]["relevanceReason"], "exact-entity-id")

    def test_indexed_retrieval_matches_full_scan_on_mixed_graph(self):
        rng = random.Random(1248)
        kinds = ("objective", "decision", "invariant", "failed-approach", "task")
        events = []
        for index in range(90):
            relations = [{"predicate": "related_to", "target": {"id": f"MEM-{target}", "kind": kinds[target % 5]}}
                         for target in rng.sample(range(90), 3)]
            events.append(self.spec(f"MEM-{index}", f"Topic{index % 13} item {index}", kinds[index % 5],
                                    {"why": f"intent{index % 17}", "critical": index == 2}, relations))
        append_project_events(repo=self.repo, events=events)
        state = rebuild_state(self.repo)
        with closing(sqlite3.connect(state)) as conn:
            conn.row_factory = sqlite3.Row
            all_rows = conn.execute("select e.*,m.lifecycle_json from entities e left join memory_lifecycle m on m.entity_id=e.entity_id where e.lifecycle='active' order by e.updated_at desc").fetchall()
            all_edges = conn.execute("select * from active_memory_relations order by updated_at desc").fetchall()
            for query in ("Topic3", "intent7", "MEM-81", "no matching words", ""):
                with self.subTest(query=query):
                    indexed = context._relevant_entities(conn, query, 90, seed_component_ids=["MEM-80"])
                    with patch.object(context, "select_context_entities", return_value=all_rows), patch.object(context, "_semantic_relations", return_value=all_edges):
                        exhaustive = context._relevant_entities(conn, query, 90, seed_component_ids=["MEM-80"])
                    self.assertEqual(indexed, exhaustive)
                    with patch.object(context, "select_context_entities", return_value=list(reversed(all_rows))), patch.object(context, "_semantic_relations", return_value=list(reversed(all_edges))):
                        reordered = context._relevant_entities(conn, query, 90, seed_component_ids=["MEM-80"])
                    compact = lambda items: [(item['id'],item['relevance'],item['relationDepth'],item['relevanceReason']) for item in items]
                    self.assertEqual(compact(exhaustive), compact(reordered), "retrieval must not depend on row/edge iteration order")


if __name__ == "__main__":
    unittest.main()
