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

from diffwitness.proof_cli import main  # noqa: E402


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
    """Inject deterministic local Project Continuity context for the exact submitted task.

    This path is deliberately fail-open: Context is advisory. A context compiler problem must not
    block the user's prompt or weaken the authoritative Stop/Guard evidence boundary. The prompt is
    used transiently for relevance selection and is never appended to ProjectEvent history.
    """
    payload = _read_hook_payload()
    raw_prompt = payload.get("prompt")
    cwd = payload.get("cwd") or "."
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        return 0
    task = raw_prompt.strip()[:_MAX_PROMPT_CHARS]
    try:
        from diffwitness.continuity_context_enriched import compile_context, render_context

        context = compile_context(cwd, task, max_items=10, refresh_structure=True)
        rendered = render_context(context, max_chars=_MAX_CONTEXT_CHARS).strip()
    except Exception:
        return 0
    if not rendered:
        return 0
    additional = (
        "DIFFWITNESS PROJECT CONTINUITY (advisory, local, bounded)\n"
        "Use these project facts as relevant context for the submitted task. Epistemic labels matter: "
        "DECLARED is project intent, INFERRED is heuristic, OBSERVED is directly recorded/parsed, and "
        "VERIFIED is backed by authoritative executed evidence. Do not upgrade a weaker status.\n\n"
        + rendered
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


def run() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"session-start", "session-stop", "user-prompt-submit"}:
        print(
            "DiffWitness plugin hook requires session-start, session-stop, or user-prompt-submit",
            file=sys.stderr,
        )
        return 2
    command = sys.argv[1]
    if command == "user-prompt-submit":
        return _user_prompt_submit()
    policy = os.environ.get("DIFFWITNESS_POLICY", "balanced")
    args = [command]
    if command == "session-stop":
        args += ["--policy", policy]
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
