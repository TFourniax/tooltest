from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_ALLOWED = {
    "id",
    "identity",
    "configure",
    "status",
    "snapshot",
    "sync",
    "assurance",
    "disconnect",
}


def portal_cli(argv: list[str]) -> int:
    """Expose the bundled local Portal sidecar through the public ``dw`` product boundary.

    Arguments are passed as an argv vector (never through a shell). Device credentials are accepted
    only from a named environment variable or stdin/hidden prompt, never as a command-line value.
    """

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            "DiffWitness Portal\n\n"
            "  dw portal id [--json]              # preferred\n"
            "  dw portal identity [--json]        # compatibility alias\n"
            "  dw portal configure --endpoint URL --token-stdin\n"
            "  dw portal configure --endpoint URL --token-env ENV_NAME\n"
            "  dw portal status [--json]\n"
            "  dw portal snapshot [--json]        # bounded dry-run, no network\n"
            "  dw portal sync [--json]\n"
            "  dw portal assurance --envelope FILE [--json]\n"
            "  dw portal disconnect\n\n"
            "Credentials are never accepted as command-line token values. ``--token-stdin`` stores "
            "the scoped device token only under local .git metadata; ``--token-env`` stores only "
            "the environment-variable name."
        )
        return 0

    command = argv[0]
    if command not in _ALLOWED:
        print(f"dw portal: unsupported command: {command}", file=sys.stderr)
        return 2

    executable = shutil.which("idleproof")
    if executable is None:
        print(
            "DiffWitness Portal sidecar is unavailable. Reinstall the matching DiffWitness wheel and retry.",
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
