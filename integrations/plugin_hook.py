from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _plugin_root() -> Path:
    explicit = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if explicit:
        return Path(explicit).resolve()
    return Path(__file__).resolve().parents[1]


ROOT = _plugin_root()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from diffwitness.proof_cli import main as proof_main  # noqa: E402


_MAX_PROMPT_CHARS = 12000
_MAX_CONTEXT_CHARS = 6500


def _read_hook_payload() -> dict[str, Any]:
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


def _user_prompt_submit() -> int:
    """Inject deterministic Project Continuity for the stable task represented by this IDE session.

    A conversation turn is not automatically a new task. The raw prompt is used only in local,
    temporary task-session state and for relevance selection; it is never appended to ProjectEvent
    history. Context remains advisory and failure remains fail-open.
    """
    payload = _read_hook_payload()
    raw_prompt = payload.get("prompt")
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CURSOR_PROJECT_DIR") or "."
    session_id = str(payload.get("session_id") or payload.get("conversation_id") or "default")
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        return 0
    raw_prompt = raw_prompt[:_MAX_PROMPT_CHARS]
    try:
        from diffwitness.continuity_task_session import task_context_query, update_task_session
        from diffwitness.gitops import repo_root

        repo = repo_root(cwd)
        task_update = update_task_session(repo, session_id, raw_prompt)
        task = task_update.get("task") or {}
        query = task_context_query(task) or raw_prompt.strip()
    except Exception:
        return 0

    rendered = ""
    try:
        from diffwitness.continuity_context_enriched import compile_context, render_context

        context = compile_context(repo, query, max_items=10, refresh_structure=True)
        rendered = render_context(context, max_chars=5200).strip()
    except Exception:
        # Task identity is still useful and local even when a project index is temporarily degraded.
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
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": additional[:_MAX_CONTEXT_CHARS],
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


def _protect(command: str) -> int:
    """Run the native Protect evaluator; off/external modes intentionally produce no hook output."""
    payload = _read_hook_payload()
    try:
        from diffwitness.ide_plugin import protect_post, protect_pre

        result = protect_pre(payload) if command == "protect-pre" else protect_post(payload)
    except Exception:
        if command == "protect-pre":
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": (
                                "DiffWitness Protect could not safely evaluate this mutating action; "
                                "inspect `dw protect status`."
                            ),
                        }
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        return 0
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def _session_stop() -> int:
    """Converge native IDE completion on Proof + Debt + Continuity + optional IdleProof Portal."""
    payload = _read_hook_payload()
    policy = os.environ.get("DIFFWITNESS_POLICY", "balanced")
    try:
        from diffwitness.ide_handoff import finalize_ide_session

        result = finalize_ide_session(payload, policy=policy)
    except Exception as exc:
        # Unknown handoff failures are not silently upgraded to successful evidence. This is a
        # correctness boundary: the agent may continue, while the user receives an actionable
        # failure instead of a false "proved" state.
        message = f"DiffWitness integrated handoff failed before evidence could be established: {str(exc)[:1200]}"
        result = {"decision": "block", "reason": message, "systemMessage": message}
    print(json.dumps(result, ensure_ascii=False))
    return 0


def run() -> int:
    commands = {"session-start", "session-stop", "user-prompt-submit", "protect-pre", "protect-post"}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(
            "DiffWitness plugin hook requires session-start, user-prompt-submit, protect-pre, protect-post, or session-stop",
            file=sys.stderr,
        )
        return 2
    command = sys.argv[1]
    if command == "user-prompt-submit":
        return _user_prompt_submit()
    if command in {"protect-pre", "protect-post"}:
        return _protect(command)
    if command == "session-stop":
        return _session_stop()
    return proof_main(["session-start"])


if __name__ == "__main__":
    raise SystemExit(run())
