"""Read-only, cited history and bidirectional navigation of recorded relationships."""
from __future__ import annotations

import base64
import binascii
import json
import re
import unicodedata
from collections import deque
from pathlib import Path
from typing import Any

from .continuity_contract import ENTITY_ID_PATTERN
from .continuity_events import ContinuityError, _read_validated_snapshot, continuity_paths
from .gitops import repo_root
from .json_contract import strict_json_loads
from .language import tr

MAX_HISTORY_BYTES = 1024 * 1024
MAX_WHY_BYTES = 8 * 1024 * 1024
_CURSOR_SCHEMA = "memory-history-cursor-1"
_AUTHORITY_NOTE = ("Event hashes identify recorded assertions, not authenticated authors. "
                   "Relationships and traversal do not establish causal Proof or current code applicability.")


def _identity(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(ENTITY_ID_PATTERN, value):
        raise ValueError("identity must be an exact Project Memory entity ID")


def _bound(value: int, maximum: int, name: str) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")


def _wire(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _source(event: dict) -> dict:
    return {"kind": "project-event", "eventId": event["event_id"], "eventHash": event["event_hash"]}


def _cursor(identity: str, count: int, head: str, before: int) -> str:
    raw = _wire({"schema": _CURSOR_SCHEMA, "identity": identity, "count": count,
                 "head": head, "before": before})
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _anchor(cursor: str | None, identity: str, events: list[dict]) -> tuple[int, int]:
    if cursor is None:
        return len(events), len(events) + 1
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048:
            raise ValueError("invalid cursor length")
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        value = strict_json_loads(raw.decode("utf-8"))
        if (not isinstance(value, dict) or set(value) != {"schema", "identity", "count", "head", "before"}
                or value["schema"] != _CURSOR_SCHEMA or value["identity"] != identity
                or type(value["count"]) is not int or not 1 <= value["count"] <= len(events)
                or type(value["before"]) is not int or not 1 <= value["before"] <= value["count"]
                or value["head"] != events[value["count"] - 1]["event_hash"]
                or _cursor(identity, value["count"], value["head"], value["before"]) != cursor):
            raise ValueError("cursor does not match this identity and journal prefix")
        return value["count"], value["before"]
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError) as exc:
        raise ContinuityError("invalid or obsolete history cursor; restart history from its first page") from exc


def entity_history(repo: str | Path, identity: str, *, limit: int = 50,
                   cursor: str | None = None) -> dict:
    """Page original subject events newest first, anchored to an immutable prefix.

    Later appends are allowed between pages; truncation/divergent replacement of
    the anchored prefix fails closed. No derived database or query is persisted.
    """
    _identity(identity)
    _bound(limit, 200, "limit")
    events, digest, _ = _read_validated_snapshot(continuity_paths(repo_root(repo)).events)
    count, before = _anchor(cursor, identity, events)
    head = events[count - 1]["event_hash"] if count else None
    selected, size, more = [], 0, False
    # Reserve enough space for fixed metadata, the bounded identity and cursor.
    for index in range(min(before - 1, count) - 1, -1, -1):
        event = events[index]
        if event["subject"]["id"] != identity:
            continue
        item = {"sequence": index + 1, "event": event}
        item_size = len(_wire(item)) + 1
        if len(selected) == limit or size + item_size > MAX_HISTORY_BYTES - 8192:
            more = True
            break
        selected.append(item)
        size += item_size
    result = {"schema_version": "memory-history-page-1", "identity": identity,
              "anchor": {"eventCount": count, "eventHead": head},
              "validatedJournal": {"eventCount": len(events), "sha256": digest},
              "events": selected, "hasMore": more,
              "nextCursor": _cursor(identity, count, head, selected[-1]["sequence"]) if more and selected else None,
              "authority": _AUTHORITY_NOTE}
    if len(_wire(result)) > MAX_HISTORY_BYTES or more and not selected:
        raise ContinuityError("history page exceeds its byte bound")
    return result


def journal_page(repo: str | Path, *, after: int = 0, expect_head: str | None = None,
                 limit: int = 100) -> dict:
    """Page the validated journal forward from an anchored prefix, oldest first.

    ``after`` counts events already consumed; for ``after > 0`` the caller must
    present the hash of event ``after``. A truncated or divergently replaced
    prefix fails closed so a consumer can never skip or silently merge history.
    Events are returned unchanged; projection belongs to the consumer.
    """
    if type(after) is not int or after < 0:
        raise ValueError("after must be a non-negative integer event count")
    _bound(limit, 500, "limit")
    if after == 0 and expect_head is not None:
        raise ValueError("expect-head applies only after a consumed prefix")
    if after > 0 and (not isinstance(expect_head, str) or not re.fullmatch(r"[0-9a-f]{64}", expect_head)):
        raise ValueError("expect-head must be the complete SHA-256 of event AFTER")
    events, digest, _ = _read_validated_snapshot(continuity_paths(repo_root(repo)).events)
    if after > len(events) or after > 0 and events[after - 1]["event_hash"] != expect_head:
        raise ContinuityError("journal prefix does not match this page cursor; restart the export from event 0")
    selected, size = [], 0
    for index in range(after, min(len(events), after + limit)):
        item = {"sequence": index + 1, "event": events[index]}
        item_size = len(_wire(item)) + 1
        if selected and size + item_size > MAX_HISTORY_BYTES - 8192:
            break
        selected.append(item)
        size += item_size
    following = after + len(selected)
    result = {"schema_version": "project-event-page-1",
              "journal": {"genesisHash": events[0]["event_hash"] if events else None,
                          "eventCount": len(events), "sha256": digest},
              "after": after, "events": selected, "next": following,
              "head": events[following - 1]["event_hash"] if following else None,
              "hasMore": following < len(events), "authority": _AUTHORITY_NOTE}
    if len(_wire(result)) > MAX_HISTORY_BYTES:
        raise ContinuityError("journal page exceeds its byte bound")
    return result


def _reason(value: Any, field: str) -> dict | None:
    if not isinstance(value, str) or not value:
        return None
    return {"field": field, "text": value[:2000], "truncated": len(value) > 2000}


def event_detail(repo: str | Path, event_id: str, *, expected_hash: str | None = None) -> dict:
    """Open an exact cited record, optionally checking the complete cited hash."""
    if not isinstance(event_id, str) or not re.fullmatch(r"dwev_[0-9a-f]{24}", event_id):
        raise ValueError("event ID must identify an exact ProjectEvent")
    if expected_hash is not None and (not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)):
        raise ValueError("expected hash must be a complete lowercase SHA-256 digest")
    events, digest, _ = _read_validated_snapshot(continuity_paths(repo_root(repo)).events)
    matches = [(sequence, event) for sequence, event in enumerate(events, 1) if event["event_id"] == event_id]
    if len(matches) != 1:
        raise ContinuityError("cited event is missing or ambiguous in this journal")
    sequence, event = matches[0]
    if expected_hash is not None and event["event_hash"] != expected_hash:
        raise ContinuityError("cited event hash does not match this journal")
    return {"schema_version": "memory-event-detail-1", "identity": event["subject"]["id"],
            "anchor": {"eventCount": len(events), "eventHead": events[-1]["event_hash"], "journalSha256": digest},
            "sequence": sequence, "event": event, "authority": _AUTHORITY_NOTE}


def _node(identity: str, history, depth: int) -> dict:
    current = history.current.get(identity)
    event = current["assertion"] if current else history.code_bindings.get(identity)
    node = {"id": identity, "depth": depth, "hasRecordedAssertion": event is not None,
            "kind": None, "label": None, "epistemicStatus": None, "source": None,
            "reason": None, "applicability": None}
    if event is None:
        return node
    payload = event["payload"]
    node.update(kind=event["subject"]["kind"], label=event["subject"].get("label"),
                epistemicStatus=event["epistemic_status"], source=_source(event),
                reason=_reason(payload.get("why"), "why") or _reason(payload.get("reason"), "reason"))
    if current:
        revision = current["revision"]
        node["applicability"] = {"active": current["active"], "action": current["action"],
                                 "source": _source(revision) if current["action"] else None,
                                 "epistemicStatus": revision["epistemic_status"] if current["action"] else None,
                                 "reason": _reason(revision["payload"].get("reason"), "reason") if current["action"] else None}
    return node


def why_entity(repo: str | Path, identity: str, *, depth: int = 2,
               max_nodes: int = 50, max_edges: int = 100) -> dict:
    """Navigate latest recorded edges in either direction, preserving each source.

    This is historical relationship navigation, not a causal inference engine.
    Inactive assertions remain visible with their explicit applicability state.
    """
    _identity(identity)
    _bound(depth, 4, "depth")
    _bound(max_nodes, 100, "max_nodes")
    _bound(max_edges, 200, "max_edges")
    events, digest, validator = _read_validated_snapshot(continuity_paths(repo_root(repo)).events)
    latest = {}
    for sequence, event in enumerate(events, 1):
        for relation in event.get("relations", []):
            key = (event["subject"]["id"], relation["predicate"], relation["target"]["id"])
            latest[key] = (sequence, event, relation)
    adjacency: dict[str, list[tuple]] = {}
    for key in sorted(latest):
        adjacency.setdefault(key[0], []).append(key)
        if key[2] != key[0]:
            adjacency.setdefault(key[2], []).append(key)
    queue, distances, edges, seen = deque([identity]), {identity: 0}, [], set()
    truncated = False
    while queue:
        current = queue.popleft()
        if distances[current] >= depth:
            if any(key not in seen for key in adjacency.get(current, [])):
                truncated = True
            continue
        for key in adjacency.get(current, []):
            if key in seen:
                continue
            other = key[2] if key[0] == current else key[0]
            if len(edges) >= max_edges or other not in distances and len(distances) >= max_nodes:
                truncated = True
                continue
            seen.add(key)
            if other not in distances:
                distances[other] = distances[current] + 1
                queue.append(other)
            sequence, event, relation = latest[key]
            metadata = relation.get("metadata", {})
            edges.append({"from": key[0], "predicate": key[1], "to": key[2],
                          "epistemicStatus": relation.get("epistemic_status") or event["epistemic_status"],
                          "source": _source(event), "sequence": sequence,
                          "reason": _reason(metadata.get("why"), "why") or _reason(metadata.get("note"), "note"),
                          "basis": _reason(metadata.get("basis"), "basis")})
    result = {"schema_version": "memory-why-1", "identity": identity,
            "anchor": {"eventCount": len(events), "eventHead": events[-1]["event_hash"] if events else None,
                       "journalSha256": digest},
            "nodes": [_node(key, validator.memory_history, distance) for key, distance in distances.items()],
            "relationships": edges,
            "coverage": {"maxDepth": depth, "maxNodes": max_nodes, "maxEdges": max_edges,
                         "truncated": truncated, "relationshipScope": "latest-recorded-edge-per-directed-triple"},
            "authority": _AUTHORITY_NOTE}
    if len(_wire(result)) > MAX_WHY_BYTES:
        raise ContinuityError("relationship navigation exceeds its byte bound")
    return result


def _display(text: str, *, limit: int = 2000) -> str:
    # Quote recorded text so controls, line breaks and direction overrides cannot
    # forge CLI record boundaries or hide the separately rendered authority.
    safe = "".join(f"\\u{ord(char):04x}" if unicodedata.category(char).startswith("C")
                   or unicodedata.category(char) in {"Zl", "Zp"} else char for char in text[:limit])
    return json.dumps(safe, ensure_ascii=False) + (tr(" [shortened]", " [raccourci]") if len(text) > limit else "")


def render_history(result: dict) -> str:
    lines = [tr("Recorded history: ", "Historique enregistré : ") + result["identity"]]
    if not result["events"]:
        lines.append(tr("No subject event in this page.", "Aucun événement de cet élément dans cette page."))
    for item in result["events"]:
        event = item["event"]
        lines.append(f"- {item['sequence']} · {_display(event['timestamp'], limit=200)} · {event['event_type']} [{event['epistemic_status']}]")
        label = event["subject"].get("label")
        if label:
            lines.append("  " + _display(label))
        reason = event["payload"].get("why") or event["payload"].get("reason")
        if isinstance(reason, str) and reason:
            lines.append("  " + _display(reason[:2000]))
            if len(reason) > 2000:
                lines.append(tr("  Text shortened; the JSON page retains the original event.", "  Texte raccourci ; la page JSON conserve l’événement original."))
        lines.append(f"  {event['event_id']} · {event['event_hash']}")
    if result["nextCursor"]:
        lines.append(tr("Next page: --cursor ", "Page suivante : --cursor ") + result["nextCursor"])
    lines.append(tr("Recorded authority is preserved; history does not reverify the current code.",
                    "L’autorité enregistrée est conservée ; l’historique ne revérifie pas le code actuel."))
    return "\n".join(lines) + "\n"


def render_why(result: dict) -> str:
    lines = [tr("Recorded reasons and relationships: ", "Raisons et relations enregistrées : ") + result["identity"]]
    for node in result["nodes"]:
        status = node["epistemicStatus"] or tr("no recorded assertion", "aucune assertion enregistrée")
        lines.append(f"- {node['id']} · {_display(node['label'] or node['kind'] or '')} [{status}]")
        if node["reason"]:
            lines.append("  " + _display(node["reason"]["text"]))
            if node["reason"]["truncated"]:
                lines.append(tr("  Reason shortened; inspect the cited event in history.", "  Raison raccourcie ; consulter l’événement cité dans l’historique."))
        if node["applicability"] and not node["applicability"]["active"]:
            lines.append(tr("  Inactive memory; retained for history.", "  Mémoire inactive ; conservée pour l’historique."))
        if node["source"]:
            lines.append(f"  {node['source']['eventId']} · {node['source']['eventHash']}")
    for edge in result["relationships"]:
        lines.append(f"{edge['from']} --{edge['predicate']}--> {edge['to']} [{edge['epistemicStatus']}]")
        if edge["reason"]:
            lines.append("  " + _display(edge["reason"]["text"]))
            if edge["reason"]["truncated"]:
                lines.append(tr("  Reason shortened; inspect the cited event in history.", "  Raison raccourcie ; consulter l’événement cité dans l’historique."))
        lines.append(f"  {edge['source']['eventId']} · {edge['source']['eventHash']}")
    if result["coverage"]["truncated"]:
        lines.append(tr("Navigation is bounded; additional relationships may exist.",
                        "La navigation est bornée ; d’autres relations peuvent exister."))
    lines.append(tr("These recorded relationships do not establish causal Proof or current code applicability.",
                    "Ces relations enregistrées n’établissent ni preuve causale ni applicabilité au code actuel."))
    return "\n".join(lines) + "\n"
