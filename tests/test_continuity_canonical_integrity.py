from __future__ import annotations

import copy
import hashlib
import json
import random
import unittest
from unittest.mock import patch

from diffwitness import continuity_events as journal


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def reference(event):
    identity = {key: value for key, value in event.items() if key not in {"event_id", "event_hash"}}
    content = {key: value for key, value in event.items() if key != "event_hash"}
    return (len(encoded(event)) + 1, "dwev_" + hashlib.sha256(encoded(identity)).hexdigest()[:24],
            hashlib.sha256(encoded(content)).hexdigest())


def signed(payload=None, **extensions):
    event = {"schema_version": "project-event-1", "event_type": "objective.declared",
             "subject": {"id": "OBJ-ONE", "kind": "objective", "label": "Mémoire sûre"},
             "epistemic_status": "DECLARED", "timestamp": "2026-09-23T12:00:00Z",
             "actor": {"kind": "human"}, "provenance": {"producer": "fixture"},
             "payload": payload if payload is not None else {"why": "Conserver les accents"},
             "relations": [], "prev_hash": None, **extensions}
    event["event_id"] = reference(event)[1]
    event["event_hash"] = reference(event)[2]
    return event


class CanonicalIntegrityTests(unittest.TestCase):
    def test_full_validator_encodes_nested_payload_only_once(self):
        event = signed({"nested": {"values": list(range(200))}})
        visits = []
        original = journal._canonical

        def observe(value):
            if isinstance(value, dict) and value.get("payload") is event["payload"]:
                visits.append(value)
            return original(value)

        with patch.object(journal, "_canonical", side_effect=observe):
            journal.validate_project_events([event])
        self.assertEqual(len(visits), 1, "full validation must not serialize the payload repeatedly")

    def test_canonical_bytes_match_independent_reference_for_extensions_and_unicode(self):
        rng = random.Random(20260923)
        values = [None, True, False, 0, -1, 1.0, -0.0, 1e-100, 1e100,
                  "éœ𐀀\u2028\u0085", '\\"event_hash":"nested"', {"z": [1, "a"], "a": {}}]
        extension_keys = ["", "aaa", "event_h", "event_hash!", "event_i", "event_id!", "zzz", "é", "\n"]
        for index in range(200):
            payload = {str(i): copy.deepcopy(rng.choice(values)) for i in range(rng.randrange(8))}
            event = signed(payload, **{key: copy.deepcopy(rng.choice(values)) for key in extension_keys})
            # Reversed insertion order must not alter canonical order or byte lengths.
            event = dict(reversed(list(event.items())))
            with self.subTest(index=index):
                self.assertEqual(journal._event_integrity(event), reference(event))
                journal.validate_project_events([event])

    def test_missing_or_malformed_identity_still_rejects_and_matches_reference(self):
        for field in ("event_id", "event_hash"):
            for value in (None, 123, "", "é", "x" * 64):
                event = signed()
                event[field] = value
                with self.subTest(field=field, value=value):
                    self.assertEqual(journal._event_integrity(event), reference(event))
                    with self.assertRaises(journal.ContinuityError):
                        journal.validate_project_events([event])
            del event[field]
            self.assertEqual(journal._event_integrity(event), reference(event))
            with self.assertRaises(journal.ContinuityError):
                journal.validate_project_events([event])

    def test_corruption_of_any_integrity_input_remains_visible(self):
        for field, value in (("event_id", "dwev_" + "0" * 24), ("event_hash", "0" * 64),
                             ("prev_hash", "0" * 64), ("payload", {"why": "Invented"}),
                             ("epistemic_status", "VERIFIED")):
            event = signed()
            event[field] = value
            with self.subTest(field=field), self.assertRaises(journal.ContinuityError):
                journal.validate_project_events([event])

    def test_size_limit_counts_utf8_and_hash_member_exactly(self):
        event = signed({"why": "é" * 80})
        size = reference(event)[0]
        with patch.object(journal, "_MAX_EVENT_BYTES", size):
            journal.validate_project_events([event])
        with patch.object(journal, "_MAX_EVENT_BYTES", size - 1):
            with self.assertRaisesRegex(journal.ContinuityError, "exceeds"):
                journal.validate_project_events([event])

    def test_finite_json_and_circular_reference_checks_remain_active(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            event = signed()
            event["payload"]["number"] = value
            with self.subTest(value=value), self.assertRaises(journal.ContinuityError):
                journal.validate_project_events([event])
        event = signed()
        event["payload"]["cycle"] = event
        with self.assertRaises(journal.ContinuityError):
            journal.validate_project_events([event])

    def test_nonstandard_python_mapping_keeps_reference_encoding(self):
        class Event(dict):
            pass

        event = Event(signed())
        self.assertEqual(journal._event_integrity(event), reference(event))
        journal.validate_project_events([event])
        malformed = signed()
        malformed[1] = "legacy mixed key"
        with self.assertRaises(journal.ContinuityError):
            journal._event_integrity(malformed)


if __name__ == "__main__":
    unittest.main()
