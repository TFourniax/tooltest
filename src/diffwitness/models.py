from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Hunk:
    header: str
    text: str
    additions: int
    deletions: int
    old_start: int | None = None
    old_count: int | None = None
    new_start: int | None = None
    new_count: int | None = None


@dataclass(slots=True)
class FilePatch:
    path: str
    old_path: str | None
    raw: str
    header: str
    hunks: list[Hunk] = field(default_factory=list)
    structural: bool = False
    binary: bool = False
    is_test: bool = False


@dataclass(slots=True)
class Mutation:
    id: str
    path: str
    label: str
    patch: str
    kind: str
    additions: int
    deletions: int
    line: int | None = None
    end_line: int | None = None


@dataclass(slots=True)
class CommandResult:
    returncode: int | None
    duration_s: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return not self.timed_out and self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunSet:
    runs: list[CommandResult]
    classification: str

    @property
    def passed(self) -> bool:
        return self.classification == "stable-pass"

    @property
    def failed(self) -> bool:
        return self.classification == "stable-fail"

    @property
    def inconclusive(self) -> bool:
        return self.classification in {"flaky", "timeout"}

    @property
    def total_duration_s(self) -> float:
        return sum(run.duration_s for run in self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "runs": [run.to_dict() for run in self.runs],
            "total_duration_s": self.total_duration_s,
        }


# Descriptive alias used by the adaptive engine and external integrations.
RepeatedCommandResult = RunSet


@dataclass(slots=True)
class MutationResult:
    mutation: Mutation
    status: str
    runs: RunSet | None = None
    apply_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation": asdict(self.mutation),
            "status": self.status,
            "runs": self.runs.to_dict() if self.runs else None,
            "apply_error": self.apply_error,
        }


@dataclass(slots=True)
class SubsetResult:
    mutation_ids: list[str]
    mutation_labels: list[str]
    status: str
    runs: RunSet | None = None
    apply_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_ids": self.mutation_ids,
            "mutation_labels": self.mutation_labels,
            "status": self.status,
            "runs": self.runs.to_dict() if self.runs else None,
            "apply_error": self.apply_error,
        }


@dataclass(slots=True)
class SearchSummary:
    enabled: bool
    attempted: int = 0
    budget: int = 0
    exhaustive_at_found_order: bool = False
    found_order: int | None = None
    results: list[SubsetResult] = field(default_factory=list)
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "attempted": self.attempted,
            "budget": self.budget,
            "exhaustive_at_found_order": self.exhaustive_at_found_order,
            "found_order": self.found_order,
            "results": [result.to_dict() for result in self.results],
            "note": self.note,
        }


@dataclass(slots=True)
class AnalysisOutcome:
    candidate: RunSet
    baseline: RunSet
    mutation_results: list[MutationResult]
    test_files: list[str]
    sufficient_search: SearchSummary
    interaction_search: SearchSummary
    minimized_removed_ids: list[str] | None = None
    reduction_patch: str | None = None

    @property
    def contrast(self) -> str:
        if self.candidate.passed and self.baseline.failed:
            return "base-fail_candidate-pass"
        if self.candidate.passed and self.baseline.passed:
            return "base-pass_candidate-pass"
        if self.candidate.passed and self.baseline.inconclusive:
            return "base-inconclusive_candidate-pass"
        return "candidate-not-stable-green"
