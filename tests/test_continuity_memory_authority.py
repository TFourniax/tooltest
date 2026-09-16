from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_context_enriched import compile_context
from diffwitness.continuity_events import append_project_event, continuity_paths, read_project_events
from diffwitness.continuity_state import STATE_SCHEMA, ensure_state, rebuild_state


class MemoryAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        for args in (("init", "-q"), ("config", "user.name", "Memory Test"),
                     ("config", "user.email", "memory@example.test")):
            self.run_command(["git", *args])
        (self.repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.run_command(["git", "add", "."])
        self.run_command(["git", "commit", "-qm", "baseline"])

    def run_command(self, args):
        proc = subprocess.run(args, cwd=self.repo, text=True, encoding="utf-8",
                              capture_output=True, timeout=180)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def dw(self, *args):
        return self.run_command([sys.executable, "-m", "diffwitness.entry", *args])

    def event(self, status, *, event_type="objective.declared", identity="OBJ-MEMORY",
              kind="objective", label="Refund requirement", payload=None, relations=None):
        return append_project_event(
            repo=self.repo, event_type=event_type,
            subject={"id": identity, "kind": kind, "label": label},
            epistemic_status=status, payload=payload or {}, relations=relations or [],
            provenance={"producer": "test", "source": "assertion-" + status},
            actor={"kind": "human", "id": "test"},
        )[0]

    def row(self, table, column, identity):
        conn = sqlite3.connect(ensure_state(self.repo))
        conn.row_factory = sqlite3.Row
        try:
            return dict(conn.execute(f"select * from {table} where {column}=?", (identity,)).fetchone())
        finally:
            conn.close()

    def test_replacement_facts_carry_their_own_authority_and_provenance(self):
        for prior, replacement in (("VERIFIED", "OBSERVED"), ("VERIFIED", "INFERRED"),
                                   ("VERIFIED", "DECLARED"), ("OBSERVED", "DECLARED"),
                                   ("INFERRED", "DECLARED")):
            with self.subTest(prior=prior, replacement=replacement):
                identity = "OBJ-" + prior + "-" + replacement
                self.event(prior, identity=identity, payload={"why": "old assertion"})
                latest = self.event(replacement, identity=identity,
                                    label="Replacement refund requirement",
                                    payload={"why": "new assertion"})
                row = self.row("entities", "entity_id", identity)
                self.assertEqual(row["epistemic_status"], replacement)
                self.assertEqual(row["source_event_id"], latest["event_id"])
                self.assertEqual(json.loads(row["provenance_json"]), latest["provenance"])
                self.assertEqual(json.loads(row["payload_json"]), latest["payload"])

    def test_relation_update_never_inherits_authority_for_new_metadata(self):
        target = {"id": "OBJ-TARGET", "kind": "objective"}
        self.event("VERIFIED", relations=[{
            "predicate": "affects", "target": target, "epistemic_status": "VERIFIED",
            "metadata": {"basis": "old executed evidence"},
        }])
        latest = self.event("DECLARED", event_type="relation.declared", relations=[{
            "predicate": "affects", "target": target, "epistemic_status": "DECLARED",
            "metadata": {"basis": "new human assertion"},
        }])
        row = self.row("relations", "source_id", "OBJ-MEMORY")
        self.assertEqual(row["epistemic_status"], "DECLARED")
        self.assertEqual(row["source_event_id"], latest["event_id"])
        self.assertEqual(json.loads(row["metadata_json"]), {"basis": "new human assertion"})

    def test_relation_only_event_does_not_replace_source_entity(self):
        self.event("OBSERVED", payload={"why": "observed refund requirement"})
        before = self.row("entities", "entity_id", "OBJ-MEMORY")
        # A relation is about the existing subject; it is not another assertion of its content.
        self.event("DECLARED", event_type="relation.declared", label="stale copied label",
                   payload={"why": "stale copied payload"}, relations=[{
                       "predicate": "affects", "target": {"id": "OBJ-TARGET", "kind": "objective"},
                       "epistemic_status": "DECLARED",
                   }])
        self.assertEqual(self.row("entities", "entity_id", "OBJ-MEMORY"), before)

    def test_debt_refresh_never_promotes_replacement_measurement(self):
        self.event("OBSERVED", event_type="debt.observed", identity="DW-0123456789AB", kind="debt",
                   payload={"signal": {"title": "Old debt", "points": 2}})
        latest = self.event("DECLARED", event_type="debt.refreshed", identity="DW-0123456789AB", kind="debt",
                            payload={"signal": {"title": "Unobserved replacement", "points": 999}})
        row = self.row("debts", "debt_id", "DW-0123456789AB")
        self.assertEqual(row["epistemic_status"], "DECLARED")
        self.assertEqual(row["title"], "Unobserved replacement")
        self.assertEqual(row["points"], 999)
        self.assertEqual(row["source_event_id"], latest["event_id"])

    def test_legacy_materialization_is_rebuilt_without_journal_mutation(self):
        self.event("VERIFIED", payload={"why": "old assertion"})
        latest = self.event("DECLARED", label="Refund replacement", payload={"why": "new assertion"})
        state = ensure_state(self.repo)
        before = continuity_paths(self.repo).events.read_bytes()
        conn = sqlite3.connect(state)
        try:
            conn.execute("update meta set value='continuity-state-2' where key='schema'")
            conn.execute("update entities set epistemic_status='VERIFIED'")
            conn.commit()
        finally:
            conn.close()
        context = compile_context(self.repo, "Refund replacement", refresh_structure=False)
        item = next(x for x in context["objectives"] if x["id"] == "OBJ-MEMORY")
        self.assertEqual(item["epistemicStatus"], "DECLARED")
        row = self.row("entities", "entity_id", "OBJ-MEMORY")
        self.assertEqual(row["source_event_id"], latest["event_id"])
        self.assertEqual(continuity_paths(self.repo).events.read_bytes(), before)
        self.assertNotEqual(STATE_SCHEMA, "continuity-state-2")
        rebuild_state(self.repo)
        self.assertEqual(self.row("entities", "entity_id", "OBJ-MEMORY"), row)

    def test_real_proof_cannot_certify_a_later_public_cli_declaration(self):
        (self.repo / "calc.py").write_text("def add(a,b):\n    return a-b\n", encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests/test_calc.py").write_text(
            "import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n"
            "    def test_add(self): self.assertEqual(add(2,3),5)\n", encoding="utf-8")
        self.run_command(["git", "add", "."])
        self.run_command(["git", "commit", "-qm", "broken addition"])
        evidence = subprocess.list2cmdline([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"])
        edit = "from pathlib import Path; Path('calc.py').write_text('def add(a,b):\\n    return a+b\\n', encoding='utf-8')"
        self.dw("guard", "--repo", str(self.repo), "--test", evidence, "--policy", "strict",
                "--stability-runs", "1", "--", sys.executable, "-c", edit)
        envelope_path = self.repo / ".git/diffwitness/change-envelope.json"
        before_envelope = envelope_path.read_bytes()
        envelope = json.loads(before_envelope)
        self.assertTrue(envelope["proof"]["accepted"])
        cert = envelope["proof"]["certificate_id"]
        before_proof = self.row("proofs", "certificate_id", cert)
        self.assertEqual(before_proof["epistemic_status"], "VERIFIED")
        before_events = read_project_events(continuity_paths(self.repo).events)
        self.dw("objective", "add", "Invented production payment guarantee", "--id", cert,
                "--why", "DECLARATION_ONLY")
        context = json.loads(self.dw("context", "Invented production payment guarantee", "--json", "--no-refresh-structure"))
        item = next(x for x in context["objectives"] if x["id"] == cert)
        self.assertEqual(item["epistemicStatus"], "DECLARED")
        self.assertEqual(item["details"]["why"], "DECLARATION_ONLY")
        self.assertEqual(self.row("proofs", "certificate_id", cert), before_proof)
        self.assertEqual(envelope_path.read_bytes(), before_envelope)
        self.assertEqual(read_project_events(continuity_paths(self.repo).events)[:len(before_events)], before_events)


if __name__ == "__main__":
    unittest.main()
