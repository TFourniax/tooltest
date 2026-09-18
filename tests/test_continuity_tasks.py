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
from unittest.mock import patch

import test_continuity_kernel as fixtures

from diffwitness.continuity_bridge import record_change_envelope
from diffwitness.continuity_context_enriched import compile_context
from diffwitness.continuity_events import ContinuityError, append_project_events, continuity_paths, read_project_events, _event_id, _event_hash
from diffwitness.continuity_state import rebuild_state, ensure_state
from diffwitness.continuity_task_session import cleanup_task_session, stable_task_id
from diffwitness.continuity_transport import _parse, _serialize
from diffwitness.ide_plugin import session_start, user_prompt_submit
from diffwitness.ide_handoff import _record_continuity, _continuity_health_path
from diffwitness.proof_cli import _state_path

PROFILE = "project-memory-task-1"


class DurableTaskTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fixture = fixtures.ContinuityKernelTests()
        self.repo = self.fixture.repo(Path(temp.name))
        self.path = continuity_paths(self.repo).events
        self.sid = "private-session-identifier"
        self.prompt = "Implement partial refunds with PRIVATE_PROMPT_SENTINEL"
        self.addCleanup(cleanup_task_session, self.repo, self.sid)

    def prompt_submit(self, text=None, sid=None):
        return user_prompt_submit({"cwd": str(self.repo), "session_id": sid or self.sid,
                                   "prompt": self.prompt if text is None else text})

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-m", "diffwitness.entry", "task", *args,
                                 "--repo", str(self.repo), "--json"], text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if expected == 0 else result

    def test_native_prompt_persists_stable_identity_without_raw_prompt_or_session(self):
        result = self.prompt_submit()
        self.assertIsNotNone(result)
        events = read_project_events(self.path)
        tasks = [e for e in events if e["event_type"] == "task.recorded"]
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["subject"]["id"], stable_task_id(self.sid, 1, self.prompt))
        self.assertEqual(task["payload"]["anchor_sha256"], hashlib.sha256(self.prompt.encode()).hexdigest())
        self.assertEqual(task["epistemic_status"], "DECLARED")
        self.assertEqual(task["provenance"]["diffwitness_profile"], PROFILE)
        before = self.path.read_bytes()
        self.prompt_submit("oui")
        self.assertEqual(self.path.read_bytes(), before)
        cleanup_task_session(self.repo, self.sid)
        state = rebuild_state(self.repo)
        for raw in (self.path.read_bytes(), state.read_bytes(), _serialize(read_project_events(self.path))):
            self.assertNotIn(self.prompt.encode(), raw)
            self.assertNotIn(self.sid.encode(), raw)
            self.assertNotIn(b"PRIVATE_PROMPT_SENTINEL", raw)

    def test_boundary_participation_keeps_pivots_and_excludes_other_sessions_and_boundaries(self):
        from diffwitness.continuity_tasks import boundary_task_refs
        session_start({"cwd": str(self.repo), "session_id": self.sid})
        first_boundary = json.loads(_state_path(self.repo, self.sid).read_text())["task_boundary_id"]
        self.prompt_submit()
        self.prompt_submit("New task: implement CSV exports")
        self.prompt_submit("continue")
        self.assertEqual(len(boundary_task_refs(self.repo, self.sid, first_boundary)), 2)
        self.assertEqual(boundary_task_refs(self.repo, "another-session", first_boundary), [])
        session_start({"cwd": str(self.repo), "session_id": self.sid})
        next_boundary = json.loads(_state_path(self.repo, self.sid).read_text())["task_boundary_id"]
        self.assertNotEqual(first_boundary, next_boundary)
        self.assertEqual(boundary_task_refs(self.repo, self.sid, next_boundary), [])
        self.prompt_submit("continue")
        self.assertEqual(len(boundary_task_refs(self.repo, self.sid, next_boundary)), 1)

    def test_native_link_is_atomic_idempotent_observed_and_survives_session_cleanup(self):
        from diffwitness.continuity_tasks import boundary_task_refs
        session_start({"cwd": str(self.repo), "session_id": self.sid})
        self.prompt_submit()
        boundary = json.loads(_state_path(self.repo, self.sid).read_text())["task_boundary_id"]
        refs = boundary_task_refs(self.repo, self.sid, boundary)
        envelope, cid = self.fixture.envelope(self.repo)
        record_change_envelope(repo=self.repo, envelope=envelope, task_refs=refs)
        before = self.path.read_bytes()
        record_change_envelope(repo=self.repo, envelope=envelope, task_refs=refs)
        self.assertEqual(self.path.read_bytes(), before)
        cleanup_task_session(self.repo, self.sid)
        events = read_project_events(self.path)
        link = next(e for e in events if e["event_type"] == "task.linked")
        self.assertEqual(link["epistemic_status"], "OBSERVED")
        self.assertEqual(link["relations"][0]["predicate"], "worked_on")
        self.assertEqual(link["relations"][0]["target"]["id"], cid)
        self.assertEqual(_parse(_serialize(events)), events)
        state = rebuild_state(self.repo)
        with contextlib.closing(sqlite3.connect(state)) as conn:
            row = conn.execute("select kind,epistemic_status from entities where entity_id=?", (link["subject"]["id"],)).fetchone()
            self.assertEqual(row, ("task", "DECLARED"))
        context = compile_context(self.repo, link["subject"]["id"], refresh_structure=False)
        self.assertIn(cid, [c["changeId"] for c in context["recentRelatedChanges"]])
        self.assertEqual(context["tasks"][0]["epistemicStatus"], "DECLARED")

    def test_explicit_task_cli_description_link_and_history_retrieval(self):
        self.cli("add", "Refund safety", "--id", "TASK-REFUND", "--why", "Avoid duplicate payouts")
        self.cli("describe", "TASK-REFUND", "--title", "Partial refund safety", "--why", "Preserve idempotency")
        envelope, cid = self.fixture.envelope(self.repo)
        record_change_envelope(repo=self.repo, envelope=envelope)
        self.cli("link", "TASK-REFUND", cid, "--why", "Implements the refund task")
        result = self.cli("show", "TASK-REFUND")
        self.assertEqual(result["schema_version"], "task-memory-1")
        self.assertEqual(result["task"]["label"], "Partial refund safety")
        self.assertEqual(result["task"]["payload"]["why"], "Preserve idempotency")
        self.assertEqual([e["event_type"] for e in result["history"]], ["task.recorded", "task.described", "task.linked"])
        self.assertEqual(result["changes"][0]["changeId"], cid)
        self.assertEqual(result["changes"][0]["proof"]["epistemicStatus"], "OBSERVED")
        context = compile_context(self.repo, "idempotency", refresh_structure=False)
        self.assertIn(cid, [c["changeId"] for c in context["recentRelatedChanges"]])
        self.assertEqual(context["relations"][0]["epistemicStatus"], "DECLARED")

    def test_task_cli_unknown_links_fail_without_changing_history(self):
        self.cli("add", "Refund task", "--id", "TASK-REFUND")
        before = self.path.read_bytes()
        self.cli("link", "TASK-REFUND", "dwchg_" + "a" * 24, expected=2)
        self.cli("describe", "TASK-MISSING", "--why", "unknown", expected=2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_native_task_can_be_explicitly_described_without_reimport_conflict(self):
        self.prompt_submit()
        tid = stable_task_id(self.sid, 1, self.prompt)
        self.cli("describe", tid, "--title", "Refund privacy", "--why", "Explicitly saved intent")
        before = self.path.read_bytes()
        self.prompt_submit("continue")
        self.assertEqual(self.path.read_bytes(), before)
        result = self.cli("show", tid)
        self.assertEqual(result["task"]["label"], "Refund privacy")
        self.assertNotIn(self.prompt, json.dumps(result))

    def test_invalid_or_cross_task_reference_aborts_whole_envelope_batch(self):
        from diffwitness.continuity_tasks import boundary_task_refs
        session_start({"cwd": str(self.repo), "session_id": self.sid})
        self.prompt_submit()
        boundary = json.loads(_state_path(self.repo, self.sid).read_text())["task_boundary_id"]
        refs = boundary_task_refs(self.repo, self.sid, boundary)
        envelope, _ = self.fixture.envelope(self.repo)
        before = self.path.read_bytes()
        for field, value in (("activation_event_id", "dwev_" + "f" * 24),
                             ("task_id", "dwtask_" + "f" * 24), ("boundary_id", "f" * 32)):
            bad = copy.deepcopy(refs)
            bad[0][field] = value
            with self.subTest(field=field), self.assertRaises(ContinuityError):
                record_change_envelope(repo=self.repo, envelope=envelope, task_refs=bad)
            self.assertEqual(self.path.read_bytes(), before)

    def test_profile_rejects_raw_prompt_extensions_and_authority_promotion(self):
        self.prompt_submit()
        event = next(e for e in read_project_events(self.path) if e["event_type"] == "task.recorded")
        before = self.path.read_bytes()
        for mutate in (lambda e: e["payload"].update(raw_prompt="do not persist"),
                       lambda e: e["payload"].update(anchor_chars=True),
                       lambda e: e.update(epistemic_status="VERIFIED"),
                       lambda e: e["subject"].update(label=self.prompt)):
            spec = copy.deepcopy(event)
            mutate(spec)
            with self.subTest(mutate=mutate), self.assertRaises(ContinuityError):
                append_project_events(repo=self.repo, events=[spec])
            self.assertEqual(self.path.read_bytes(), before)

    def test_hash_valid_broken_references_are_rejected_by_readers_checkpoints_and_old_cache(self):
        session_start({"cwd": str(self.repo), "session_id": self.sid})
        self.prompt_submit()
        state = ensure_state(self.repo)
        events = read_project_events(self.path)
        activation = events[-1]
        self.assertEqual(activation["event_type"], "task.activated")
        activation["payload"]["task_event_id"] = "dwev_" + "f" * 24
        activation["event_id"] = _event_id(activation)
        activation["event_hash"] = _event_hash(activation)
        raw = _serialize(events)
        self.path.write_bytes(raw)
        for reader in (lambda: read_project_events(self.path), lambda: _parse(raw), lambda: rebuild_state(self.repo)):
            with self.subTest(reader=reader), self.assertRaisesRegex(ContinuityError, "task history"):
                reader()
        with contextlib.closing(sqlite3.connect(state)) as conn:
            conn.execute("delete from meta where key like '%file_sha256%'")
            conn.execute("insert into meta(key,value) values(?,?)",
                         ("lifecycle_profile_event_file_sha256", hashlib.sha256(raw).hexdigest()))
            conn.commit()
        with self.assertRaisesRegex(ContinuityError, "task history"):
            compile_context(self.repo, "refund", refresh_structure=False)

    def test_lost_native_participant_stays_degraded_after_a_later_successful_prompt(self):
        session_start({"cwd": str(self.repo), "session_id": self.sid})
        with patch("diffwitness.continuity_tasks.record_native_task", side_effect=OSError(self.prompt)):
            result = self.prompt_submit()
        self.assertIn("memory is degraded", result["hookSpecificOutput"]["additionalContext"])
        state_path = _state_path(self.repo, self.sid)
        self.assertTrue(json.loads(state_path.read_text())["task_memory_error"])
        self.assertNotIn(self.prompt, _continuity_health_path(self.repo).read_text())
        self.prompt_submit("New task: implement CSV exports")
        self.assertTrue(json.loads(state_path.read_text())["task_memory_error"])
        envelope, _ = self.fixture.envelope(self.repo)
        envelope_path = self.repo / "envelope.json"
        envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
        before = self.path.read_bytes()
        _, created, error = _record_continuity(self.repo, envelope_path, task_error=True)
        self.assertEqual(created, 0)
        self.assertIn("participation", error)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(_continuity_health_path(self.repo).exists())

    def test_native_link_rejects_extra_text_and_preserves_description(self):
        from diffwitness.continuity_tasks import boundary_task_refs, native_link_specs
        session_start({"cwd": str(self.repo), "session_id": self.sid})
        self.prompt_submit()
        tid = stable_task_id(self.sid, 1, self.prompt)
        self.cli("describe", tid, "--title", "Public task label")
        boundary = json.loads(_state_path(self.repo, self.sid).read_text())["task_boundary_id"]
        refs = boundary_task_refs(self.repo, self.sid, boundary)
        envelope, cid = self.fixture.envelope(self.repo)
        record_change_envelope(repo=self.repo, envelope=envelope)
        before = self.path.read_bytes()
        spec = native_link_specs(cid, refs)[0]
        spec["relations"][0]["target"]["label"] = self.prompt
        with self.assertRaises(ContinuityError):
            append_project_events(repo=self.repo, events=[spec])
        self.assertEqual(self.path.read_bytes(), before)
        record_change_envelope(repo=self.repo, envelope=envelope, task_refs=refs)
        self.assertEqual(self.cli("show", tid)["task"]["label"], "Public task label")

    def test_task_identity_cannot_replace_existing_entity_and_unprofiled_extensions_keep_projection(self):
        spec = {"event_type": "task.activated", "subject": {"id": "TASK-EXISTING", "kind": "objective", "label": "Legacy intent"},
                "epistemic_status": "DECLARED", "payload": {}, "relations": [],
                "provenance": {"producer": "legacy"}, "actor": {"kind": "human", "id": "tester"}}
        append_project_events(repo=self.repo, events=[spec])
        state = rebuild_state(self.repo)
        with contextlib.closing(sqlite3.connect(state)) as conn:
            self.assertEqual(conn.execute("select kind from entities where entity_id='TASK-EXISTING'").fetchone(), ("objective",))
        before = self.path.read_bytes()
        self.cli("add", "New task", "--id", "TASK-EXISTING", expected=2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_installed_guided_technical_french_and_english_context_show_declared_task(self):
        self.cli("add", "Refund idempotency", "--id", "TASK-REFUND")
        for language in ("en", "fr"):
            for view in ("guided", "technical"):
                for args in (("task", "show", "TASK-REFUND"), ("context", "idempotency", "--no-refresh-structure")):
                    result = subprocess.run([sys.executable, "-m", "diffwitness.entry", "--language", language,
                                             *args, "--view", view, "--repo", str(self.repo)], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("Refund idempotency", result.stdout)
                    self.assertIn("DECLARED", result.stdout)
                    if language == "fr" and args[0] == "task":
                        self.assertIn("Aucun changement", result.stdout)


if __name__ == "__main__":
    unittest.main()
