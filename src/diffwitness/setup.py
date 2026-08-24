from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


class SetupError(RuntimeError):
    pass


def _idleproof_executable(explicit: str | None = None) -> str:
    candidate = explicit or os.environ.get("DIFFWITNESS_IDLEPROOF_BIN") or shutil.which("idleproof")
    if not candidate:
        raise SetupError(
            "DiffWitness understanding sidecar is not installed. Install the matching DiffWitness alpha bundle "
            "or provide --idleproof-command / DIFFWITNESS_IDLEPROOF_BIN."
        )
    value = str(Path(candidate).expanduser()) if os.path.sep in candidate or (os.path.altsep and os.path.altsep in candidate) else candidate
    if os.path.sep in value or (os.path.altsep and os.path.altsep in value):
        path = Path(value).resolve()
        if not path.exists():
            raise SetupError(f"IdleProof sidecar command does not exist: {path}")
        return str(path)
    resolved = shutil.which(value)
    if not resolved:
        raise SetupError(f"IdleProof sidecar command is not executable: {value}")
    return resolved


def _dw_command() -> str:
    configured = os.environ.get("DIFFWITNESS_BIN")
    if configured:
        return configured
    resolved = shutil.which("dw")
    return resolved or "dw"


def _windows_batch_prefix(command: str, args: Sequence[str]) -> list[str]:
    suffix = Path(command).suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        command_line = subprocess.list2cmdline([command, *args])
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
    return [command, *args]


def _run_sidecar(
    command: str,
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    allow_nonzero: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            _windows_batch_prefix(command, args),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"DiffWitness sidecar command failed to start: {exc}") from exc
    if proc.returncode and not allow_nonzero:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise SetupError(f"DiffWitness sidecar rejected the operation: {detail[:1200]}")
    return proc


def _status(command: str, cwd: Path) -> dict:
    proc = _run_sidecar(
        command,
        ["integration", "status", "--json"],
        cwd=cwd,
        timeout=15.0,
        allow_nonzero=True,
    )
    raw = (proc.stdout or "").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SetupError(f"DiffWitness sidecar returned an invalid status payload: {raw[:500]}") from exc
    if payload.get("schema") != "diffwitness.integration-status.v1":
        raise SetupError("DiffWitness sidecar is incompatible with this release (unexpected integration status schema).")
    return payload


def setup_install(*, cwd: Path, agent: str, idleproof_command: str | None = None) -> dict:
    command = _idleproof_executable(idleproof_command)
    _run_sidecar(
        command,
        [
            "integration",
            "install",
            "--agent",
            agent,
            "--diffwitness-command",
            _dw_command(),
        ],
        cwd=cwd,
        timeout=120.0,
    )
    status = _status(command, cwd)
    if not status.get("healthy"):
        raise SetupError(f"DiffWitness integration installed but failed its health check: {json.dumps(status, sort_keys=True)[:1200]}")
    return status


def setup_uninstall(*, cwd: Path, idleproof_command: str | None = None) -> dict:
    command = _idleproof_executable(idleproof_command)
    proc = _run_sidecar(
        command,
        ["integration", "uninstall"],
        cwd=cwd,
        timeout=60.0,
    )
    return {
        "schema": "diffwitness.setup-uninstall.v1",
        "installed": False,
        "sidecar": command,
        "message": (proc.stdout or "").strip(),
    }


def setup_status(*, cwd: Path, idleproof_command: str | None = None) -> dict:
    command = _idleproof_executable(idleproof_command)
    status = _status(command, cwd)
    return {**status, "sidecar": command}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dw setup",
        description="Arm DiffWitness native IDE integration without wrapping Claude, Codex, or Cursor.",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("install", "status", "uninstall"),
        default="install",
        help="install (default), status, or uninstall",
    )
    parser.add_argument(
        "--agent",
        default="auto",
        help="auto, all, claude, codex, cursor, or a comma-separated combination",
    )
    parser.add_argument(
        "--idleproof-command",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable status")
    return parser


def setup_cli(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cwd = Path.cwd().resolve()
    try:
        if args.action == "status":
            result = setup_status(cwd=cwd, idleproof_command=args.idleproof_command)
        elif args.action == "uninstall":
            result = setup_uninstall(cwd=cwd, idleproof_command=args.idleproof_command)
        else:
            result = setup_install(cwd=cwd, agent=args.agent, idleproof_command=args.idleproof_command)
    except SetupError as exc:
        if args.json:
            print(json.dumps({"schema": "diffwitness.setup-error.v1", "ok": False, "error": str(exc)}))
        else:
            print(f"DiffWitness setup failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.action == "uninstall":
        print("DiffWitness native IDE integration removed. Historical evidence and project continuity were preserved.")
        return 0

    healthy = bool(result.get("healthy"))
    expected = result.get("expectedAdapters") or []
    adapters = ", ".join(expected) if expected else "none"
    if args.action == "status":
        print(f"DiffWitness setup: {'ready' if healthy else 'not ready'} · adapters: {adapters}")
        return 0 if healthy else 1

    print(f"DiffWitness is ready · adapters: {adapters}")
    print("Use Claude Code, Codex, or Cursor normally. DiffWitness will UNDERSTAND · PROVE · OWE · preserve CONTINUITY at the native task boundary.")
    return 0


__all__ = ["SetupError", "setup_cli", "setup_install", "setup_status", "setup_uninstall"]
