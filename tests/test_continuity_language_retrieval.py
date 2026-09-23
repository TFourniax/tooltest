from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness.continuity_context import compile_context
from diffwitness.continuity_events import append_project_event, append_project_events, continuity_paths
from diffwitness.continuity_lifecycle import lifecycle_spec
from diffwitness.continuity_search import tokens
from diffwitness.continuity_state import STATE_SCHEMA, rebuild_state


class LanguageRetrievalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temporary.name))

    def record(self, label="Réinitialisation sécurisée", *, why="", status="DECLARED"):
        return append_project_event(
            repo=self.repo, event_type="decision.recorded",
            subject={"id": "DEC-LANGUAGE", "kind": "decision", "label": label},
            epistemic_status=status, payload={"why": why},
        )[0]

    def decisions(self, query):
        return compile_context(self.repo, query, refresh_structure=False)["decisions"]

    def test_ascii_token_behavior_is_preserved(self):
        self.assertEqual(tokens("HTTP_v2/getUser.py retry-safe 123 AB"),
                         {"http", "getuser", "retry", "safe", "123"})

    def test_french_accents_and_canonical_unicode_forms_recall_exact_assertion(self):
        for label in ("Réinitialisation sécurisée", "Re\u0301initialisation se\u0301curise\u0301e"):
            event = self.record(label, status="INFERRED")
            for query in ("reinitialisation", "RÉINITIALISATION", "re\u0301initialisation", "securisee"):
                with self.subTest(label=label, query=query):
                    items = self.decisions(query)
                    self.assertEqual(len(items), 1)
                    self.assertEqual(items[0]["label"], label)
                    self.assertEqual(items[0]["epistemicStatus"], "INFERRED")
                    self.assertEqual(items[0]["source"], {"kind": "project-event",
                        "eventId": event["event_id"], "eventHash": event["event_hash"]})

    def test_accented_query_matches_plain_label_and_french_ligatures(self):
        self.record("Controle des oeuvres et du coeur")
        self.assertEqual(len(self.decisions("contrôle")), 1)
        self.assertEqual(len(self.decisions("œuvres")), 1)
        self.assertEqual(len(self.decisions("cœur")), 1)

    def test_legacy_index_rebuilds_without_changing_the_journal(self):
        import re
        event = self.record()
        paths = continuity_paths(self.repo)
        before = paths.events.read_bytes()
        old_tokens = lambda value: {word.lower() for word in re.findall(r"[A-Za-z0-9]+", value or "") if len(word) >= 3}
        with patch("diffwitness.continuity_state.tokens", side_effect=old_tokens):
            rebuild_state(self.repo)
        with closing(sqlite3.connect(paths.state)) as conn:
            conn.execute("update meta set value='continuity-state-6' where key='schema'")
            conn.commit()
        items = self.decisions("reinitialisation")
        self.assertEqual([item["id"] for item in items], ["DEC-LANGUAGE"])
        self.assertEqual(items[0]["source"]["eventHash"], event["event_hash"])
        self.assertEqual(paths.events.read_bytes(), before)
        with closing(sqlite3.connect(paths.state)) as conn:
            self.assertEqual(conn.execute("select value from meta where key='schema'").fetchone()[0], STATE_SCHEMA)

    def test_replacement_removes_old_normalized_payload_terms(self):
        self.record("Choix", why="Réinitialisation")
        self.assertEqual(len(self.decisions("reinitialisation")), 1)
        latest = self.record("Choix", why="Archivage")
        self.assertEqual(self.decisions("reinitialisation"), [])
        self.assertEqual(self.decisions("archivage")[0]["source"]["eventId"], latest["event_id"])

    def test_retired_memory_is_not_revived_by_normalization(self):
        self.record()
        self.assertEqual(len(self.decisions("securisee")), 1)
        append_project_events(repo=self.repo, events=[
            lifecycle_spec(self.repo, "decision", "DEC-LANGUAGE", "retire", "Obsolete")])
        self.assertEqual(self.decisions("securisee"), [])

    def test_query_is_not_persisted_and_unrelated_query_has_no_match(self):
        self.record()
        paths = continuity_paths(self.repo)
        before = paths.events.read_bytes()
        secret_query = "QUESTION-PRIVEE-UNIQUE éphémère"
        self.assertEqual(self.decisions(secret_query), [])
        self.assertEqual(paths.events.read_bytes(), before)
        self.assertNotIn(secret_query.encode("utf-8"), paths.state.read_bytes())
        self.assertNotIn(b"ephemere", paths.state.read_bytes())

    def test_short_exact_id_keeps_literal_matching(self):
        append_project_event(repo=self.repo, event_type="decision.recorded",
            subject={"id": "X", "kind": "decision", "label": "Choix"}, epistemic_status="DECLARED")
        self.assertEqual(self.decisions("X")[0]["relevanceReason"], "exact-entity-id")
        self.assertEqual(self.decisions("x"), [])

    def test_normalized_terms_do_not_merge_distinct_identities_or_authorities(self):
        first = self.record("Côte", status="INFERRED")
        second = append_project_event(repo=self.repo, event_type="decision.recorded",
            subject={"id": "DEC-OTHER", "kind": "decision", "label": "Cote"},
            epistemic_status="DECLARED")[0]
        by_id = {item["id"]: item for item in self.decisions("cote")}
        self.assertEqual(set(by_id), {"DEC-LANGUAGE", "DEC-OTHER"})
        for event in (first, second):
            item = by_id[event["subject"]["id"]]
            self.assertEqual(item["source"]["eventId"], event["event_id"])
            self.assertEqual(item["epistemicStatus"], event["epistemic_status"])


if __name__ == "__main__":
    unittest.main()
