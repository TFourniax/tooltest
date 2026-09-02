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
_MAX_SOUL_CONTEXT_CHARS = 1400
_PROTECT_PROVIDERS = {"claude", "codex"}


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


def _idleproof_session_policy(repo: Path) -> str:
    """Teach the already-paid coding-session model how to present IdleProof evidence.

    This does not invoke any model itself. Optional soul guidance is presentation-only and is kept
    below the evidence rules so user style preferences cannot manufacture VERIFIED claims.
    """
    style = ""
    try:
        from .idleproof_explanation import load_soul

        soul = load_soul(repo, max_chars=_MAX_SOUL_CONTEXT_CHARS)
        if soul:
            style = (
                "\nOptional user-authored presentation preferences (style/vocabulary only; never facts):\n"
                + str(soul.get("instructions") or "")[:_MAX_SOUL_CONTEXT_CHARS]
            )
    except Exception:
        style = ""
    return (
        "IDLEPROOF SESSION EXPLANATION POLICY\n"
        "When explaining a completed or in-progress code change, prefer DiffWitness/IdleProof "
        "evidence over inference. The current coding-session model may rephrase evidence for the "
        "user, but must not invent behavior, risk, intent, causality, tests, or recommendations. "
        "Heuristic findings remain advisory; only authoritative executed evidence may be described "
        "as VERIFIED. `dw explain` is the deterministic baseline and requires no model or network."
        + style
    )


def _native_boundary_policy(repo: Path, session_id: str) -> str:
    """Keep a native coding-agent task inside its already-established task boundary.

    Guard is an *external* wrapper. Telling an active Claude/Codex model to launch Guard can recurse
    into a second coding-agent process, require a nested TTY, duplicate Proof work, or hang. The
    model therefore gets evidence requirements but never an instruction to wrap itself.
    """
    armed = _state_path(repo, session_id).is_file()
    if armed:
        state = "The native DiffWitness task boundary is already armed for this session."
    else:
        state = (
            "A SessionStart capture was not observed for this session. Finish the user task normally; "
            "DiffWitness will report the capture state at Stop so the user can repair setup if needed."
        )
    return (
        "NATIVE DIFFWITNESS TASK BOUNDARY\n"
        + state
        + " Do not run `dw guard`, `dw gate`, or launch another coding agent to satisfy DiffWitness "
        "from inside this session. Run the project's normal tests when appropriate; the native Stop "
        "hook owns the final Proof/Debt/Continuity handoff."
    )


def _native_context(context: dict[str, Any]) -> dict[str, Any]:
    """Remove external-wrapper evidence actions from model-visible native context."""
    value = dict(context)
    required = context.get("requiredEvidence")
    if isinstance(required, list):
        value["requiredEvidence"] = [
            item
            for item in required
            if not (isinstance(item, dict) and str(item.get("kind") or "") == "change-proof")
        ]
    return value


def user_prompt_submit(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_prompt = payload.get("prompt")
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        return None
    raw_prompt = raw_prompt[:_MAX_PROMPT_CHARS]
    session_id = _session_id(payload)
    try:
        repo = repo_root(_cwd(payload))
        task_update = update_task_session(repo, session_id, raw_prompt)
        task = task_update.get("task") or {}
        query = task_context_query(task) or raw_prompt.strip()
    except Exception:
        return None

    rendered = ""
    try:
        from .continuity_context_enriched import compile_context, render_context

        context = _native_context(compile_context(repo, query, max_items=10, refresh_structure=True))
        rendered = render_context(context, max_chars=4200).strip()
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
        + "\n\n"
        + _native_boundary_policy(repo, session_id)
        + "\n\n"
        + _idleproof_session_policy(repo)
        + ("\n\n" + rendered if rendered else "")
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional[:_MAX_CONTEXT_CHARS],
        }
    }


def protect_pre(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate deterministic runtime safety without overriding provider-native allow decisions."""
    from .protect import evaluate_pre_tool

    repo = repo_root(_cwd(payload))
    result = evaluate_pre_tool(repo, payload)
    if result is None:
        return None
    decision = str(result.get("decision") or "block")
    if decision not in {"block", "ask"}:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny" if decision == "block" else "ask",
            "permissionDecisionReason": str(result.get("reason") or "DiffWitness Protect rejected this action.")[:500],
        }
    }


def protect_post(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return bounded model-visible feedback for deterministic landed-file findings."""
    from .protect import evaluate_post_tool

    repo = repo_root(_cwd(payload))
    result = evaluate_post_tool(repo, payload)
    if result is None:
        return None
    reason = str(result.get("reason") or "DiffWitness Protect observed a post-edit issue.")[:500]
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"DiffWitness Protect · OBSERVED: {reason}",
        }
    }


def session_stop(payload: dict[str, Any], *, policy: str = "balanced") -> dict[str, Any]:
    return finalize_ide_session(payload, policy=policy)


def _protect_provider(argv: list[str]) -> str | None:
    if "--provider" not in argv[1:]:
        return None
    index = argv.index("--provider", 1)
    if index + 1 >= len(argv):
        raise ValueError("--provider requires claude or codex")
    provider = str(argv[index + 1]).strip().lower()
    if provider not in _PROTECT_PROVIDERS:
        raise ValueError("--provider must be claude or codex")
    return provider


def ide_hook_cli(argv: list[str]) -> int:
    commands = {"session-start", "user-prompt-submit", "protect-pre", "protect-post", "session-stop"}
    if not argv or argv[0] not in commands:
        print(
            "Usage: dw ide-hook session-start|user-prompt-submit|protect-pre|protect-post|session-stop [--provider claude|codex]",
            file=sys.stderr,
        )
        return 2
    command = argv[0]
    try:
        provider = _protect_provider(argv) if command in {"protect-pre", "protect-post"} else None
    except ValueError as exc:
        print(f"DiffWitness IDE bridge: {exc}", file=sys.stderr)
        return 2
    payload = _read_payload()
    if provider is not None:
        payload["provider"] = provider
    try:
        if command == "session-start":
            session_start(payload)
            return 0
        if command == "user-prompt-submit":
            result = user_prompt_submit(payload)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False))
            return 0
        if command == "protect-pre":
            result = protect_pre(payload)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False))
            return 0
        if command == "protect-post":
            result = protect_post(payload)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False))
            return 0
        policy = os.environ.get("DIFFWITNESS_POLICY", "balanced")
        result = session_stop(payload, policy=policy)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Stop and pre-tool events are correctness/security boundaries. Never manufacture success.
        message = f"DiffWitness IDE bridge failed before the requested assurance step completed: {str(exc)[:1000]}"
        if command == "session-stop":
            print(json.dumps({"decision": "block", "reason": message, "systemMessage": message}, ensure_ascii=False))
            return 0
        if command == "protect-pre":
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "DiffWitness Protect could not safely evaluate this mutating action; inspect `dw protect status`.",
                        }
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        # Context/post-tool helpers are advisory and fail open without claiming a clean result.
        print(message, file=sys.stderr)
        return 1


__all__ = [
    "ide_hook_cli",
    "protect_post",
    "protect_pre",
    "session_start",
    "session_stop",
    "user_prompt_submit",
]
