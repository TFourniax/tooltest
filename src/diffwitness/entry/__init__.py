"""Public DiffWitness frontend.

The package form intentionally owns :mod:`diffwitness.entry` for the current public command surface.
A tiny wrapper configures robust UTF-8 terminal output before delegating to the frontend so an
otherwise successful proof/health command cannot fail merely because a legacy Windows console
cannot encode an annotation, arrow, ellipsis, or repository path.
"""

from __future__ import annotations

import sys

from ..frontend import FrontendError, main as _frontend_main


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


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
    return _frontend_main(args)


__all__ = ["FrontendError", "main"]
