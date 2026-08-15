from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Hunk:
    header: str
    text: str
    additions: int
    deletions: int


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
class MutationResult:
    mutation: Mutation
    status: str
    command: CommandResult | None = None
    apply_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation": asdict(self.mutation),
            "status": self.status,
            "command": self.command.to_dict() if self.command else None,
            "apply_error": self.apply_error,
        }
