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


def _with_provider(payload: dict[str, Any], provider: str | None) -> dict[str, Any]:
    if provider is not None:
        payload["provider"] = provider
    return payload


def _user_prompt_submit(provider: str | None) -> int:
    """Delegate to the canonical native bridge so plugin and installed-sidecar behavior cannot drift."""
    payload = _with_provider(_read_hook_payload(), provider)
    try:
        from diffwitness.ide_plugin import user_prompt_submit

        result = user_prompt_submit(payload)
    except Exception:
        # Project context is advisory. A degraded context helper must not break the coding session.
        return 0
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


def _protect(command: str, provider: str | None) -> int:
    payload = _with_provider(_read_hook_payload(), provider)
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


def _session_start(provider: str | None) -> int:
    payload = _with_provider(_read_hook_payload(), provider)
    try:
        from diffwitness.ide_plugin import session_start

        session_start(payload)
    except Exception as exc:
        # Start capture has no truthful success payload to manufacture. Make the failure visible;
        # the Stop boundary will also fail closed instead of launching a nested fallback agent.
        print(
            f"DiffWitness could not arm SessionStart: {type(exc).__name__}: {str(exc)[:800]}",
            file=sys.stderr,
        )
        return 1
    return 0


def _session_stop(provider: str | None) -> int:
    payload = _with_provider(_read_hook_payload(), provider)
    policy = os.environ.get("DIFFWITNESS_POLICY", "balanced")
    try:
        from diffwitness.ide_plugin import session_stop

        result = session_stop(payload, policy=policy)
    except Exception as exc:
        message = (
            "DiffWitness integrated handoff failed before evidence could be established and this "
            f"task remains unverified: {str(exc)[:1200]}"
        )
        result = {"continue": False, "stopReason": message, "systemMessage": message}
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
    tail = sys.argv[2:]
    provider: str | None = None
    if tail:
        if len(tail) != 2 or tail[0] != "--provider" or tail[1] not in {"claude", "codex", "cursor"}:
            print("DiffWitness plugin hook accepts only --provider claude|codex|cursor after the event", file=sys.stderr)
            return 2
        provider = tail[1]
    if command in {"protect-pre", "protect-post"} and provider not in {"claude", "codex"}:
        print("DiffWitness Protect plugin hooks require --provider claude or codex", file=sys.stderr)
        return 2
    if command == "session-start":
        return _session_start(provider)
    if command == "user-prompt-submit":
        return _user_prompt_submit(provider)
    if command in {"protect-pre", "protect-post"}:
        return _protect(command, provider)
    return _session_stop(provider)


if __name__ == "__main__":
    raise SystemExit(run())
