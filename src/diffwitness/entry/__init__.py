"""Public DiffWitness frontend.

The package form intentionally owns :mod:`diffwitness.entry` for the current public command surface.
A tiny wrapper configures robust UTF-8 terminal output before delegating to the frontend so an
otherwise successful proof/health command cannot fail merely because a legacy Windows console
cannot encode an annotation, arrow, ellipsis, or repository path.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from ..frontend import FrontendError, main as _frontend_main


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _guard_with_continuity(argv: list[str]) -> int:
    """Run the unchanged Guard kernel, then project a newly written envelope best-effort.

    This wrapper is intentionally outside :mod:`diffwitness.guard`: the authoritative proof/debt
    kernel remains unchanged and a continuity failure can never turn an accepted proof into a
    rejection.  A manual/stale envelope is not trusted; VERIFIED is granted here only after Guard
    itself has validated the generated certificate and rewritten the exact envelope during this run.
    """
    from ..gitops import repo_root
    from ..guard import guard_cli

    parser_repo = "."
    for index, value in enumerate(argv):
        if value == "--repo" and index + 1 < len(argv):
            parser_repo = argv[index + 1]
            break
    try:
        repo = repo_root(parser_repo)
    except Exception:
        # Preserve Guard's canonical error/exit behavior for invalid repository arguments.
        return guard_cli(argv)

    envelope_path = repo / ".git" / "diffwitness" / "change-envelope.json"
    before = _digest(envelope_path)
    rc = guard_cli(argv)
    after = _digest(envelope_path)
    if after is None or after == before:
        return rc

    try:
        from ..continuity_bridge import record_change_envelope
        from ..continuity_state import ensure_state

        result = record_change_envelope(
            repo=repo,
            path=envelope_path,
            actor="diffwitness-guard",
            trusted_proof=True,
        )
        ensure_state(repo)
        created = result.get("created") or {}
        total = sum(int(value or 0) for value in created.values())
        print(f"Project continuity: {total} new event(s) · {result['change_id']}")
    except Exception as exc:
        print(f"Project continuity recording degraded: {str(exc)[:300]}", file=sys.stderr)
    return rc


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "doctor":
        # Doctor is intercepted here so the commercial preflight can evolve independently from the
        # legacy proof CLI while `dw` remains the canonical user-facing command.
        from ..doctor import doctor_cli

        return doctor_cli(args[1:])
    if args and args[0] == "engine":
        # Engine enrollment is machine-local commercial plumbing. Keep it outside the legacy proof
        # parser and outside committed project state while preserving one canonical `dw` executable.
        from ..engine_cli import engine_cli

        return engine_cli(args[1:])
    if args and args[0] == "guard":
        return _guard_with_continuity(args[1:])
    if args and args[0] in {"state", "context", "objective", "decision", "invariant", "failed-approach"}:
        # Continuity is an additive facade over the existing Proof/Debt kernel. Keeping these
        # commands outside the legacy parser means the experimental Project State model can evolve
        # or be removed without changing the stable proof/debt command semantics.
        from ..continuity_cli import (
            context_cli,
            decision_cli,
            failed_approach_cli,
            invariant_cli,
            objective_cli,
            state_cli,
        )

        handlers = {
            "state": state_cli,
            "context": context_cli,
            "objective": objective_cli,
            "decision": decision_cli,
            "invariant": invariant_cli,
            "failed-approach": failed_approach_cli,
        }
        return handlers[args[0]](args[1:])
    return _frontend_main(args)


__all__ = ["FrontendError", "main"]
