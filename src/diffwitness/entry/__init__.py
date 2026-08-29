"""Public DiffWitness frontend and additive Project Continuity facade."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from ..frontend import FrontendError, main as _frontend_main


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _option_value(argv: list[str], name: str, default: str | None = None) -> str | None:
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return argv[index + 1]
        prefix = name + "="
        if value.startswith(prefix):
            return value[len(prefix) :]
    return default


def _root_help() -> str:
    from ..public_help import TECHNICAL_HELP, help_for_view

    try:
        from ..gitops import repo_root
        from ..view_mode import get_view_mode

        repo = repo_root(".")
        return help_for_view(get_view_mode(repo))
    except Exception:
        # Outside a repository, retain the established complete command surface.
        return TECHNICAL_HELP


def _sync_debt_continuity_best_effort(argv: list[str]) -> None:
    try:
        from ..continuity_debt_bridge import sync_debt_history
        from ..gitops import repo_root

        repo = repo_root(_option_value(argv, "--repo", ".") or ".")
        result = sync_debt_history(repo, explicit_config=_option_value(argv, "--config"))
        created = int(result.get("created") or 0)
        if created:
            print(f"Project continuity: {created} Debt Ledger lifecycle event(s) projected")
    except Exception as exc:
        print(f"Project continuity debt sync degraded: {str(exc)[:300]}", file=sys.stderr)


def _guard_with_continuity(argv: list[str]) -> int:
    from ..gitops import repo_root
    from ..guard import guard_cli

    parser_repo = _option_value(argv, "--repo", ".") or "."
    try:
        repo = repo_root(parser_repo)
    except Exception:
        return guard_cli(argv)

    envelope_path = repo / ".git" / "diffwitness" / "change-envelope.json"
    before = _digest(envelope_path)
    rc = guard_cli(argv)
    after = _digest(envelope_path)
    if after is not None and after != before:
        try:
            from ..continuity_bridge import record_change_envelope
            from ..continuity_state import ensure_state

            result = record_change_envelope(
                repo=repo,
                path=envelope_path,
                actor="diffwitness-guard",
                trusted_proof=True,
            )
            ensure_state(repo)
            created = result.get("created") or {}
            total = sum(int(value or 0) for value in created.values())
            print(f"Project continuity: {total} new change event(s) · {result['change_id']}")
        except Exception as exc:
            print(f"Project continuity recording degraded: {str(exc)[:300]}", file=sys.stderr)

    _sync_debt_continuity_best_effort(argv)
    return rc


def _debt_command_with_continuity(command: str, argv: list[str]) -> int:
    rc = _frontend_main([command, *argv])
    _sync_debt_continuity_best_effort(argv)
    return rc


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(_root_help(), end="")
        return 0
    if args[0] == "view":
        from ..view_mode import view_cli

        return view_cli(args[1:])
    if args[0] == "status":
        from ..status_cli import status_cli

        return status_cli(args[1:])
    if args[0] == "setup":
        from ..setup import setup_cli

        return setup_cli(args[1:])
    if args[0] == "explain":
        from ..idleproof_explanation import explanation_cli

        return explanation_cli(args[1:])
    if args[0] == "portal":
        from ..portal_proxy import portal_cli

        return portal_cli(args[1:])
    if args[0] == "ide-hook":
        from ..ide_plugin import ide_hook_cli

        return ide_hook_cli(args[1:])
    if args[0] == "doctor":
        from ..doctor import doctor_cli

        return doctor_cli(args[1:])
    if args[0] == "engine":
        from ..engine_cli import engine_cli

        return engine_cli(args[1:])
    if args[0] == "guard":
        return _guard_with_continuity(args[1:])
    if args[0] in {"debt", "health", "repay", "recheck", "ledger"}:
        return _debt_command_with_continuity(args[0], args[1:])
    if args[0] == "state" and len(args) > 1 and args[1] in {"checkpoint", "restore", "pull", "push"}:
        from ..continuity_transport_cli import state_transport_cli

        return state_transport_cli(args[1:])
    if args[0] == "relation":
        from ..continuity_relation_cli import relation_cli

        return relation_cli(args[1:])
    if args[0] == "context":
        from ..continuity_context_command import context_command_cli

        return context_command_cli(args[1:])
    if args[0] in {"state", "objective", "decision", "invariant", "failed-approach"}:
        from ..continuity_cli import (
            decision_cli,
            failed_approach_cli,
            invariant_cli,
            objective_cli,
            state_cli,
        )

        handlers = {
            "state": state_cli,
            "objective": objective_cli,
            "decision": decision_cli,
            "invariant": invariant_cli,
            "failed-approach": failed_approach_cli,
        }
        return handlers[args[0]](args[1:])
    return _frontend_main(args)


__all__ = ["FrontendError", "main"]
