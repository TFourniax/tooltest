from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .gitops import repo_root
from .idleproof_sidecar import build_portal_snapshot

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


def _snapshot_cli(argv: list[str]) -> int:
    unknown = [value for value in argv[1:] if value != "--json"]
    if unknown:
        print(f"dw portal snapshot: unsupported option: {unknown[0]}", file=sys.stderr)
        return 2
    try:
        snapshot = build_portal_snapshot(repo_root("."))
    except Exception as exc:
        # This command is intentionally local-only. Fail without dumping evidence payloads or secrets.
        print(f"dw portal snapshot failed: {str(exc)[:500]}", file=sys.stderr)
        return 2

    if "--json" in argv[1:]:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    project = snapshot.get("project") if isinstance(snapshot.get("project"), dict) else {}
    privacy = snapshot.get("privacy") if isinstance(snapshot.get("privacy"), dict) else {}
    print(f"DiffWitness Portal snapshot: {snapshot.get('snapshotId')}")
    if project.get("localId"):
        print(f"Local project id: {project.get('localId')}")
    print(
        "Privacy: source code no · raw diff no · raw prompt no"
        if privacy.get("sourceCodeIncluded") is False
        and privacy.get("rawDiffIncluded") is False
        and privacy.get("rawPromptIncluded") is False
        else "Privacy: inspect JSON output before connecting Portal"
    )
    print("No network request was made. Configure Portal only when you are ready to sync this bounded snapshot.")
    return 0


def portal_cli(argv: list[str]) -> int:
    """Expose the bundled local Portal sidecar through the public ``dw`` product boundary.

    Arguments are passed as an argv vector (never through a shell). Device credentials are accepted
    only from a named environment variable or stdin/hidden prompt, never as a command-line value.
    ``dw portal snapshot`` is evaluated in-process so users can inspect the exact bounded payload
    before any Portal configuration or credential exists.
    """

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            "DiffWitness Portal\n\n"
            "  dw portal id [--json]              # preferred\n"
            "  dw portal identity [--json]        # compatibility alias\n"
            "  dw portal configure --endpoint URL --token-stdin\n"
            "  dw portal configure --endpoint URL --token-env ENV_NAME\n"
            "  dw portal status [--json]\n"
            "  dw portal snapshot [--json]        # bounded local preview, no config/network\n"
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

    if command == "snapshot":
        return _snapshot_cli(argv)

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
