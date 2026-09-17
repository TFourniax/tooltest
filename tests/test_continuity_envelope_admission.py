from __future__ import annotations

import contextlib
import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_change_envelope as builder_fixtures
import test_continuity_kernel as kernel_fixtures

from diffwitness.change_envelope import build_change_envelope
from diffwitness.continuity_bridge import record_change_envelope
from diffwitness.continuity_events import (
    ContinuityError, append_project_events, continuity_paths, read_project_events,
)
from diffwitness.continuity_state import ensure_state


class EnvelopeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fixture = kernel_fixtures.ContinuityKernelTests()
        self.repo = fixture.repo(Path(self.temp.name))
        self.envelope, self.cid = fixture.envelope(self.repo)
        append_project_events(repo=self.repo, events=[{
            "event_type": "objective.declared",
            "subject": {"id": "OBJ-EXISTING", "kind": "objective"},
            "epistemic_status": "DECLARED",
            "payload": {"why": "Existing history"},
        }])
        self.path = continuity_paths(self.repo).events
        self.original = self.path.read_bytes()

    def assert_rejected(self, envelope):
        try:
            with self.assertRaises(ContinuityError):
                record_change_envelope(repo=self.repo, envelope=envelope)
            self.assertEqual(self.path.read_bytes(), self.original)
        finally:
            # Isolate failing baseline subcases without hiding their assertions.
            self.path.write_bytes(self.original)

    def test_public_cli_rejects_string_false_without_writing_history(self):
        self.envelope["proof"]["accepted"] = "false"
        source = self.repo / "envelope.json"
        source.write_text(json.dumps(self.envelope), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "diffwitness.entry", "state", "ingest-envelope",
             str(source), "--repo", str(self.repo), "--json"],
            cwd=self.repo, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("proof.accepted", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(continuity_paths(self.repo).state.exists())

    def test_wrong_summary_scalars_fail_atomically(self):
        fields = {
            ("proof", "accepted"): ("false", 0, 1, None, [], {}),
            ("debt", "points"): ("7", 2.5, True, False, -1, None, [], {}),
            ("debt", "budget_passed"): ("false", 0, 1, [], {}),
            ("understanding", "coverage"): ("82", 2.5, True, -1, 101, None, [], {}),
            ("understanding", "feature_coverage"): ("75", False, -1, 101, None),
            ("understanding", "knowledge_debt"): ("3", 2.5, True, -1, None),
            ("understanding", "feature_debt"): ("2", False, -1, None),
        }
        for (summary, field), values in fields.items():
            for value in values:
                with self.subTest(summary=summary, field=field, value=value):
                    envelope = copy.deepcopy(self.envelope)
                    envelope[summary][field] = value
                    self.assert_rejected(envelope)

    def test_malformed_containers_fail_with_controlled_errors(self):
        for value in ([], "envelope", True, 42):
            with self.subTest(root=value):
                self.assert_rejected(value)
        for field in ("repository", "base", "candidate", "proof", "debt", "understanding"):
            for value in ([], ["item"], "object", True, 42):
                with self.subTest(field=field, value=value):
                    envelope = copy.deepcopy(self.envelope)
                    envelope[field] = value
                    self.assert_rejected(envelope)
        for value in ("DW-0123456789AB", {"DW-0123456789AB": True}, 1, [42], [None]):
            with self.subTest(lineages=value):
                envelope = copy.deepcopy(self.envelope)
                envelope["debt"]["open_lineages"] = value
                self.assert_rejected(envelope)

    def test_ambiguous_and_nonfinite_source_json_fails_before_append(self):
        raw = json.dumps(self.envelope)
        variants = (
            raw.replace('"accepted": true', '"accepted": false, "accepted": true'),
            raw.replace('"accepted": true', '"accep\\u0074ed": false, "accepted": true'),
            raw.replace('{', '{"schema_version": "other",', 1),
        )
        # Even discarded extension values must not make admission depend on the parser.
        variants += tuple(raw[:-1] + ', "extensions": {"number": ' + value + '}}'
                          for value in ("NaN", "Infinity", "-Infinity", "1e999"))
        source = self.repo / "envelope.json"
        for invalid in variants:
            with self.subTest(source=invalid[-100:]):
                source.write_text(invalid, encoding="utf-8")
                try:
                    with self.assertRaises(ContinuityError):
                        record_change_envelope(repo=self.repo, path=source)
                    self.assertEqual(self.path.read_bytes(), self.original)
                finally:
                    self.path.write_bytes(self.original)
        for number in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(direct=number):
                self.assert_rejected({**self.envelope, "extensions": {"number": number}})

    def test_valid_false_zero_and_nullable_budget_keep_exact_meaning(self):
        self.envelope["proof"]["accepted"] = False
        self.envelope["debt"].update(points=0, open_lineages=[], budget_passed=None)
        self.envelope["understanding"].update(
            coverage=0, knowledge_debt=0, feature_coverage=100, feature_debt=0,
        )
        record_change_envelope(repo=self.repo, envelope=self.envelope, trusted_proof=True)
        events = read_project_events(self.path)[1:]
        by_type = {event["event_type"]: event for event in events}
        self.assertIs(by_type["proof.completed"]["payload"]["accepted"], False)
        self.assertTrue(all(event["epistemic_status"] == "OBSERVED" for event in events))
        self.assertEqual(by_type["debt.snapshot"]["payload"]["points"], 0)
        self.assertIsNone(by_type["debt.snapshot"]["payload"]["budget_passed"])
        self.assertEqual(by_type["understanding.recorded"]["payload"]["feature_coverage"], 100)
        with contextlib.closing(sqlite3.connect(ensure_state(self.repo))) as conn:
            self.assertEqual(conn.execute("select accepted,epistemic_status from proofs").fetchall(),
                             [(0, "OBSERVED")])

    def test_legacy_absence_and_idempotency_remain_compatible(self):
        self.envelope["proof"].pop("accepted")
        self.envelope["debt"] = {}
        self.envelope["understanding"] = {}
        first = record_change_envelope(repo=self.repo, envelope=self.envelope)
        self.assertEqual(first["created"], {"change": 1, "proof": 1, "debt": 1, "understanding": 1})
        before = self.path.read_bytes()
        repeated = record_change_envelope(repo=self.repo, envelope=self.envelope)
        self.assertEqual(sum(repeated["created"].values()), 0)
        self.assertEqual(self.path.read_bytes(), before)
        by_type = {event["event_type"]: event for event in read_project_events(self.path)[1:]}
        self.assertIs(by_type["proof.completed"]["payload"]["accepted"], False)
        self.assertEqual(by_type["debt.snapshot"]["payload"]["points"], 0)
        self.assertIsNone(by_type["understanding.recorded"]["payload"]["coverage"])
        # Null optional summaries historically mean no summary; retain that behavior.
        self.path.write_bytes(self.original)
        self.envelope.update(proof=None, debt=None, understanding=None)
        result = record_change_envelope(repo=self.repo, envelope=self.envelope)
        self.assertEqual(result["created"], {"change": 1, "proof": 0, "debt": 0, "understanding": 0})

    def test_native_builder_output_remains_importable_and_observed(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = builder_fixtures.ChangeEnvelopeTests()
            repo = fixture.repo(Path(td))
            proof, debt, understanding, cid = fixture._fixtures(repo)
            envelope = build_change_envelope(
                repo=repo, base_ref="HEAD", candidate_ref="WORKTREE",
                proof_path=proof, debt_path=debt, understanding_path=understanding,
            )
            result = record_change_envelope(repo=repo, envelope=envelope)
            self.assertEqual(result["change_id"], cid)
            events = read_project_events(continuity_paths(repo).events)
            self.assertEqual(len(events), 5)
            self.assertTrue(all(event["epistemic_status"] == "OBSERVED" for event in events))


if __name__ == "__main__":
    unittest.main()
