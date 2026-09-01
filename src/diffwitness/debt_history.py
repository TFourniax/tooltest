from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .ledger import DebtLedger


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(slots=True)
class DebtTrend:
    days: int
    current_points: int
    start_points: int
    delta_points: int
    introduced: int
    resolved: int
    reopened: int
    accepted: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def trend(ledger: DebtLedger, *, days: int = 30, now: datetime | None = None) -> DebtTrend:
    if days < 1:
        raise ValueError("days must be >= 1")
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current_time - timedelta(days=days)
    before = [
        event
        for event in ledger.events
        if _parse(str(event.get("timestamp") or "1970-01-01T00:00:00+00:00")) < cutoff
    ]
    start = DebtLedger(ledger.path, before)
    window = [
        event
        for event in ledger.events
        if _parse(str(event.get("timestamp") or "1970-01-01T00:00:00+00:00")) >= cutoff
    ]
    counts = {
        kind: sum(1 for event in window if event.get("event_type") == kind)
        for kind in ("introduced", "resolved", "reopened", "accepted")
    }
    current_points = ledger.active_points()
    start_points = start.active_points()
    return DebtTrend(
        days=days,
        current_points=current_points,
        start_points=start_points,
        delta_points=current_points - start_points,
        introduced=counts["introduced"],
        resolved=counts["resolved"],
        reopened=counts["reopened"],
        accepted=counts["accepted"],
    )
