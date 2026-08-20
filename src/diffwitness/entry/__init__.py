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
    return _frontend_main(argv)


__all__ = ["FrontendError", "main"]