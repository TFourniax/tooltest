from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_ALLOWED = {
    "identity",
    "configure",
    "status",
    "snapshot",
    "sync",
    "assurance",
    "disconnect",
}


def portal_cli(argv: list[str]) -> int:
    """Expose the local Portal sidecar through the public ``dw`` product boundary.

    IdleProof remains an implementation detail/backward-compatible package. Arguments are passed as
    an argv vector (never through a shell), so the sidecar retains its existing credential rules —
    notably tokens stay on stdin or in a named environment variable rather than command history.
    """

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            "DiffWitness Portal\n\n"
            "  dw portal identity [--json]\n"
            "  dw portal configure --endpoint URL --token-stdin\n"
            "  dw portal configure --endpoint URL --token-env ENV_NAME\n"
            "  dw portal status [--json]\n"
            "  dw portal snapshot\n"
            "  dw portal sync [--json]\n"
            "  dw portal assurance --envelope FILE [--json]\n"
            "  dw portal disconnect\n\n"
            "Credentials are never accepted as command-line token values."
        )
        return 0

    command = argv[0]
    if command not in _ALLOWED:
        print(f"dw portal: unsupported command: {command}", file=sys.stderr)
        return 2

    executable = shutil.which("idleproof")
    if executable is None:
        print(
            "DiffWitness Portal sidecar is unavailable. Run `dw setup` from this project, then retry.",
            file=sys.stderr,
        )
        return 127

    try:
        proc = subprocess.run(
            [executable, "portal", *argv],
            cwd=Path.cwd(),
            check=False,
        )
    except OSError as exc:
        print(f"DiffWitness Portal could not start its local sidecar: {exc}", file=sys.stderr)
        return 126
    return int(proc.returncode)


__all__ = ["portal_cli"]
