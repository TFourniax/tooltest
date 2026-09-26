from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .gitops import repo_root
from .idleproof_sidecar import build_portal_snapshot
from .local_git_state import LocalGitStateError, ensure_local_integration_excludes

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


# The bundled console script installed by this wheel carries this entry point; the IdleProof
# package's own CLI does not. Content, not location, decides: both can share one bin directory.
_BUNDLED_MARKER = b"diffwitness.idleproof_entry"


def _is_bundled_entry(executable: str) -> bool:
    try:
        with open(executable, "rb") as handle:
            return _BUNDLED_MARKER in handle.read(4_000_000)
    except OSError:
        return False


def _resolve_portal_transport() -> tuple[str | None, str | None]:
    """Pick the single Portal transport for this invocation.

    The Alpha's nominal transport is the IdleProof CLI: it owns capture, receipts, the offline queue,
    memory history pages and exact-change assurance. When it is installed, every ``dw portal``
    command is delegated to it, so both tools use one enrollment. The integration bundled with this
    wheel is used only when no IdleProof CLI is on PATH.
    """
    bundled: str | None = None
    directories = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item] or [None]
    for directory in directories:
        candidate = shutil.which("idleproof", path=directory) if directory else shutil.which("idleproof")
        if not candidate:
            continue
        if _is_bundled_entry(candidate):
            bundled = bundled or candidate
            continue
        return "idleproof", candidate
    return ("bundled", bundled) if bundled else (None, None)


def _enrollment_owner(repo: Path) -> str | None:
    """Which transport wrote this repository's enrollment (both use .idleproof/portal.json)."""
    try:
        value = json.loads((repo / ".idleproof" / "portal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("token"), str):
        return "idleproof"
    if "tokenMode" in value or "tokenEnv" in value:
        return "bundled"
    return None


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
            "When IdleProof is installed, these commands use IdleProof's Portal enrollment and delivery "
            "(one enrollment per repository); otherwise the integration bundled with DiffWitness is used.\n\n"
            "Credentials are never accepted as command-line token values. ``--token-stdin`` stores "
            "the scoped device token only under local .git metadata; ``--token-env`` stores only "
            "the environment-variable name."
        )
        return 0

    command = argv[0]
    if command not in _ALLOWED:
        print(f"dw portal: unsupported command: {command}", file=sys.stderr)
        return 2

    try:
        ensure_local_integration_excludes(repo_root("."))
    except LocalGitStateError as exc:
        print(f"dw portal: cannot prepare non-invasive local Git state: {exc}", file=sys.stderr)
        return 2

    repo = repo_root(".")
    kind, executable = _resolve_portal_transport()
    owner = _enrollment_owner(repo)
    if kind == "idleproof":
        if owner == "bundled" and command not in {"id", "identity", "configure", "disconnect"}:
            print(
                "dw portal: this repository was enrolled by the Portal integration bundled with DiffWitness. "
                "IdleProof is installed, so `dw portal` now uses IdleProof's enrollment for this repository. "
                "Run `dw portal id`, generate a credential for that ID in Portal, then "
                "`dw portal configure --endpoint URL --token-stdin`. History already in Portal is kept; "
                "nothing was sent.",
                file=sys.stderr,
            )
            return 2
        forwarded = ["identity" if command == "id" else command, *argv[1:]]
    else:
        if owner == "idleproof":
            print(
                "dw portal: this repository is enrolled through IdleProof, but no IdleProof CLI is on PATH. "
                "Install IdleProof (or add it to PATH) so `dw portal` uses the same enrollment; "
                "nothing was configured or sent.",
                file=sys.stderr,
            )
            return 2
        if command == "snapshot":
            return _snapshot_cli(argv)
        forwarded = argv
    if executable is None:
        print(
            "DiffWitness Portal integration is unavailable. Reinstall the matching DiffWitness wheel and retry.",
            file=sys.stderr,
        )
        return 127

    try:
        proc = subprocess.run(
            [executable, "portal", *forwarded],
            cwd=Path.cwd(),
            check=False,
        )
    except OSError as exc:
        print(f"DiffWitness Portal could not start its local integration: {exc}", file=sys.stderr)
        return 126
    return int(proc.returncode)


__all__ = ["portal_cli"]
