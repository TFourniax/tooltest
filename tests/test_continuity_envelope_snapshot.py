from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as kernel_fixtures

from diffwitness import continuity_bridge as bridge
from diffwitness.continuity_events import (
    ContinuityError, append_project_events, continuity_paths, read_project_events,
)


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class EnvelopeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fixture = kernel_fixtures.ContinuityKernelTests()
        self.repo = fixture.repo(Path(self.temp.name))
        self.envelope, self.cid = fixture.envelope(self.repo)
        self.envelope["extensions"] = {"note": "café"}
        self.source = self.repo / "source.json"
        self.raw = (json.dumps(self.envelope, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.source.write_bytes(self.raw)
        append_project_events(repo=self.repo, events=[{
            "event_type": "objective.declared",
            "subject": {"id": "OBJ-EXISTING", "kind": "objective"},
            "epistemic_status": "DECLARED", "payload": {"why": "Keep history"},
        }])
        self.journal = continuity_paths(self.repo).events
        self.original = self.journal.read_bytes()

    def test_replacement_or_deletion_after_parse_keeps_parsed_snapshot_digest(self):
        changed_files = bridge._changed_files
        for action in ("replace", "delete"):
            with self.subTest(action=action):
                self.journal.write_bytes(self.original)
                self.source.write_bytes(self.raw)

                def change_path(repo, parsed):
                    if action == "replace":
                        replacement = copy.deepcopy(parsed)
                        replacement["proof"]["accepted"] = False
                        self.source.write_text(json.dumps(replacement), encoding="utf-8")
                    else:
                        self.source.unlink()
                    return changed_files(repo, parsed)

                with patch.object(bridge, "_changed_files", side_effect=change_path):
                    bridge.record_change_envelope(repo=self.repo, path=self.source)
                events = read_project_events(self.journal)[1:]
                self.assertEqual(len(events), 5)
                self.assertTrue(all(event["epistemic_status"] == "OBSERVED" for event in events))
                proof = next(event for event in events if event["event_type"] == "proof.completed")
                self.assertIs(proof["payload"]["accepted"], True)
                self.assertTrue(all(event["provenance"].get("artifact_digest") == digest(self.raw)
                                    for event in events))
                if action == "replace":
                    self.assertNotEqual(digest(self.source.read_bytes()), digest(self.raw))
                else:
                    self.assertFalse(self.source.exists())

    def test_conflicting_object_and_path_are_rejected_without_append(self):
        for section, field, value in (("proof", "accepted", False), ("debt", "points", 0)):
            with self.subTest(section=section):
                supplied = copy.deepcopy(self.envelope)
                supplied[section][field] = value
                try:
                    with self.assertRaises(ContinuityError):
                        bridge.record_change_envelope(repo=self.repo, envelope=supplied, path=self.source)
                    self.assertEqual(self.journal.read_bytes(), self.original)
                finally:
                    self.journal.write_bytes(self.original)

    def test_matching_dual_input_preserves_raw_unicode_and_line_endings(self):
        for ending in (b"\n", b"\r\n", b"\r"):
            with self.subTest(ending=ending):
                self.journal.write_bytes(self.original)
                raw = self.raw.replace(b"\n", ending)
                self.source.write_bytes(raw)
                first = bridge.record_change_envelope(
                    repo=self.repo, envelope=self.envelope, path=self.source,
                )
                self.assertEqual(sum(first["created"].values()), 5)
                events = read_project_events(self.journal)[1:]
                self.assertTrue(all(event["provenance"]["artifact_digest"] == digest(raw) for event in events))
                before = self.journal.read_bytes()
                # Equivalent serialization can be reimported; existing event bytes stay immutable.
                self.source.write_text(json.dumps(self.envelope), encoding="utf-8")
                second = bridge.record_change_envelope(repo=self.repo, path=self.source)
                self.assertEqual(sum(second["created"].values()), 0)
                self.assertEqual(self.journal.read_bytes(), before)

    def test_supplied_object_cannot_bypass_invalid_or_missing_source(self):
        for raw in (b"not JSON", b"\xff", b'{"accepted":true,"accepted":false}', None):
            with self.subTest(raw=raw):
                if raw is None:
                    self.source.unlink(missing_ok=True)
                else:
                    self.source.write_bytes(raw)
                try:
                    with self.assertRaises(ContinuityError):
                        bridge.record_change_envelope(repo=self.repo, envelope=self.envelope, path=self.source)
                    self.assertEqual(self.journal.read_bytes(), self.original)
                finally:
                    self.journal.write_bytes(self.original)

    def test_direct_object_has_no_invented_file_digest(self):
        self.source.unlink()
        bridge.record_change_envelope(repo=self.repo, envelope=self.envelope)
        events = read_project_events(self.journal)[1:]
        self.assertEqual(len(events), 5)
        self.assertTrue(all("artifact_digest" not in event["provenance"] for event in events))
        self.assertTrue(all(event["epistemic_status"] == "OBSERVED" for event in events))


if __name__ == "__main__":
    unittest.main()
