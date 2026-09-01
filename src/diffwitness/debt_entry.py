from __future__ import annotations

from .debt_cli import debt_cli


def debt_entry(argv: list[str]) -> int:
    """Backward-compatible command shim.

    Certificate integrity/content binding, worktree snapshot exclusions, debt measurement,
    budget enforcement, recording and output now live in `debt_cli` so local/CI entrypoints cannot
    drift into subtly different trust semantics.
    """
    return debt_cli(argv)
