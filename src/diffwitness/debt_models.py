from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

DEBT_CATEGORIES = (
    "evidence",
    "test",
    "complexity",
    "redundancy",
    "dependency",
    "architecture",
    "security",
    "migration",
    "knowledge",
    "unverified_change",
)

SEVERITY_POINTS = {"info": 0, "low": 1, "medium": 3, "high": 5, "critical": 8}
SEVERITY_ORDER = {name: index for index, name in enumerate(SEVERITY_POINTS)}
MEASUREMENT_ORDER = {"causal": 0, "deterministic": 1, "historical": 2, "heuristic": 3}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def stable_debt_id(*, category: str, rule_id: str, path: str | None, anchor: str) -> str:
    stable = {"category": category, "rule_id": rule_id, "path": path or "", "anchor": anchor}
    return "DW-" + hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()[:12].upper()


@dataclass(slots=True)
class DebtSignal:
    category: str
    rule_id: str
    title: str
    severity: str
    measurement: str
    anchor: str
    explanation: str
    path: str | None = None
    line: int | None = None
    end_line: int | None = None
    points: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    introduced_by: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.category not in DEBT_CATEGORIES:
            raise ValueError(f"unknown debt category: {self.category}")
        if self.severity not in SEVERITY_POINTS:
            raise ValueError(f"unknown debt severity: {self.severity}")
        if self.measurement not in MEASUREMENT_ORDER:
            raise ValueError(f"unknown debt measurement type: {self.measurement}")
        if self.points is None:
            self.points = SEVERITY_POINTS[self.severity]
        if isinstance(self.points, bool) or not isinstance(self.points, int) or self.points < 0:
            raise ValueError("debt points must be a non-negative integer")
        if self.line is not None and self.line < 1:
            raise ValueError("line must be >= 1")
        if self.end_line is not None and self.end_line < 1:
            raise ValueError("end_line must be >= 1")

    @property
    def debt_id(self) -> str:
        return stable_debt_id(category=self.category, rule_id=self.rule_id, path=self.path, anchor=self.anchor)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["debt_id"] = self.debt_id
        return value


@dataclass(slots=True)
class DebtReport:
    scope: str
    signals: list[DebtSignal]
    repo: str | None = None
    base_sha: str | None = None
    candidate_sha: str | None = None
    candidate_tree: str | None = None
    certificate_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_points(self) -> int:
        return sum(int(signal.points or 0) for signal in self.signals)

    @property
    def by_category(self) -> dict[str, int]:
        result = {category: 0 for category in DEBT_CATEGORIES}
        for signal in self.signals:
            result[signal.category] += int(signal.points or 0)
        return {key: value for key, value in result.items() if value}

    @property
    def by_measurement(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for signal in self.signals:
            result[signal.measurement] = result.get(signal.measurement, 0) + int(signal.points or 0)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "debt-report-1",
            "scope": self.scope,
            "repo": self.repo,
            "base_sha": self.base_sha,
            "candidate_sha": self.candidate_sha,
            "candidate_tree": self.candidate_tree,
            "certificate_id": self.certificate_id,
            "summary": {"points": self.total_points, "signals": len(self.signals), "by_category": self.by_category, "by_measurement": self.by_measurement},
            "signals": [signal.to_dict() for signal in sort_signals(self.signals)],
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class DebtBudgetResult:
    passed: bool
    projected_total: int
    change_points: int
    active_total: int
    violations: list[str] = field(default_factory=list)
    projected_by_category: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sort_signals(signals: Iterable[DebtSignal]) -> list[DebtSignal]:
    return sorted(signals, key=lambda signal: (-SEVERITY_ORDER[signal.severity], MEASUREMENT_ORDER[signal.measurement], signal.category, signal.path or "", signal.line or 0, signal.rule_id, signal.debt_id))


def dedupe_signals(signals: Iterable[DebtSignal]) -> list[DebtSignal]:
    """Keep the strongest signal for each stable debt identity instead of double charging it."""
    by_id: dict[str, DebtSignal] = {}
    for signal in signals:
        current = by_id.get(signal.debt_id)
        if current is None:
            by_id[signal.debt_id] = signal
            continue
        candidate_key = (int(signal.points or 0), -MEASUREMENT_ORDER[signal.measurement], SEVERITY_ORDER[signal.severity])
        current_key = (int(current.points or 0), -MEASUREMENT_ORDER[current.measurement], SEVERITY_ORDER[current.severity])
        if candidate_key > current_key:
            by_id[signal.debt_id] = signal
    return sort_signals(by_id.values())
