"""Typed, privacy-bounded task records and journal-local reference checks."""
from __future__ import annotations

import re
from typing import Any

TASK_PROFILE = "project-memory-task-1"
TASK_EVENT_TYPES = ("task.recorded", "task.described", "task.activated", "task.linked")
TASK_EDGE_EVENTS = frozenset({"task.activated", "task.linked"})
_IDENTITY_FIELDS = ("origin", "anchor_sha256", "anchor_chars", "session_sha256", "ordinal")


def is_task_edge_event(event: dict[str, Any]) -> bool:
    return event["event_type"] in TASK_EDGE_EVENTS and event["provenance"].get("diffwitness_profile") == TASK_PROFILE


def _matches(pattern: str, value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("task profile " + message)


def validate_task_profile(event: dict[str, Any]) -> None:
    kind, payload, provenance = event["event_type"], event["payload"], event["provenance"]
    identity = event["subject"]["id"]
    _check(kind in TASK_EVENT_TYPES and event["subject"]["kind"] == "task", "requires a task event and subject")
    _check(provenance.get("producer") == "diffwitness", "requires diffwitness provenance")
    _check(set(provenance) == {"producer", "source", "diffwitness_profile"}, "provenance contains unsupported fields")
    _check(set(event["subject"]) == ({"id", "kind"} if kind in TASK_EDGE_EVENTS else {"id", "kind", "label"}),
           "subject contains missing or unsupported fields")
    source = provenance.get("source")
    _check(source in ("native-session", "human-cli"), "source must be native-session or human-cli")
    _check(event["actor"] == ({"kind": "system", "id": "diffwitness-native"} if source == "native-session"
                             else {"kind": "human", "id": "local-user"}), "actor must match the declared source")
    status = "OBSERVED" if kind in TASK_EDGE_EVENTS and source == "native-session" else "DECLARED"
    _check(event["epistemic_status"] == status, "cannot promote task intent or association to Proof")
    why = payload.get("why")
    _check(why is None or isinstance(why, str) and len(why) <= 2000, "why must be a bounded nullable string")

    if kind in ("task.recorded", "task.described"):
        fields = {*_IDENTITY_FIELDS, "why"}
        if kind == "task.described":
            fields.add("source_task_event_id")
            _check(source == "human-cli" and _matches(r"dwev_[0-9a-f]{24}", payload.get("source_task_event_id")),
                   "description requires an explicit source task reference")
            _check(event.get("dedupe_key") is None, "descriptions record each explicit declaration")
        else:
            _check(event.get("dedupe_key") == "task:" + identity, "record dedupe must match its task identity")
        _check(set(payload) == fields, "record payload contains missing or unsupported fields")
        _check(not event.get("relations"), "task records cannot attach unvalidated relations")
        label = event["subject"].get("label")
        _check(isinstance(label, str) and bool(label.strip()), "requires a nonempty label")
        if payload["origin"] == "native-session":
            _check(_matches(r"dwtask_[0-9a-f]{24}", identity), "native task identity is invalid")
            _check(_matches(r"[0-9a-f]{64}", payload["anchor_sha256"])
                   and _matches(r"[0-9a-f]{64}", payload["session_sha256"]), "native digests must be SHA-256")
            _check(type(payload["anchor_chars"]) is int and 0 < payload["anchor_chars"] <= 12000
                   and type(payload["ordinal"]) is int and payload["ordinal"] > 0, "native length/ordinal must be bounded integers")
            if kind == "task.recorded":
                _check(source == "native-session" and why is None and label == "Task " + identity,
                       "native task text must remain private; only an explicit description may persist text")
        else:
            _check(payload["origin"] == "explicit-declaration" and source == "human-cli", "invalid task origin")
            _check(all(payload[field] is None for field in _IDENTITY_FIELDS[1:]), "explicit tasks cannot invent native identity metadata")
        return

    _check(_matches(r"dwev_[0-9a-f]{24}", payload.get("task_event_id")), "requires the original task record")
    if kind == "task.activated":
        _check(set(payload) == {"task_event_id", "session_sha256", "boundary_id"}, "activation fields must be bounded")
        _check(source == "native-session" and _matches(r"[0-9a-f]{64}", payload["session_sha256"])
               and _matches(r"[0-9a-f]{32}", payload["boundary_id"]), "activation requires exact native boundary identity")
        _check(not event.get("relations"), "activation does not prove or link a change")
        _check(event.get("dedupe_key") == f"task-activation:{payload['boundary_id']}:{identity}", "activation dedupe mismatch")
        return

    _check(set(payload) == {"task_event_id", "activation_event_id", "boundary_id", "change_id", "why"}, "link fields must be bounded")
    cid = payload["change_id"]
    _check(_matches(r"dwchg_[0-9a-f]{24}", cid), "link requires an exact change identity")
    native = source == "native-session"
    if native:
        _check(_matches(r"dwev_[0-9a-f]{24}", payload["activation_event_id"])
               and _matches(r"[0-9a-f]{32}", payload["boundary_id"]) and why is None, "native links require an activation, not invented intent")
        _check(event.get("dedupe_key") == f"task-change:{payload['activation_event_id']}:{cid}", "native link dedupe mismatch")
    else:
        _check(payload["activation_event_id"] is None and payload["boundary_id"] is None
               and event.get("dedupe_key") is None, "explicit links cannot invent a native activation")
    relations = event.get("relations", [])
    _check(len(relations) == 1, "link requires exactly one edge")
    relation = relations[0]
    _check(set(relation) == {"predicate", "target", "epistemic_status", "metadata"}
           and set(relation["target"]) == {"id", "kind"}, "link cannot persist extra relation text")
    _check(relation["predicate"] == ("worked_on" if native else "motivates")
           and relation["target"]["kind"] == "change" and relation["target"]["id"] == cid
           and relation.get("epistemic_status", status) == status, "link edge and authority must match its assertion")
    _check(relation.get("metadata") == {"basis": "native-boundary-observation" if native else "explicit-task-declaration",
                                        "causal_proof": False, "why": why}, "link must retain its bounded, non-Proof basis")


class TaskHistoryValidator:
    """References are checked in journal order, including checkpoint imports."""

    def __init__(self):
        self.records: dict[str, dict[str, Any]] = {}
        self.activations: dict[str, dict[str, Any]] = {}
        self.changes: set[str] = set()
        self.kinds: dict[str, str] = {}

    def admit(self, event: dict[str, Any]) -> None:
        kind, identity = event["event_type"], event["subject"]["id"]
        payload = event["payload"]
        if event["provenance"].get("diffwitness_profile") == TASK_PROFILE:
            if kind == "task.recorded":
                _check(identity not in self.kinds, "cannot replace an existing entity with a new task")
                self.records[event["event_id"]] = event
            else:
                reference = payload["source_task_event_id"] if kind == "task.described" else payload["task_event_id"]
                record = self.records.get(reference)
                _check(record is not None and record["subject"]["id"] == identity and self.kinds.get(identity) == "task",
                       "reference must identify an earlier compatible task record")
                if kind == "task.described":
                    _check(all(payload[field] == record["payload"][field] for field in _IDENTITY_FIELDS), "description cannot rebind task identity")
                elif kind == "task.activated":
                    _check(payload["session_sha256"] == record["payload"]["session_sha256"], "activation session does not match the task")
                    self.activations[event["event_id"]] = event
                else:
                    _check(payload["change_id"] in self.changes and self.kinds.get(payload["change_id"]) == "change",
                           "link must identify an earlier compatible observed change")
                    if payload["activation_event_id"] is not None:
                        activation = self.activations.get(payload["activation_event_id"])
                        _check(activation is not None and activation["subject"]["id"] == identity
                               and activation["payload"]["task_event_id"] == reference
                               and activation["payload"]["boundary_id"] == payload["boundary_id"],
                               "native link activation, task and boundary must agree")
        if kind == "change.observed" and event["subject"]["kind"] == "change":
            self.changes.add(identity)
        if not is_task_edge_event(event) and kind != "relation.declared":
            self.kinds[identity] = event["subject"]["kind"]


def task_profile_descriptor() -> dict[str, Any]:
    return {
        "provenance_field": "diffwitness_profile", "event_types": list(TASK_EVENT_TYPES),
        "task_intent_status": "DECLARED", "native_participation_status": "OBSERVED",
        "native_identity": "existing task-v1 ID; digest/length/session digest/ordinal only",
        "explicit_text": "opt-in label and why; never copied from native prompt",
        "references": "earlier compatible records in the same validated journal",
        "unknown_payload_fields": "reject", "grants_proof_authority": False,
        "native_association_is_causal_proof": False,
    }
