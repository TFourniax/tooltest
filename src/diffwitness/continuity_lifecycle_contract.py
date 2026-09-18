"""Explicit human judgments about memory applicability, distinct from assertion authority."""
from __future__ import annotations

import re
from typing import Any

from .continuity_task_contract import is_task_edge_event

MEMORY_LIFECYCLE_PROFILE = "project-memory-lifecycle-1"
MEMORY_KINDS = {"objective": "objective", "decision": "decision", "invariant": "invariant", "failed-approach": "approach"}
MEMORY_ACTIONS = {"confirm": "confirmed", "reject": "rejected", "retire": "retired", "supersede": "superseded"}


def is_memory_lifecycle(event: dict[str, Any]) -> bool:
    return event["provenance"].get("diffwitness_profile") == MEMORY_LIFECYCLE_PROFILE


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("memory lifecycle " + message)


def _reference(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"dwev_[0-9a-f]{24}", value) is not None


def validate_memory_lifecycle(event: dict[str, Any]) -> None:
    subject, payload = event["subject"], event["payload"]
    kind = subject["kind"]
    _check(kind in MEMORY_KINDS and set(subject) == {"id", "kind"}, "requires an existing supported memory subject")
    action = event["event_type"].split(".")[-1]
    _check(action in MEMORY_ACTIONS.values() and event["event_type"] == f"{MEMORY_KINDS[kind]}.{action}", "event type must match its subject")
    _check(event["epistemic_status"] == "DECLARED", "human judgment cannot become executed Proof")
    _check(event["actor"] == {"kind": "human", "id": "local-user"}, "requires explicit human source")
    _check(event["provenance"] == {"producer": "diffwitness", "source": "human-cli", "diffwitness_profile": MEMORY_LIFECYCLE_PROFILE}, "requires explicit provenance")
    _check(event.get("dedupe_key") is None and not event.get("relations"), "actions cannot attach unchecked relations or dedupe aliases")
    _check(set(payload) == {"source_event_id", "previous_revision_event_id", "reason", "replacement_id", "replacement_event_id"}, "payload fields are invalid")
    _check(_reference(payload["source_event_id"]) and _reference(payload["previous_revision_event_id"]), "requires exact assertion and revision references")
    _check(isinstance(payload["reason"], str) and 0 < len(payload["reason"].strip()) <= 2000, "requires a nonempty bounded reason")
    if action == "superseded":
        _check(isinstance(payload["replacement_id"], str) and bool(payload["replacement_id"])
               and _reference(payload["replacement_event_id"]), "supersession requires a replacement reference")
    else:
        _check(payload["replacement_id"] is None and payload["replacement_event_id"] is None, "only supersession can identify a replacement")


def lifecycle_view(event: dict[str, Any]) -> dict[str, Any]:
    action = event["event_type"].split(".")[-1]
    payload = event["payload"]
    return {"action": action, "active": action == "confirmed", "reason": payload["reason"],
            "epistemicStatus": "DECLARED", "sourceEventId": event["event_id"],
            "assertionEventId": payload["source_event_id"], "updatedAt": event["timestamp"],
            "replacementId": payload["replacement_id"], "replacementEventId": payload["replacement_event_id"]}


class MemoryHistoryValidator:
    def __init__(self):
        self.current: dict[str, dict[str, Any]] = {}

    def admit(self, event: dict[str, Any]) -> None:
        identity = event["subject"]["id"]
        current = self.current.get(identity)
        if is_memory_lifecycle(event):
            payload = event["payload"]
            _check(current is not None and current["assertion"]["subject"]["kind"] == event["subject"]["kind"], "requires an earlier compatible assertion")
            _check(current["assertion"]["event_id"] == payload["source_event_id"]
                   and current["revision"]["event_id"] == payload["previous_revision_event_id"], "revision is stale or refers to another assertion")
            _check(current["action"] != "superseded", "superseded identity is immutable; use a new identity")
            action = event["event_type"].split(".")[-1]
            if action == "superseded":
                replacement = self.current.get(payload["replacement_id"])
                _check(payload["replacement_id"] != identity and replacement is not None
                       and replacement["active"] and replacement["assertion"]["subject"]["kind"] == event["subject"]["kind"]
                       and replacement["assertion"]["event_id"] == payload["replacement_event_id"],
                       "replacement must be another active assertion of the same kind")
            current.update(revision=event, active=action == "confirmed", action=action)
        elif event["event_type"] != "relation.declared" and not is_task_edge_event(event):
            _check(current is None or current["action"] is None, "managed assertion is immutable; use a new identity")
            payload = event["payload"]
            inactive = event["event_type"].endswith((".superseded", ".retired", ".resolved")) or payload.get("lifecycle") == "inactive"
            self.current[identity] = {"assertion": event, "revision": event, "active": not inactive, "action": None}


def memory_lifecycle_descriptor() -> dict[str, Any]:
    return {"event_types": [f"{prefix}.{action}" for prefix in MEMORY_KINDS.values() for action in MEMORY_ACTIONS.values()],
            "judgment_status": "DECLARED", "grants_proof_authority": False,
            "reference_policy": "current assertion and revision; replacement must be active and same kind",
            "superseded_identity": "terminal and immutable", "unknown_payload_fields": "reject"}
