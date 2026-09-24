from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import test_continuity_kernel as fixtures
from diffwitness import continuity_events as journal
from diffwitness.continuity_cli import state_cli
from diffwitness.continuity_events import ContinuityError
from diffwitness.continuity_history import journal_page


class JournalPageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temp.name))
        self.paths = journal.continuity_paths(self.repo)

    def record(self, identity):
        return journal.append_project_event(
            repo=self.repo, event_type="objective.declared",
            subject={"id": identity, "kind": "objective", "label": identity},
            epistemic_status="DECLARED", payload={}, relations=[],
            provenance={"producer": "page-fixture"}, actor={"kind": "human", "id": "fixture"})[0]

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = state_cli(["events", "--repo", str(self.repo), *args])
        return code, out.getvalue(), err.getvalue()

    def test_pages_forward_without_gaps_across_appends_and_keeps_bytes(self):
        events = [self.record(f"OBJ-{index}") for index in range(5)]
        raw = self.paths.events.read_bytes()
        first = journal_page(self.repo, after=0, limit=2)
        self.assertEqual(first["schema_version"], "project-event-page-1")
        self.assertEqual([item["sequence"] for item in first["events"]], [1, 2])
        self.assertEqual([item["event"] for item in first["events"]], events[:2])
        self.assertEqual(first["journal"]["genesisHash"], events[0]["event_hash"])
        self.assertEqual((first["next"], first["head"], first["hasMore"]), (2, events[1]["event_hash"], True))
        later = self.record("OBJ-late")
        second = journal_page(self.repo, after=first["next"], expect_head=first["head"], limit=10)
        self.assertEqual([item["event"] for item in second["events"]], [*events[2:], later])
        self.assertFalse(second["hasMore"])
        self.assertEqual(second["journal"]["genesisHash"], first["journal"]["genesisHash"])
        empty = journal_page(self.repo, after=second["next"], expect_head=second["head"])
        self.assertEqual((empty["events"], empty["next"], empty["head"]), ([], 6, later["event_hash"]))
        self.assertTrue(self.paths.events.read_bytes().startswith(raw))

    def test_prefix_mismatch_and_out_of_range_cursors_fail_closed(self):
        events = [self.record(f"OBJ-{index}") for index in range(3)]
        with self.assertRaisesRegex(ContinuityError, "restart"):
            journal_page(self.repo, after=2, expect_head=events[0]["event_hash"])
        with self.assertRaisesRegex(ContinuityError, "restart"):
            journal_page(self.repo, after=4, expect_head=events[2]["event_hash"])
        with self.assertRaises(ValueError):
            journal_page(self.repo, after=1)
        with self.assertRaises(ValueError):
            journal_page(self.repo, after=0, expect_head=events[0]["event_hash"])
        with self.assertRaises(ValueError):
            journal_page(self.repo, after=0, limit=501)
        with self.assertRaises(ValueError):
            journal_page(self.repo, after=-1)

    def test_empty_journal_has_no_identity_and_cli_is_compatible(self):
        empty = journal_page(self.repo, after=0)
        self.assertEqual((empty["journal"]["genesisHash"], empty["events"], empty["next"], empty["head"]), (None, [], 0, None))
        events = [self.record(f"OBJ-{index}") for index in range(3)]
        code, out, _ = self.cli("--limit", "2", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), events[1:])
        code, out, _ = self.cli("--after", "1", "--expect-head", events[0]["event_hash"], "--limit", "5", "--json")
        self.assertEqual(code, 0)
        page = json.loads(out)
        self.assertEqual([item["event"]["event_id"] for item in page["events"]], [e["event_id"] for e in events[1:]])
        code, _, err = self.cli("--after", "1", "--expect-head", "0" * 64, "--json")
        self.assertEqual(code, 2)
        self.assertIn("restart", err)
        code, _, err = self.cli("--after", "0")
        self.assertEqual(code, 2)
        self.assertIn("--json", err)

    def test_tampered_journal_is_not_paged(self):
        self.record("OBJ-0")
        self.record("OBJ-1")
        lines = self.paths.events.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["subject"]["label"] = "tampered"
        lines[0] = json.dumps(record, sort_keys=True, separators=(",", ":"))
        self.paths.events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(ContinuityError):
            journal_page(self.repo, after=0)


if __name__ == "__main__":
    unittest.main()
