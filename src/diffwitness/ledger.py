from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .debt_models import DEBT_CATEGORIES, DebtReport, DebtSignal


class LedgerError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _event_hash(event: dict[str, Any]) -> str:
    stable = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class LedgerItem:
    debt_id: str
    status: str
    category: str
    rule_id: str
    title: str
    severity: str
    measurement: str
    points: int
    anchor: str
    explanation: str
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    introduced_by: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    introduced_at: str | None = None
    updated_at: str | None = None
    resolved_at: str | None = None
    resolution: dict[str, Any] | None = None
    accepted: bool = False
    accepted_reason: str | None = None
    reopen_count: int = 0

    @property
    def active(self) -> bool:
        return self.status == "open"

    @classmethod
    def from_signal(cls, signal: DebtSignal, *, timestamp: str) -> "LedgerItem":
        return cls(
            debt_id=signal.debt_id, status="open", category=signal.category, rule_id=signal.rule_id,
            title=signal.title, severity=signal.severity, measurement=signal.measurement,
            points=int(signal.points or 0), anchor=signal.anchor, explanation=signal.explanation,
            path=signal.path, line=signal.line, end_line=signal.end_line, evidence=dict(signal.evidence),
            verification=dict(signal.verification), introduced_by=dict(signal.introduced_by),
            tags=list(signal.tags), introduced_at=timestamp, updated_at=timestamp,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "debt_id": self.debt_id, "status": self.status, "category": self.category,
            "rule_id": self.rule_id, "title": self.title, "severity": self.severity,
            "measurement": self.measurement, "points": self.points, "anchor": self.anchor,
            "explanation": self.explanation, "path": self.path, "line": self.line,
            "end_line": self.end_line, "evidence": self.evidence, "verification": self.verification,
            "introduced_by": self.introduced_by, "tags": self.tags, "introduced_at": self.introduced_at,
            "updated_at": self.updated_at, "resolved_at": self.resolved_at, "resolution": self.resolution,
            "accepted": self.accepted, "accepted_reason": self.accepted_reason, "reopen_count": self.reopen_count,
        }


class DebtLedger:
    """Append-only debt ledger with a hash chain; defaults under `.git/diffwitness`."""

    def __init__(self, path: Path, events: list[dict[str, Any]] | None = None) -> None:
        self.path = path
        self.events = list(events or [])
        self._validate_chain()

    @classmethod
    def load(cls, path: Path) -> "DebtLedger":
        if not path.exists():
            return cls(path, [])
        events: list[dict[str, Any]] = []
        try:
            for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not raw.strip():
                    continue
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise LedgerError(f"ledger line {number} is not a JSON object")
                events.append(value)
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerError(f"cannot read debt ledger {path}: {exc}") from exc
        return cls(path, events)

    def _validate_chain(self) -> None:
        previous: str | None = None
        for index, event in enumerate(self.events, start=1):
            if event.get("schema_version") != "debt-event-1":
                raise LedgerError(f"unsupported ledger event at line {index}")
            if event.get("prev_hash") != previous:
                raise LedgerError(f"debt ledger hash chain broken at line {index}")
            expected = _event_hash(event)
            if event.get("event_hash") != expected:
                raise LedgerError(f"debt ledger integrity check failed at line {index}")
            previous = expected

    @property
    def last_hash(self) -> str | None:
        return self.events[-1].get("event_hash") if self.events else None

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        body = "".join(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n" for event in self.events)
        temp.write_text(body, encoding="utf-8")
        os.replace(temp, self.path)

    def append(self, *, event_type: str, debt_id: str, payload: dict[str, Any], actor: str = "diffwitness", timestamp: str | None = None) -> dict[str, Any]:
        event = {"schema_version": "debt-event-1", "event_type": event_type, "debt_id": debt_id,
                 "timestamp": timestamp or _now(), "actor": actor, "prev_hash": self.last_hash, "payload": payload}
        event["event_hash"] = _event_hash(event)
        self.events.append(event)
        self._persist()
        return event

    def items(self) -> dict[str, LedgerItem]:
        state: dict[str, LedgerItem] = {}
        for event in self.events:
            debt_id = str(event["debt_id"])
            payload = event.get("payload") or {}
            event_type = event.get("event_type")
            timestamp = str(event.get("timestamp") or "")
            if event_type in {"introduced", "reopened"}:
                raw = payload.get("signal") or {}
                try:
                    signal = DebtSignal(
                        category=str(raw["category"]), rule_id=str(raw["rule_id"]), title=str(raw["title"]),
                        severity=str(raw["severity"]), measurement=str(raw["measurement"]), anchor=str(raw["anchor"]),
                        explanation=str(raw["explanation"]), path=raw.get("path"), line=raw.get("line"),
                        end_line=raw.get("end_line"), points=raw.get("points"), evidence=dict(raw.get("evidence") or {}),
                        verification=dict(raw.get("verification") or {}), introduced_by=dict(raw.get("introduced_by") or {}),
                        tags=list(raw.get("tags") or []),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise LedgerError(f"invalid signal payload for {debt_id}: {exc}") from exc
                item = LedgerItem.from_signal(signal, timestamp=timestamp)
                item.debt_id = debt_id
                old = state.get(debt_id)
                if old and event_type == "reopened":
                    item.introduced_at = old.introduced_at
                    item.reopen_count = old.reopen_count + 1
                state[debt_id] = item
            elif event_type == "resolved":
                item = state.get(debt_id)
                if item:
                    item.status = "resolved"; item.resolved_at = timestamp; item.updated_at = timestamp; item.resolution = dict(payload)
            elif event_type == "accepted":
                item = state.get(debt_id)
                if item:
                    item.accepted = True; item.accepted_reason = str(payload.get("reason") or "") or None; item.updated_at = timestamp
            elif event_type == "unaccepted":
                item = state.get(debt_id)
                if item:
                    item.accepted = False; item.accepted_reason = None; item.updated_at = timestamp
            elif event_type == "refreshed":
                item = state.get(debt_id); raw = payload.get("signal") or {}
                if item and isinstance(raw, dict):
                    item.title = str(raw.get("title", item.title)); item.severity = str(raw.get("severity", item.severity))
                    item.points = int(raw.get("points", item.points)); item.explanation = str(raw.get("explanation", item.explanation))
                    item.evidence = dict(raw.get("evidence") or item.evidence); item.verification = dict(raw.get("verification") or item.verification)
                    item.introduced_by = dict(raw.get("introduced_by") or item.introduced_by); item.updated_at = timestamp
        return state

    def active_items(self, *, include_accepted: bool = True) -> list[LedgerItem]:
        items = [item for item in self.items().values() if item.active]
        if not include_accepted:
            items = [item for item in items if not item.accepted]
        return sorted(items, key=lambda item: (-item.points, item.category, item.debt_id))

    def active_points(self, *, include_accepted: bool = True) -> int:
        return sum(item.points for item in self.active_items(include_accepted=include_accepted))

    def active_by_category(self, *, include_accepted: bool = True) -> dict[str, int]:
        result = {category: 0 for category in DEBT_CATEGORIES}
        for item in self.active_items(include_accepted=include_accepted):
            result[item.category] += item.points
        return {category: points for category, points in result.items() if points}

    def record_report(self, report: DebtReport, *, actor: str = "diffwitness") -> dict[str, int]:
        before = self.items(); introduced = reopened = refreshed = 0
        for signal in report.signals:
            current = before.get(signal.debt_id)
            payload = {"signal": signal.to_dict(), "report": {"scope": report.scope, "base_sha": report.base_sha,
                       "candidate_sha": report.candidate_sha, "candidate_tree": report.candidate_tree,
                       "certificate_id": report.certificate_id}}
            if current is None:
                self.append(event_type="introduced", debt_id=signal.debt_id, payload=payload, actor=actor); introduced += 1
            elif current.status == "resolved":
                self.append(event_type="reopened", debt_id=signal.debt_id, payload=payload, actor=actor); reopened += 1
            else:
                current_shape = {"title": current.title, "severity": current.severity, "points": current.points,
                                 "explanation": current.explanation, "evidence": current.evidence,
                                 "verification": current.verification, "introduced_by": current.introduced_by}
                signal_shape = {"title": signal.title, "severity": signal.severity, "points": int(signal.points or 0),
                                "explanation": signal.explanation, "evidence": signal.evidence,
                                "verification": signal.verification, "introduced_by": signal.introduced_by}
                if current_shape != signal_shape:
                    self.append(event_type="refreshed", debt_id=signal.debt_id, payload=payload, actor=actor); refreshed += 1
        return {"introduced": introduced, "reopened": reopened, "refreshed": refreshed}

    def reconcile_project_report(self, report: DebtReport, *, actor: str = "diffwitness") -> dict[str, int]:
        stats = self.record_report(report, actor=actor); present = {signal.debt_id for signal in report.signals}; resolved = 0
        for item in self.active_items():
            if item.verification.get("type") != "project-rule" or item.debt_id in present:
                continue
            self.resolve(item.debt_id, reason="project rule no longer reproduces in current health scan",
                         verification={"type": "project-rule", "result": "absent"}, actor=actor); resolved += 1
        stats["resolved"] = resolved
        return stats

    def resolve(self, debt_id: str, *, reason: str, verification: dict[str, Any] | None = None,
                actor: str = "diffwitness", force: bool = False) -> None:
        item = self.items().get(debt_id)
        if item is None:
            raise LedgerError(f"unknown debt id: {debt_id}")
        if item.status == "resolved":
            return
        if not force and not verification:
            raise LedgerError("resolving debt requires verification data; use force only for explicit manual override")
        self.append(event_type="resolved", debt_id=debt_id,
                    payload={"reason": reason, "verification": verification or {}, "forced": force}, actor=actor)

    def accept(self, debt_id: str, *, reason: str, actor: str = "user") -> None:
        item = self.items().get(debt_id)
        if item is None or not item.active:
            raise LedgerError(f"cannot accept non-open debt: {debt_id}")
        if not reason.strip():
            raise LedgerError("accepted debt requires an explicit reason")
        self.append(event_type="accepted", debt_id=debt_id, payload={"reason": reason}, actor=actor)

    def unaccept(self, debt_id: str, *, actor: str = "user") -> None:
        item = self.items().get(debt_id)
        if item is None or not item.active:
            raise LedgerError(f"cannot unaccept non-open debt: {debt_id}")
        self.append(event_type="unaccepted", debt_id=debt_id, payload={}, actor=actor)

    def points_delta_since(self, event_index: int) -> int:
        if event_index < 0 or event_index > len(self.events):
            raise LedgerError("invalid ledger event index")
        prefix = DebtLedger(self.path, self.events[:event_index])
        return self.active_points() - prefix.active_points()

    def history(self, debt_id: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event.get("debt_id") == debt_id]

    def export_state(self) -> dict[str, Any]:
        active = self.active_items()
        return {"schema_version": "debt-ledger-state-1", "path": str(self.path), "events": len(self.events),
                "last_hash": self.last_hash, "active_points": sum(item.points for item in active),
                "active_by_category": self.active_by_category(), "active_items": [item.to_dict() for item in active]}
