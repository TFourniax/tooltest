from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .debt_models import DEBT_CATEGORIES, DebtReport, DebtSignal, dedupe_signals


class LedgerError(RuntimeError):
    pass


_EVENT_TYPES = {"introduced", "refreshed", "accepted", "unaccepted", "resolved", "reopened"}
_LOCK_TIMEOUT_SECONDS = 10.0
_STALE_LOCK_SECONDS = 120.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _event_hash(event: dict[str, Any]) -> str:
    stable = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
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
    return events


def _serialize(events: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n" for event in events)


def _atomic_write(path: Path, events: list[dict[str, Any]]) -> None:
    """Durably replace the ledger without exposing a partially written JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    fd: int | None = None
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = None
            handle.write(_serialize(events))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _ledger_lock(path: Path, *, timeout: float = _LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Portable inter-process lock using atomic lock-file creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    token = f"{os.getpid()}:{time.time_ns()}"
    deadline = time.monotonic() + timeout
    acquired = False
    while not acquired:
        try:
            fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > _STALE_LOCK_SECONDS:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise LedgerError(
                    f"timed out waiting for debt ledger lock {lock_path}; another DiffWitness process may still be writing"
                )
            time.sleep(0.05)
            continue
        try:
            os.write(fd, token.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        acquired = True
    try:
        yield
    finally:
        try:
            owner = lock_path.read_text(encoding="utf-8")
        except OSError:
            owner = None
        if owner == token:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


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
            debt_id=signal.debt_id,
            status="open",
            category=signal.category,
            rule_id=signal.rule_id,
            title=signal.title,
            severity=signal.severity,
            measurement=signal.measurement,
            points=int(signal.points or 0),
            anchor=signal.anchor,
            explanation=signal.explanation,
            path=signal.path,
            line=signal.line,
            end_line=signal.end_line,
            evidence=dict(signal.evidence),
            verification=dict(signal.verification),
            introduced_by=dict(signal.introduced_by),
            tags=list(signal.tags),
            introduced_at=timestamp,
            updated_at=timestamp,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "debt_id": self.debt_id,
            "status": self.status,
            "category": self.category,
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "measurement": self.measurement,
            "points": self.points,
            "anchor": self.anchor,
            "explanation": self.explanation,
            "path": self.path,
            "line": self.line,
            "end_line": self.end_line,
            "evidence": self.evidence,
            "verification": self.verification,
            "introduced_by": self.introduced_by,
            "tags": self.tags,
            "introduced_at": self.introduced_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
            "resolution": self.resolution,
            "accepted": self.accepted,
            "accepted_reason": self.accepted_reason,
            "reopen_count": self.reopen_count,
        }


class DebtLedger:
    """Append-only debt ledger with hash and semantic integrity checks."""

    def __init__(self, path: Path, events: list[dict[str, Any]] | None = None) -> None:
        self.path = path
        self.events = list(events or [])
        self._validate_chain()
        self._reduce_items()

    @classmethod
    def load(cls, path: Path) -> "DebtLedger":
        return cls(path, _read_events(path))

    def _validate_chain(self) -> None:
        previous: str | None = None
        for index, event in enumerate(self.events, start=1):
            if event.get("schema_version") != "debt-event-1":
                raise LedgerError(f"unsupported ledger event at line {index}")
            event_type = event.get("event_type")
            if event_type not in _EVENT_TYPES:
                raise LedgerError(f"unknown debt ledger event type at line {index}: {event_type!r}")
            debt_id = event.get("debt_id")
            if not isinstance(debt_id, str) or not debt_id.strip():
                raise LedgerError(f"invalid debt id at ledger line {index}")
            if not isinstance(event.get("timestamp"), str) or not event.get("timestamp"):
                raise LedgerError(f"invalid timestamp at ledger line {index}")
            if not isinstance(event.get("actor"), str) or not event.get("actor"):
                raise LedgerError(f"invalid actor at ledger line {index}")
            if not isinstance(event.get("payload"), dict):
                raise LedgerError(f"invalid payload at ledger line {index}")
            if event.get("prev_hash") != previous:
                raise LedgerError(f"debt ledger hash chain broken at line {index}")
            expected = _event_hash(event)
            if event.get("event_hash") != expected:
                raise LedgerError(f"debt ledger integrity check failed at line {index}")
            previous = expected

    @property
    def last_hash(self) -> str | None:
        return self.events[-1].get("event_hash") if self.events else None

    def _adopt_disk_events(self) -> None:
        disk_events = _read_events(self.path)
        if not disk_events:
            if self.events and self.path.exists():
                raise LedgerError("debt ledger changed concurrently; refusing to overwrite a shorter history")
            return
        DebtLedger(self.path, disk_events)
        if disk_events == self.events:
            return
        if len(disk_events) >= len(self.events) and disk_events[: len(self.events)] == self.events:
            self.events = disk_events
            return
        raise LedgerError("debt ledger changed concurrently with a divergent history; reload before writing")

    def _persist_unlocked(self, events: list[dict[str, Any]]) -> None:
        DebtLedger(self.path, events)
        _atomic_write(self.path, events)

    def _persist(self) -> None:
        """Persist the current state without allowing an unnoticed concurrent overwrite."""
        with _ledger_lock(self.path):
            disk_events = _read_events(self.path)
            if disk_events and disk_events != self.events:
                if len(self.events) < len(disk_events) or self.events[: len(disk_events)] != disk_events:
                    raise LedgerError("debt ledger changed concurrently; refusing to overwrite newer or divergent events")
            self._persist_unlocked(self.events)

    def replace_events(self, events: list[dict[str, Any]]) -> None:
        """Replace the local file only when the replacement is a semantic fast-forward."""
        candidate = list(events)
        DebtLedger(self.path, candidate)
        with _ledger_lock(self.path):
            disk_events = _read_events(self.path)
            if disk_events != candidate:
                if len(candidate) < len(disk_events) or candidate[: len(disk_events)] != disk_events:
                    raise LedgerError("refusing to replace debt ledger with a non-fast-forward history")
                self._persist_unlocked(candidate)
            self.events = candidate

    @staticmethod
    def _validate_append(event_type: str, debt_id: str, payload: dict[str, Any]) -> None:
        if event_type not in _EVENT_TYPES:
            raise LedgerError(f"unknown debt ledger event type: {event_type}")
        if not debt_id.strip():
            raise LedgerError("debt id cannot be empty")
        if not isinstance(payload, dict):
            raise LedgerError("debt ledger payload must be an object")

    def _append_unlocked(
        self,
        *,
        event_type: str,
        debt_id: str,
        payload: dict[str, Any],
        actor: str,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        self._validate_append(event_type, debt_id, payload)
        event = {
            "schema_version": "debt-event-1",
            "event_type": event_type,
            "debt_id": debt_id,
            "timestamp": timestamp or _now(),
            "actor": actor,
            "prev_hash": self.last_hash,
            "payload": payload,
        }
        event["event_hash"] = _event_hash(event)
        updated = [*self.events, event]
        self._persist_unlocked(updated)
        self.events = updated
        return event

    def append(
        self,
        *,
        event_type: str,
        debt_id: str,
        payload: dict[str, Any],
        actor: str = "diffwitness",
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        self._validate_append(event_type, debt_id, payload)
        with _ledger_lock(self.path):
            self._adopt_disk_events()
            return self._append_unlocked(
                event_type=event_type,
                debt_id=debt_id,
                payload=payload,
                actor=actor,
                timestamp=timestamp,
            )

    @staticmethod
    def _signal_from_payload(raw: Any, *, debt_id: str) -> DebtSignal:
        if not isinstance(raw, dict):
            raise LedgerError(f"invalid signal payload for {debt_id}: expected an object")
        try:
            signal = DebtSignal(
                category=str(raw["category"]),
                rule_id=str(raw["rule_id"]),
                title=str(raw["title"]),
                severity=str(raw["severity"]),
                measurement=str(raw["measurement"]),
                anchor=str(raw["anchor"]),
                explanation=str(raw["explanation"]),
                path=raw.get("path"),
                line=raw.get("line"),
                end_line=raw.get("end_line"),
                points=raw.get("points"),
                evidence=dict(raw.get("evidence") or {}),
                verification=dict(raw.get("verification") or {}),
                introduced_by=dict(raw.get("introduced_by") or {}),
                tags=list(raw.get("tags") or []),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LedgerError(f"invalid signal payload for {debt_id}: {exc}") from exc
        embedded_id = raw.get("debt_id")
        if embedded_id is not None and embedded_id != debt_id:
            raise LedgerError(f"signal identity mismatch for {debt_id}: payload carries {embedded_id}")
        if signal.debt_id != debt_id:
            raise LedgerError(f"signal identity mismatch for {debt_id}: stable identity is {signal.debt_id}")
        return signal

    def _reduce_items(self) -> dict[str, LedgerItem]:
        state: dict[str, LedgerItem] = {}
        for index, event in enumerate(self.events, start=1):
            debt_id = str(event["debt_id"])
            payload = event.get("payload") or {}
            event_type = event.get("event_type")
            timestamp = str(event.get("timestamp") or "")
            current = state.get(debt_id)
            if event_type == "introduced":
                if current is not None:
                    raise LedgerError(f"invalid introduced transition for existing debt {debt_id} at line {index}")
                signal = self._signal_from_payload(payload.get("signal"), debt_id=debt_id)
                state[debt_id] = LedgerItem.from_signal(signal, timestamp=timestamp)
            elif event_type == "reopened":
                if current is None or current.active:
                    raise LedgerError(f"invalid reopened transition for {debt_id} at line {index}")
                signal = self._signal_from_payload(payload.get("signal"), debt_id=debt_id)
                item = LedgerItem.from_signal(signal, timestamp=timestamp)
                item.introduced_at = current.introduced_at
                item.reopen_count = current.reopen_count + 1
                state[debt_id] = item
            elif event_type == "resolved":
                if current is None or not current.active:
                    raise LedgerError(f"invalid resolved transition for {debt_id} at line {index}")
                current.status = "resolved"
                current.resolved_at = timestamp
                current.updated_at = timestamp
                current.resolution = dict(payload)
            elif event_type == "accepted":
                if current is None or not current.active:
                    raise LedgerError(f"invalid accepted transition for {debt_id} at line {index}")
                current.accepted = True
                current.accepted_reason = str(payload.get("reason") or "") or None
                current.updated_at = timestamp
            elif event_type == "unaccepted":
                if current is None or not current.active:
                    raise LedgerError(f"invalid unaccepted transition for {debt_id} at line {index}")
                current.accepted = False
                current.accepted_reason = None
                current.updated_at = timestamp
            elif event_type == "refreshed":
                if current is None or not current.active:
                    raise LedgerError(f"invalid refreshed transition for {debt_id} at line {index}")
                signal = self._signal_from_payload(payload.get("signal"), debt_id=debt_id)
                current.title = signal.title
                current.severity = signal.severity
                current.measurement = signal.measurement
                current.points = int(signal.points or 0)
                current.explanation = signal.explanation
                current.line = signal.line
                current.end_line = signal.end_line
                current.evidence = dict(signal.evidence)
                current.verification = dict(signal.verification)
                current.introduced_by = dict(signal.introduced_by)
                current.tags = list(signal.tags)
                current.updated_at = timestamp
        return state

    def items(self) -> dict[str, LedgerItem]:
        return self._reduce_items()

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

    @staticmethod
    def _signal_shape(signal: DebtSignal) -> dict[str, Any]:
        return {
            "title": signal.title,
            "severity": signal.severity,
            "measurement": signal.measurement,
            "points": int(signal.points or 0),
            "explanation": signal.explanation,
            "line": signal.line,
            "end_line": signal.end_line,
            "evidence": signal.evidence,
            "verification": signal.verification,
            "introduced_by": signal.introduced_by,
            "tags": signal.tags,
        }

    @staticmethod
    def _item_shape(item: LedgerItem) -> dict[str, Any]:
        return {
            "title": item.title,
            "severity": item.severity,
            "measurement": item.measurement,
            "points": item.points,
            "explanation": item.explanation,
            "line": item.line,
            "end_line": item.end_line,
            "evidence": item.evidence,
            "verification": item.verification,
            "introduced_by": item.introduced_by,
            "tags": item.tags,
        }

    def _record_report_unlocked(self, report: DebtReport, *, actor: str) -> dict[str, int]:
        before = self.items()
        introduced = reopened = refreshed = 0
        for signal in dedupe_signals(report.signals):
            current = before.get(signal.debt_id)
            payload = {
                "signal": signal.to_dict(),
                "report": {
                    "scope": report.scope,
                    "base_sha": report.base_sha,
                    "candidate_sha": report.candidate_sha,
                    "candidate_tree": report.candidate_tree,
                    "certificate_id": report.certificate_id,
                },
            }
            if current is None:
                self._append_unlocked(event_type="introduced", debt_id=signal.debt_id, payload=payload, actor=actor)
                before[signal.debt_id] = LedgerItem.from_signal(signal, timestamp=str(self.events[-1]["timestamp"]))
                introduced += 1
            elif current.status == "resolved":
                self._append_unlocked(event_type="reopened", debt_id=signal.debt_id, payload=payload, actor=actor)
                reopened_item = LedgerItem.from_signal(signal, timestamp=str(self.events[-1]["timestamp"]))
                reopened_item.introduced_at = current.introduced_at
                reopened_item.reopen_count = current.reopen_count + 1
                before[signal.debt_id] = reopened_item
                reopened += 1
            elif self._item_shape(current) != self._signal_shape(signal):
                self._append_unlocked(event_type="refreshed", debt_id=signal.debt_id, payload=payload, actor=actor)
                refreshed += 1
        return {"introduced": introduced, "reopened": reopened, "refreshed": refreshed}

    def record_report(self, report: DebtReport, *, actor: str = "diffwitness") -> dict[str, int]:
        with _ledger_lock(self.path):
            self._adopt_disk_events()
            return self._record_report_unlocked(report, actor=actor)

    def reconcile_project_report(self, report: DebtReport, *, actor: str = "diffwitness") -> dict[str, int]:
        with _ledger_lock(self.path):
            self._adopt_disk_events()
            stats = self._record_report_unlocked(report, actor=actor)
            present = {signal.debt_id for signal in report.signals}
            resolved = 0
            for item in self.active_items():
                if item.verification.get("type") != "project-rule" or item.debt_id in present:
                    continue
                self._append_unlocked(
                    event_type="resolved",
                    debt_id=item.debt_id,
                    payload={
                        "reason": "project rule no longer reproduces in current health scan",
                        "verification": {"type": "project-rule", "result": "absent"},
                        "forced": False,
                    },
                    actor=actor,
                )
                resolved += 1
            stats["resolved"] = resolved
            return stats

    def resolve(
        self,
        debt_id: str,
        *,
        reason: str,
        verification: dict[str, Any] | None = None,
        actor: str = "diffwitness",
        force: bool = False,
    ) -> None:
        if not reason.strip():
            raise LedgerError("resolving debt requires a non-empty reason")
        if not force and not verification:
            raise LedgerError("resolving debt requires verification data; use force only for explicit manual override")
        with _ledger_lock(self.path):
            self._adopt_disk_events()
            item = self.items().get(debt_id)
            if item is None:
                raise LedgerError(f"unknown debt id: {debt_id}")
            if item.status == "resolved":
                return
            self._append_unlocked(
                event_type="resolved",
                debt_id=debt_id,
                payload={"reason": reason, "verification": verification or {}, "forced": force},
                actor=actor,
            )

    def accept(self, debt_id: str, *, reason: str, actor: str = "user") -> None:
        if not reason.strip():
            raise LedgerError("accepted debt requires an explicit reason")
        with _ledger_lock(self.path):
            self._adopt_disk_events()
            item = self.items().get(debt_id)
            if item is None or not item.active:
                raise LedgerError(f"cannot accept non-open debt: {debt_id}")
            if item.accepted and item.accepted_reason == reason:
                return
            self._append_unlocked(event_type="accepted", debt_id=debt_id, payload={"reason": reason}, actor=actor)

    def unaccept(self, debt_id: str, *, actor: str = "user") -> None:
        with _ledger_lock(self.path):
            self._adopt_disk_events()
            item = self.items().get(debt_id)
            if item is None or not item.active:
                raise LedgerError(f"cannot unaccept non-open debt: {debt_id}")
            if not item.accepted:
                return
            self._append_unlocked(event_type="unaccepted", debt_id=debt_id, payload={}, actor=actor)

    def points_delta_since(self, event_index: int) -> int:
        if event_index < 0 or event_index > len(self.events):
            raise LedgerError("invalid ledger event index")
        prefix = DebtLedger(self.path, self.events[:event_index])
        return self.active_points() - prefix.active_points()

    def history(self, debt_id: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event.get("debt_id") == debt_id]

    def export_state(self) -> dict[str, Any]:
        active = self.active_items()
        return {
            "schema_version": "debt-ledger-state-1",
            "path": str(self.path),
            "events": len(self.events),
            "last_hash": self.last_hash,
            "active_points": sum(item.points for item in active),
            "active_by_category": self.active_by_category(),
            "active_items": [item.to_dict() for item in active],
        }
