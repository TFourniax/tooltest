from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_events import append_project_event, continuity_paths, read_project_events
from diffwitness.continuity_relation_cli import relation_cli
from diffwitness.continuity_state import rebuild_state


class ContinuityContractTests(unittest.TestCase):
    def contract(self):
        from diffwitness.continuity_contract import project_memory_contract
        return project_memory_contract()

    def test_public_json_discovery_is_repository_independent_read_only_and_language_stable(self):
        with tempfile.TemporaryDirectory() as td:
            outputs = []
            for language in ("en", "fr"):
                result = subprocess.run(
                    [sys.executable, "-m", "diffwitness.entry", "--language", language, "state", "contract", "--json"],
                    cwd=td, capture_output=True,
                    encoding="utf-8", timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                outputs.append(json.loads(result.stdout))
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[0], self.contract())
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_contract_covers_concepts_without_renaming_historical_wire_kinds(self):
        contract = self.contract()
        self.assertEqual(contract["schema_version"], "project-memory-contract-1")
        self.assertEqual(contract["event_schema"], "project-event-1")
        kinds = contract["entity_kinds"]
        self.assertTrue({"task", "objective", "decision", "invariant", "failed-approach",
                         "feature", "component", "symbol", "dependency", "change",
                         "proof-certificate", "debt", "understanding"} <= set(kinds))
        self.assertEqual(kinds["proof-certificate"]["concept"], "proof")
        self.assertIn("file", kinds)
        self.assertIn("external-module", kinds)
        self.assertEqual(contract["compatibility"]["unknown_kinds"], "preserve")
        self.assertFalse(contract["authority"]["descriptor_grants_verified"])
        self.assertFalse(contract["authority"]["runtime_observation_is_proof"])

    def test_discovery_preserves_the_existing_human_relation_boundary(self):
        contract = self.contract()
        declared = set(contract["relations"]["human_declarable"])
        self.assertEqual(declared, {"motivated_by", "affects", "introduced_in", "created",
                                    "protects", "constrains", "informed", "supersedes",
                                    "depends_on", "serves", "related_to"})
        self.assertTrue({"served_by", "affected", "proves", "describes", "refreshed_in",
                         "reopened_in", "imports", "calls-name"} <= set(contract["relations"]["known"]))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            relation_cli(["add", "OBJ-X", "proves", "CHANGE-X"])
        self.assertEqual(raised.exception.code, 2)

    def test_legacy_extensions_and_projection_lifecycle_survive_reconstruction(self):
        contract = self.contract()
        self.assertEqual(contract["lifecycle"]["projection_states"], ["active", "inactive"])
        self.assertFalse(contract["lifecycle"]["supersedes_relation_retires_source"])
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init", "-q", td], check=True, capture_output=True)
            for identity, event_type, payload in (
                ("EXT-1", "vendor.recorded", {"lifecycle": "active"}),
                ("EXT-2", "vendor.recorded", {"lifecycle": "inactive"}),
                ("EXT-3", "vendor.superseded", {"lifecycle": "active"}),
            ):
                append_project_event(
                    repo=repo, event_type=event_type,
                    subject={"id": identity, "kind": "vendor-extension"},
                    epistemic_status="DECLARED", payload=payload,
                    relations=[{"predicate": "vendor.links", "target": {"id": "EXT-T", "kind": "vendor-target"}}],
                    provenance={"producer": "legacy-provider", "source": "external"},
                )
            path = continuity_paths(repo).events
            before = path.read_bytes()
            events = read_project_events(path)
            state = rebuild_state(repo)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(read_project_events(path), events)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                rows = conn.execute("select entity_id,kind,epistemic_status,lifecycle from entities order by entity_id").fetchall()
            self.assertEqual(rows, [
                ("EXT-1", "vendor-extension", "DECLARED", "active"),
                ("EXT-2", "vendor-extension", "DECLARED", "inactive"),
                ("EXT-3", "vendor-extension", "DECLARED", "inactive"),
            ])

    def test_exported_metadata_cannot_mutate_live_contract_rules(self):
        original = self.contract()
        changed = self.contract()
        changed["epistemic_statuses"].clear()
        changed["relations"]["human_declarable"].append("proves")
        changed["entity_kinds"]["proof-certificate"]["concept"] = "declaration"
        self.assertEqual(self.contract(), original)


if __name__ == "__main__":
    unittest.main()
