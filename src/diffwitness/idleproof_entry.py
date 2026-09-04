from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import idleproof_sidecar as _sidecar

_ORIGINAL_BUILD_PORTAL_SNAPSHOT = _sidecar.build_portal_snapshot
_ORIGINAL_INTEGRATION_INSTALL = _sidecar.integration_install
_ORIGINAL_ADAPTER_INSTALLED = _sidecar._adapter_installed
_ORIGINAL_INTEGRATION_UNINSTALL = _sidecar.integration_uninstall

_CLAUDE_EXEC_EVENTS = {
    "SessionStart": ("session-start", 10),
    "UserPromptSubmit": ("user-prompt-submit", 8),
    "Stop": ("session-stop", 900),
}


def _bounded_protection(repo: Path) -> dict[str, Any] | None:
    """Project only aggregate Protect metadata into the Portal privacy boundary.

    Individual receipts deliberately remain local because they may contain tool names and paths.
    The Portal gets mode/health/policy and aggregate decision counts only; these remain OBSERVED
    runtime metadata and are never promoted into DiffWitness assurance.
    """
    try:
        from .protect import protect_status

        status = protect_status(repo)
    except Exception:
        return None
    mode = str(status.get("mode") or "")
    policy = str(status.get("policy") or "")
    health = str(status.get("health") or "")
    if mode not in {"off", "builtin", "external"}:
        return None
    if policy not in {"observe", "standard", "strict"}:
        return None
    if health not in {"off", "ready", "delegated", "degraded", "invalid"}:
        return None
    receipts = status.get("receipts") if isinstance(status.get("receipts"), dict) else {}
    decisions = receipts.get("decisions") if isinstance(receipts.get("decisions"), dict) else {}

    def count(name: str) -> int:
        value = decisions.get(name, 0)
        return max(0, min(1_000_000, int(value))) if isinstance(value, int) and not isinstance(value, bool) else 0

    receipt_count = receipts.get("count", 0)
    total = max(0, min(1_000_000, int(receipt_count))) if isinstance(receipt_count, int) and not isinstance(receipt_count, bool) else 0
    blocked = count("block")
    observed = count("observed")
    asked = count("ask")
    # Defensive bounding: malformed local counters are never widened into the cloud contract.
    if blocked + observed + asked > total:
        return None
    return {
        "schema": "idleproof.protection-summary.v1",
        "mode": mode,
        "policy": policy,
        "health": health,
        "receiptCount": total,
        "receiptIntegrity": bool(receipts.get("integrity")),
        "blocked": blocked,
        "observed": observed,
        "asked": asked,
    }


def _claude_exec_args(action: str) -> list[str]:
    return ["ide-hook", action, "--provider", "claude"]


def _entry_hook(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return None
    for hook in hooks:
        if isinstance(hook, dict):
            return hook
    return None


def _is_claude_exec_entry(entry: Any, *, dw_command: str, action: str) -> bool:
    hook = _entry_hook(entry)
    if hook is None:
        return False
    args = hook.get("args")
    return hook.get("command") == dw_command and isinstance(args, list) and args == _claude_exec_args(action)


def _normalize_claude_exec_hooks(repo: Path, *, dw_command: str) -> None:
    """Persist Claude hooks in exec form so Windows never re-parses a native path in Git Bash.

    Claude Code runs shell-form hooks through Git Bash on Windows when Git Bash is installed. A
    native `C:\\...\\dw.exe ...` command string is therefore not a portable shell command. Supplying
    `args` makes Claude spawn the executable directly on every platform and removes shell quoting
    from this trust boundary.
    """
    path = repo / ".claude" / "settings.local.json"
    if not path.is_file():
        return
    data = _sidecar._read_json(path, required=True)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks

    for event, (action, timeout) in _CLAUDE_EXEC_EVENTS.items():
        entries = hooks.get(event)
        if not isinstance(entries, list):
            entries = []
        legacy_shell = _sidecar._shell_command(dw_command, "ide-hook", action, "--provider", "claude")
        kept: list[Any] = []
        for entry in entries:
            hook = _entry_hook(entry)
            if hook is not None and hook.get("command") == legacy_shell:
                continue
            if _is_claude_exec_entry(entry, dw_command=dw_command, action=action):
                continue
            kept.append(entry)
        kept.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": dw_command,
                        "args": _claude_exec_args(action),
                        "timeout": timeout,
                    }
                ]
            }
        )
        hooks[event] = kept
    _sidecar._write_json(path, data)


def _adapter_installed(repo: Path, adapter: str, dw_command: str) -> bool:
    if adapter != "claude":
        return _ORIGINAL_ADAPTER_INSTALLED(repo, adapter, dw_command)
    # Accept the legacy shell form while an existing install is being upgraded in place.
    if _ORIGINAL_ADAPTER_INSTALLED(repo, adapter, dw_command):
        return True
    path = repo / ".claude" / "settings.local.json"
    if not path.is_file():
        return False
    try:
        data = _sidecar._read_json(path, required=True)
    except Exception:
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event, (action, _timeout) in _CLAUDE_EXEC_EVENTS.items():
        entries = hooks.get(event)
        if not isinstance(entries, list) or not any(
            _is_claude_exec_entry(entry, dw_command=dw_command, action=action) for entry in entries
        ):
            return False
    return True


def integration_install(repo: Path, *, agent: str, dw_command: str) -> dict[str, Any]:
    status = _ORIGINAL_INTEGRATION_INSTALL(repo, agent=agent, dw_command=dw_command)
    if "claude" in (status.get("expectedAdapters") or []):
        state = _sidecar._read_json(_sidecar._integration_state_path(repo), required=True)
        installed_dw = str(state.get("diffwitnessCommand") or dw_command)
        _normalize_claude_exec_hooks(repo, dw_command=installed_dw)
        status = _sidecar.integration_status(repo)
        if not status.get("healthy"):
            raise _sidecar.IdleProofSidecarError("Claude exec-form hooks were written but health verification failed")
    return status


def integration_uninstall(repo: Path) -> None:
    state = _sidecar._read_json(_sidecar._integration_state_path(repo))
    dw_command = str(state.get("diffwitnessCommand") or shutil.which("dw") or "dw")
    created_files = state.get("createdFiles") if isinstance(state.get("createdFiles"), dict) else {}
    _ORIGINAL_INTEGRATION_UNINSTALL(repo)

    path = repo / ".claude" / "settings.local.json"
    if not path.is_file():
        return
    data = _sidecar._read_json(path, required=True)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, (action, _timeout) in _CLAUDE_EXEC_EVENTS.items():
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [
            entry
            for entry in entries
            if not _is_claude_exec_entry(entry, dw_command=dw_command, action=action)
        ]
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)

    rel = path.relative_to(repo).as_posix()
    only_empty_scaffold = not hooks and set(data) <= {"hooks", "version"}
    if bool(created_files.get(rel)) and only_empty_scaffold:
        try:
            path.unlink()
            return
        except OSError:
            pass
    _sidecar._write_json(path, data)


def build_portal_snapshot(repo: Path) -> dict[str, Any]:
    snapshot = _ORIGINAL_BUILD_PORTAL_SNAPSHOT(repo)
    privacy = snapshot.get("privacy") if isinstance(snapshot.get("privacy"), dict) else {}
    privacy["rawCommandsIncluded"] = False
    snapshot["privacy"] = privacy
    protection = _bounded_protection(repo)
    if protection is not None:
        snapshot["protection"] = protection
    else:
        snapshot.pop("protection", None)
    snapshot["snapshotId"] = _sidecar._snapshot_id(snapshot)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    # Sidecar functions resolve these collaborators from their module globals at call time. Keep
    # the established implementation and install only bounded public-entry compatibility shims.
    _sidecar.build_portal_snapshot = build_portal_snapshot
    _sidecar._adapter_installed = _adapter_installed
    _sidecar.integration_install = integration_install
    _sidecar.integration_uninstall = integration_uninstall
    return _sidecar.main(argv)


__all__ = ["build_portal_snapshot", "main"]
