"""Public DiffWitness frontend and additive Project Continuity facade."""

from __future__ import annotations

import difflib
import hashlib
import sys
from pathlib import Path

from ..frontend import FrontendError, main as _frontend_main


_PUBLIC_COMMANDS = {
    "setup", "status", "view", "protect", "explain", "portal", "doctor", "engine", "guard",
    "gate", "prove", "core", "debt", "health", "repay", "recheck", "ledger", "plan",
    "state", "objective", "decision", "invariant", "failed-approach", "relation", "context",
    "envelope", "verify", "note", "ide-hook",
}


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


def _root_help(*, explicit_view: str | None = None) -> str:
    from ..public_help import GUIDED_HELP, help_for_view

    if explicit_view in {"guided", "technical"}:
        return help_for_view(explicit_view)
    try:
        from ..gitops import repo_root
        from ..view_mode import get_view_mode

        repo = repo_root(".")
        return help_for_view(get_view_mode(repo))
    except Exception:
        return GUIDED_HELP


def _help_request(args: list[str]) -> str | None:
    if not args:
        return None
    if args[0] in {"-h", "--help"}:
        if len(args) > 1 and args[1] in {"technical", "guided"}:
            return args[1]
        return "auto"
    if args[0] == "help":
        if len(args) > 1 and args[1] in {"technical", "guided"}:
            return args[1]
        return "auto"
    return None


def _friendly_unknown(args: list[str]) -> int | None:
    if not args:
        return None
    token = args[0]
    if token.startswith("--") and len(token) > 2:
        likely = token[2:]
        if likely in _PUBLIC_COMMANDS:
            print(f"Unknown top-level option: {token}", file=sys.stderr)
            print(f"Did you mean `dw {likely}`?", file=sys.stderr)
            return 2
        print(f"Unknown top-level option: {token}", file=sys.stderr)
        print("Run `dw --help` for the current command surface.", file=sys.stderr)
        return 2
    if token.startswith("-"):
        print(f"Unknown top-level option: {token}", file=sys.stderr)
        print("Run `dw --help` for the current command surface.", file=sys.stderr)
        return 2
    if token not in _PUBLIC_COMMANDS:
        matches = difflib.get_close_matches(token, sorted(_PUBLIC_COMMANDS), n=1, cutoff=0.68)
        if matches:
            print(f"Unknown command: {token}", file=sys.stderr)
            print(f"Did you mean `dw {matches[0]}`?", file=sys.stderr)
            return 2
    return None


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


def _explain(argv: list[str]) -> int:
    engine = _option_value(argv, "--engine", "deterministic") or "deterministic"
    if engine == "deterministic":
        cleaned: list[str] = []
        skip = False
        for index, value in enumerate(argv):
            if skip:
                skip = False
                continue
            if value == "--engine" and index + 1 < len(argv):
                skip = True
                continue
            if value.startswith("--engine="):
                continue
            cleaned.append(value)
        from ..explain_ui import explain_ui_cli
        return explain_ui_cli(cleaned)
    from ..idleproof_user_inference import user_inference_cli
    return user_inference_cli(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(_root_help(), end="")
        return 0
    help_view = _help_request(args)
    if help_view is not None:
        print(_root_help(explicit_view=None if help_view == "auto" else help_view), end="")
        return 0

    friendly = _friendly_unknown(args)
    if friendly is not None:
        return friendly

    if args[0] == "view":
        from ..view_mode import view_cli
        return view_cli(args[1:])
    if args[0] == "status":
        from ..status_cli import status_cli
        return status_cli(args[1:])
    if args[0] == "setup":
        from ..setup import setup_cli
        return setup_cli(args[1:])
    if args[0] == "protect":
        from ..protect_ui import protect_surface_cli
        return protect_surface_cli(args[1:])
    if args[0] == "explain":
        return _explain(args[1:])
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
        from ..continuity_cli import decision_cli, failed_approach_cli, invariant_cli, objective_cli, state_cli

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
