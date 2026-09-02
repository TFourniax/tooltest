from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .autodetect import command_available, default_evidence, suggested_available_command
from .config import load_config
from .gitops import repo_root
from .local_git_state import LocalGitStateError, ensure_local_integration_excludes
from .view_mode import get_view_mode


class SetupError(RuntimeError):
    pass


_SETUP_SCOPE_SCHEMA = "diffwitness.setup-scope.v1"


def _setup_scope_path(cwd: Path) -> Path:
    return cwd / ".git" / "diffwitness" / "setup-scope.json"


def _persist_setup_scope(cwd: Path, adapters: Sequence[str]) -> None:
    path = _setup_scope_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": _SETUP_SCOPE_SCHEMA,
        "adapters": list(dict.fromkeys(str(item) for item in adapters if str(item))),
    }
    staged = path.with_suffix(".json.tmp")
    staged.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    staged.replace(path)


def _clear_setup_scope(cwd: Path) -> None:
    try:
        _setup_scope_path(cwd).unlink()
    except (FileNotFoundError, OSError):
        pass


def _git_project(cwd: Path) -> Path:
    try:
        return repo_root(cwd)
    except Exception as exc:
        raise SetupError(
            "DiffWitness setup must be run inside a Git project. Change into the project directory "
            "or run `git init` there first."
        ) from exc


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


def _protect_recommendation(cwd: Path) -> dict:
    """Return a non-mutating recommendation and provider readiness; setup never enables blocking."""
    try:
        from .protect import detect_external_harness, protect_status

        detection = detect_external_harness(cwd)
        status = protect_status(cwd)
        if status.get("mode") != "off":
            recommendation = str(status.get("mode"))
            reason = "Protect already has an explicit local mode."
        elif detection.get("externalHarnessDetected"):
            recommendation = "external"
            reason = "A high-confidence external harness signal was detected."
        else:
            recommendation = "builtin"
            reason = "No high-confidence external harness signal was detected."
        adapters = status.get("adapters") if isinstance(status.get("adapters"), dict) else {}
        bounded = {
            name: {
                "installed": bool(item.get("installed")),
                "ready": bool(item.get("ready")),
                "activation": item.get("activation"),
            }
            for name, item in adapters.items()
            if isinstance(item, dict)
        }
        return {
            "mode": status.get("mode", "off"),
            "health": status.get("health", "unknown"),
            "recommendation": recommendation,
            "reason": reason,
            "adapters": bounded,
        }
    except Exception as exc:
        return {
            "mode": "unknown",
            "health": "unknown",
            "recommendation": "inspect",
            "reason": f"Protect recommendation unavailable: {str(exc)[:200]}",
            "adapters": {},
        }


def _verification_readiness(cwd: Path) -> dict:
    try:
        config = load_config(cwd, None)
    except Exception as exc:
        return {"ready": False, "source": "invalid-config", "command": None, "reason": str(exc)[:300]}
    configured = config.get("test")
    if isinstance(configured, str) and configured.strip():
        command = configured.strip()
        ready = command_available(command, cwd=cwd)
        return {
            "ready": ready,
            "source": "configured",
            "command": command,
            "reason": None if ready else "configured executable is unavailable",
            "suggestion": None if ready else suggested_available_command(command),
        }
    plan = default_evidence(cwd)
    if plan is None:
        return {"ready": False, "source": "missing", "command": None, "reason": "no safe evidence command detected"}
    ready = command_available(plan.command, cwd=cwd)
    return {
        "ready": ready,
        "source": "detected",
        "command": plan.command,
        "confidence": plan.confidence,
        "reason": plan.reason if ready else "detected command executable is unavailable",
        "suggestion": None if ready else suggested_available_command(plan.command),
    }


def _with_readiness(cwd: Path, status: dict) -> dict:
    return {
        **status,
        "protect": _protect_recommendation(cwd),
        "verification": _verification_readiness(cwd),
        "productReady": bool(status.get("healthy") and _verification_readiness(cwd).get("ready")),
    }


def setup_install(*, cwd: Path, agent: str, idleproof_command: str | None = None) -> dict:
    cwd = _git_project(cwd)
    try:
        ensure_local_integration_excludes(cwd)
    except LocalGitStateError as exc:
        raise SetupError(f"cannot prepare non-invasive local Git state: {exc}") from exc
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
    _persist_setup_scope(cwd, status.get("expectedAdapters") or [])
    return _with_readiness(cwd, status)


def setup_uninstall(*, cwd: Path, idleproof_command: str | None = None) -> dict:
    cwd = _git_project(cwd)
    command = _idleproof_executable(idleproof_command)
    proc = _run_sidecar(
        command,
        ["integration", "uninstall"],
        cwd=cwd,
        timeout=60.0,
    )
    _clear_setup_scope(cwd)
    return {
        "schema": "diffwitness.setup-uninstall.v1",
        "installed": False,
        "sidecar": command,
        "message": (proc.stdout or "").strip(),
        "protectPreserved": True,
    }


def setup_status(*, cwd: Path, idleproof_command: str | None = None) -> dict:
    cwd = _git_project(cwd)
    command = _idleproof_executable(idleproof_command)
    status = _status(command, cwd)
    return {**_with_readiness(cwd, status), "sidecar": command}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dw setup",
        description="Connect DiffWitness to Claude Code/Codex/Cursor without wrapping the coding agent.",
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
    parser.add_argument("--idleproof-command", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="emit machine-readable status")
    return parser


def _agent_names(adapters: Sequence[str]) -> str:
    names = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor"}
    rendered = [names.get(str(adapter), str(adapter)) for adapter in adapters]
    if not rendered:
        return "your configured coding agent"
    if len(rendered) == 1:
        return rendered[0]
    return ", ".join(rendered[:-1]) + " and " + rendered[-1]


def _protect_human_lines(protect: dict, *, guided: bool) -> list[str]:
    mode = protect.get("mode")
    if mode == "off":
        return ["• Protection live désactivée (optionnelle)." if guided else "Protect: off · optional"]
    if mode == "external":
        return ["✓ Protection live déléguée à ton harness." if guided else "Protect: external · delegated"]
    if mode != "builtin":
        return ["⚠ État Protect à inspecter avec `dw protect status`." if guided else "Protect: unknown/invalid · inspect `dw protect status`"]
    lines: list[str] = []
    names = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor"}
    for adapter, item in sorted((protect.get("adapters") or {}).items()):
        if not isinstance(item, dict):
            continue
        label = names.get(adapter, adapter)
        if item.get("ready"):
            state = "prête" if guided else "ready"
        elif item.get("installed") and item.get("activation") == "requires-provider-feature-and-trust":
            state = "en attente d’approbation du provider" if guided else "pending provider trust"
        elif item.get("installed"):
            state = "installée, pas encore observée" if guided else "installed, not observed"
        else:
            state = "hooks manquants" if guided else "MISSING HOOKS"
        lines.append(("• " if guided else "  ") + f"{label}: {state}")
    return lines or (["• Protection live activée."] if guided else ["Protect: builtin"])


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
        print("DiffWitness native IDE integration removed. Historical evidence, project continuity, and the separately configured Protect mode were preserved.")
        return 0

    healthy = bool(result.get("healthy"))
    expected = result.get("expectedAdapters") or []
    verification = result.get("verification") or {}
    protect = result.get("protect") or {}
    guided = False
    try:
        guided = get_view_mode(_git_project(cwd)) == "guided"
    except Exception:
        guided = False

    if args.action == "status":
        if guided:
            print("DIFFWITNESS · SETUP")
            print(f"{'✓' if healthy else '⚠'} Agent connecté : {_agent_names(expected)}")
            if verification.get("ready"):
                print(f"✓ Vérification prête : {verification.get('command')}")
            else:
                print("⚠ Vérification encore à configurer.")
                if verification.get("suggestion"):
                    print(f"  Commande disponible suggérée : {verification['suggestion']}")
                print("  Lance `dw doctor` pour le diagnostic exact.")
            for line in _protect_human_lines(protect, guided=True):
                print(line)
        else:
            adapters = ", ".join(expected) if expected else "none"
            print(f"Agent integration: {'ready' if healthy else 'not ready'} · adapters: {adapters}")
            print(
                f"Verification: {'ready' if verification.get('ready') else 'NOT READY'}"
                + (f" · {verification.get('command')}" if verification.get("command") else "")
            )
            for line in _protect_human_lines(protect, guided=False):
                print(line)
        return 0 if result.get("productReady") else 1

    if guided:
        print(f"✓ {_agent_names(expected)} connecté à DiffWitness.")
        print("Utilise ton agent normalement : DiffWitness vérifiera la modification exacte à la fin de la tâche.")
        if verification.get("ready"):
            print(f"✓ Vérification prête : {verification.get('command')}")
            print("Le projet est prêt pour une première tâche agentique.")
        else:
            print("⚠ L’intégration agent est prête, mais les vérifications du projet ne le sont pas encore.")
            if verification.get("suggestion"):
                print(f"Commande disponible suggérée : {verification['suggestion']} (non appliquée automatiquement)")
            print("Lance `dw doctor` pour terminer cette étape avant de considérer DiffWitness pleinement prêt.")
        for line in _protect_human_lines(protect, guided=True):
            print(line)
    else:
        adapters = ", ".join(expected) if expected else "none"
        print(f"Agent integration ready · adapters: {adapters}")
        print(
            f"Use {_agent_names(expected)} normally. Native Stop runs PROVE · OWE · UNDERSTAND · CONTINUITY; "
            "`dw guard` is a manual fallback only."
        )
        print(
            f"Verification {'ready' if verification.get('ready') else 'NOT READY'}"
            + (f" · {verification.get('command')}" if verification.get("command") else "")
        )
        if not verification.get("ready"):
            print("Run `dw doctor` before treating the project as fully ready.")
        for line in _protect_human_lines(protect, guided=False):
            print(line)
    return 0 if result.get("productReady") else 1


__all__ = ["SetupError", "setup_cli", "setup_install", "setup_status", "setup_uninstall"]
