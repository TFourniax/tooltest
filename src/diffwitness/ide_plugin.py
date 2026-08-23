from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .continuity_task_session import task_context_query, update_task_session
from .gitops import repo_root, snapshot_worktree
from .ide_handoff import finalize_ide_session
from .proof_cli import _state_path

_MAX_PROMPT_CHARS = 12000
_MAX_CONTEXT_CHARS = 6500


def _read_payload() -> dict[str, Any]:
    try:
        if sys.stdin.isatty():
            return {}
    except OSError:
        return {}
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _cwd(payload: dict[str, Any]) -> str:
    return str(
        payload.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.environ.get("CURSOR_PROJECT_DIR")
        or "."
    )


def _session_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("session_id")
        or payload.get("conversation_id")
        or payload.get("parent_conversation_id")
        or "default"
    )


def session_start(payload: dict[str, Any]) -> dict[str, Any] | None:
    repo = repo_root(_cwd(payload))
    session_id = _session_id(payload)
    state = {"base": snapshot_worktree(repo), "retries": 0, "repo": str(repo)}
    path = _state_path(repo, session_id)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text(json.dumps(state), encoding="utf-8")
    staged.replace(path)
    return None


def user_prompt_submit(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_prompt = payload.get("prompt")
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        return None
    raw_prompt = raw_prompt[:_MAX_PROMPT_CHARS]
    try:
        repo = repo_root(_cwd(payload))
        task_update = update_task_session(repo, _session_id(payload), raw_prompt)
        task = task_update.get("task") or {}
        query = task_context_query(task) or raw_prompt.strip()
    except Exception:
        return None

    rendered = ""
    try:
        from .continuity_context_enriched import compile_context, render_context

        context = compile_context(repo, query, max_items=10, refresh_structure=True)
        rendered = render_context(context, max_chars=5200).strip()
    except Exception:
        rendered = ""

    task_id = str(task.get("id") or "")
    anchor = str(task.get("anchor") or "").strip()
    focus = str(task.get("latest_focus") or "").strip()
    task_lines = [
        f"ACTIVE TASK {task_id}" if task_id else "ACTIVE TASK",
        f"Primary objective: {anchor}" if anchor else None,
        f"Current focus: {focus}" if focus and focus != anchor else None,
    ]
    additional = (
        "DIFFWITNESS PROJECT CONTINUITY (advisory, local, bounded)\n"
        "A turn is not automatically a new task. Preserve this active task identity across short "
        "follow-ups. Epistemic labels matter: DECLARED is project intent, INFERRED is heuristic, "
        "OBSERVED is directly recorded/parsed, and VERIFIED is backed by authoritative executed "
        "evidence. Never upgrade a weaker status.\n\n"
        + "\n".join(line for line in task_lines if line)
        + ("\n\n" + rendered if rendered else "")
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional[:_MAX_CONTEXT_CHARS],
        }
    }


def session_stop(payload: dict[str, Any], *, policy: str = "balanced") -> dict[str, Any]:
    return finalize_ide_session(payload, policy=policy)


def ide_hook_cli(argv: list[str]) -> int:
    if not argv or argv[0] not in {"session-start", "user-prompt-submit", "session-stop"}:
        print("Usage: dw ide-hook session-start|user-prompt-submit|session-stop", file=sys.stderr)
        return 2
    command = argv[0]
    payload = _read_payload()
    try:
        if command == "session-start":
            session_start(payload)
            return 0
        if command == "user-prompt-submit":
            result = user_prompt_submit(payload)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False))
            return 0
        policy = os.environ.get("DIFFWITNESS_POLICY", "balanced")
        result = session_stop(payload, policy=policy)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        # A packaged orchestrator must never manufacture VERIFIED evidence after an internal error.
        # For stop events, fail closed so the coding agent cannot silently report success.
        message = f"DiffWitness IDE bridge failed before evidence could be established: {str(exc)[:1200]}"
        if command == "session-stop":
            print(json.dumps({"decision": "block", "reason": message, "systemMessage": message}, ensure_ascii=False))
            return 0
        print(message, file=sys.stderr)
        return 1


__all__ = ["ide_hook_cli", "session_start", "session_stop", "user_prompt_submit"]
