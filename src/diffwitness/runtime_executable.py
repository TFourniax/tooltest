"""Bind persistent hook commands to this installation, never implicit PATH order."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

_WINDOWS = os.name == "nt"


class ExecutableResolutionError(ValueError):
    """The intended installation has no identifiable executable."""


def _executable(path: Path) -> str | None:
    if path.is_file() and (_WINDOWS or os.access(path, os.X_OK)):
        return str(path.resolve())
    return None


def resolve_explicit_command(value: str, *, setting: str) -> str:
    """An explicit executable name may use PATH; persist its absolute result."""
    path = Path(value).expanduser()
    if path.parent != Path(".") or path.is_absolute():
        resolved = _executable(path)
    else:
        found = shutil.which(value)
        resolved = _executable(Path(found)) if found else None
    if not resolved:
        raise ExecutableResolutionError(
            f"{setting} must name an existing executable (without arguments): {value}"
        )
    return resolved


def _distribution_entrypoint(name: str) -> str | None:
    # RECORD locates pip/user/venv scripts without guessing a scripts directory.
    # Confirm the metadata belongs to the code actually imported in this process.
    from importlib.metadata import PackageNotFoundError, distribution

    try:
        dist = distribution("diffwitness")
    except PackageNotFoundError:
        return None
    origin = Path(__file__).with_name("__init__.py").resolve()
    matches = Path(dist.locate_file("diffwitness/__init__.py")).resolve() == origin
    if not matches:
        try:
            direct = json.loads(dist.read_text("direct_url.json") or "{}")
            url = urlsplit(direct.get("url", ""))
            if direct.get("dir_info", {}).get("editable") and url.scheme == "file":
                root = Path(url2pathname(("//" + url.netloc if url.netloc else "") + url.path)).resolve()
                matches = origin.is_relative_to(root)
        except (ValueError, TypeError, OSError):
            return None
    if not matches:
        return None
    filename = name + (".exe" if _WINDOWS else "")
    for entry in dist.files or ():
        if entry.name == filename:
            resolved = _executable(Path(dist.locate_file(entry)))
            if resolved:
                return resolved
    return None


def resolve_dw_command() -> str:
    configured = os.environ.get("DIFFWITNESS_BIN")
    if configured:
        return resolve_explicit_command(configured, setting="DIFFWITNESS_BIN")
    if getattr(sys, "frozen", False):
        resolved = _executable(Path(sys.executable))
        if resolved:
            return resolved
    else:
        launcher = Path(sys.argv[0]) if sys.argv else Path(".")
        # distlib's Windows entry wrapper removes .exe from sys.argv[0].
        # Bare argv names are not resolved against cwd or PATH.
        if launcher.parent != Path(".") or launcher.is_absolute():
            if _WINDOWS and launcher.name.lower() in {"dw", "dw.exe", "dw-script.py", "dw-script.pyw"}:
                resolved = _executable(launcher.with_name("dw.exe"))
            elif not _WINDOWS and launcher.name == "dw":
                resolved = _executable(launcher)
            else:
                resolved = None
            if resolved:
                return resolved
        resolved = _distribution_entrypoint("dw")
        if resolved:
            return resolved
    raise ExecutableResolutionError(
        "Cannot identify this DiffWitness installation's dw executable. "
        "Reinstall its entry points or set DIFFWITNESS_BIN explicitly."
    )


def resolve_idleproof_command(explicit: str | None = None) -> str:
    configured = explicit or os.environ.get("DIFFWITNESS_IDLEPROOF_BIN")
    if configured:
        return resolve_explicit_command(configured, setting="--idleproof-command / DIFFWITNESS_IDLEPROOF_BIN")
    resolved = None if getattr(sys, "frozen", False) else _distribution_entrypoint("idleproof")
    if resolved:
        return resolved
    raise ExecutableResolutionError(
        "This DiffWitness installation has no bundled understanding sidecar. "
        "Install the matching bundle or provide --idleproof-command / DIFFWITNESS_IDLEPROOF_BIN."
    )
