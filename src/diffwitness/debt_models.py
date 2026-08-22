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


def _duplicate_locations(signal: DebtSignal) -> list[tuple[str, int]] | None:
    if signal.rule_id != "project.exact-duplicate-block":
        return None
    raw = signal.evidence.get("locations")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    locations: list[tuple[str, int]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        path = item.get("path")
        line = item.get("line")
        if not isinstance(path, str) or not isinstance(line, int) or line < 1:
            return None
        locations.append((path, line))
    locations.sort()
    if len({path for path, _ in locations}) < 2:
        return None
    return locations


def _coalesce_duplicate_regions(signals: list[DebtSignal]) -> list[DebtSignal]:
    """Collapse overlapping 8-line duplicate windows into one human-sized region.

    The project scanner intentionally uses sliding windows for detection sensitivity. Charging
    every adjacent window as a separate obligation makes one copied region look like many debts.
    This post-processing keeps the sensitive detector while presenting/accounting one maximal
    contiguous region. The first window's content-derived anchor is retained so the lineage does
    not depend on absolute line numbers.
    """
    passthrough: list[DebtSignal] = []
    by_paths: dict[tuple[str, ...], list[tuple[tuple[int, ...], DebtSignal]]] = {}
    for signal in signals:
        locations = _duplicate_locations(signal)
        if locations is None:
            passthrough.append(signal)
            continue
        paths = tuple(path for path, _ in locations)
        lines = tuple(line for _, line in locations)
        by_paths.setdefault(paths, []).append((lines, signal))

    merged: list[DebtSignal] = []
    for paths, entries in by_paths.items():
        entries.sort(key=lambda item: item[0])
        runs: list[list[tuple[tuple[int, ...], DebtSignal]]] = []
        current: list[tuple[tuple[int, ...], DebtSignal]] = []
        for entry in entries:
            if not current:
                current = [entry]
                continue
            previous_lines = current[-1][0]
            deltas = [new - old for old, new in zip(previous_lines, entry[0], strict=True)]
            # Adjacent compact-code windows can skip comments/blank lines in source. A bounded
            # positive advance on every copy still represents the same overlapping 8-line run.
            if all(1 <= delta <= 8 for delta in deltas):
                current.append(entry)
            else:
                runs.append(current)
                current = [entry]
        if current:
            runs.append(current)

        for run in runs:
            if len(run) == 1:
                merged.append(run[0][1])
                continue
            first_lines, first = run[0]
            last_lines, _ = run[-1]
            locations = [
                {"path": path, "line": start, "end_line": end + 7}
                for path, start, end in zip(paths, first_lines, last_lines, strict=True)
            ]
            strongest = max((entry[1] for entry in run), key=lambda signal: (SEVERITY_ORDER[signal.severity], int(signal.points or 0)))
            normalized_lines = 8 + len(run) - 1
            merged.append(
                DebtSignal(
                    category="redundancy",
                    rule_id="project.exact-duplicate-block",
                    title="Exact normalized code region duplicated across files",
                    severity=strongest.severity,
                    measurement="deterministic",
                    anchor=first.anchor,
                    path=paths[0],
                    line=first_lines[0],
                    end_line=last_lines[0] + 7,
                    explanation=(
                        f"One normalized duplicated region spans at least {normalized_lines} compact code lines "
                        f"across {len(paths)} files. Overlapping 8-line detector windows are counted once; "
                        "consolidation may or may not be architecturally desirable."
                    ),
                    evidence={
                        "locations": locations,
                        "normalized_lines": normalized_lines,
                        "overlapping_windows": len(run),
                    },
                    verification=first.verification,
                    introduced_by=first.introduced_by,
                    tags=first.tags,
                )
            )
    return passthrough + merged


def dedupe_signals(signals: Iterable[DebtSignal]) -> list[DebtSignal]:
    """Keep one charge per stable obligation, including one charge per duplicate region."""
    normalized = _coalesce_duplicate_regions(list(signals))
    by_id: dict[str, DebtSignal] = {}
    for signal in normalized:
        current = by_id.get(signal.debt_id)
        if current is None:
            by_id[signal.debt_id] = signal
            continue
        candidate_key = (int(signal.points or 0), -MEASUREMENT_ORDER[signal.measurement], SEVERITY_ORDER[signal.severity])
        current_key = (int(current.points or 0), -MEASUREMENT_ORDER[current.measurement], SEVERITY_ORDER[current.severity])
        if candidate_key > current_key:
            by_id[signal.debt_id] = signal
    return sort_signals(by_id.values())
