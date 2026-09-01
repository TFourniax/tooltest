from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .gitops import repo_root

PROTECT_SCHEMA = "diffwitness.protect-config.v1"
RECEIPT_SCHEMA = "diffwitness.protection-receipt.v1"
SUMMARY_SCHEMA = "diffwitness.protection-summary.v1"
MODES = ("off", "builtin", "external")
POLICIES = ("observe", "standard", "strict")
SUPPORTED_ADAPTERS = ("claude", "codex")
_MAX_CONTENT_SCAN = 2 * 1024 * 1024
_MAX_RECEIPTS = 2000

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,200}\b")),
    ("generic-api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,200}\b")),
)

_HIGH_CONFIDENCE_HARNESS_MARKERS = (
    ".interlinked",
    ".sondera",
)

_DEPENDENCY_RE = re.compile(
    r"(?:^|\s)(?:npm|pnpm|yarn)\s+(?:add|install)\b|"
    r"(?:^|\s)(?:pip|pip3|python\s+-m\s+pip)\s+install\b|"
    r"(?:^|\s)cargo\s+add\b|(?:^|\s)go\s+get\b",
    re.IGNORECASE,
)
_PIPE_TO_SHELL_RE = re.compile(
    r"\b(?:curl|wget)\b[^\n|]{0,1000}\|\s*(?:sudo\s+)?(?:sh|bash|zsh|fish|pwsh|powershell)\b",
    re.IGNORECASE,
)
_DROP_DATABASE_RE = re.compile(r"\bDROP\s+(?:DATABASE|SCHEMA)\b", re.IGNORECASE)


class ProtectError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _state_dir(repo: Path) -> Path:
    return repo / ".git" / "diffwitness"


def _config_path(repo: Path) -> Path:
    return _state_dir(repo) / "protect.json"


def _receipts_path(repo: Path) -> Path:
    return _state_dir(repo) / "protection.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtectError(f"cannot read Protect state: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtectError("Protect state root must be an object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    staged.replace(path)


def load_protect_config(repo: Path) -> dict[str, Any]:
    raw = _read_json(_config_path(repo))
    if not raw:
        return {
            "schema": PROTECT_SCHEMA,
            "mode": "off",
            "policy": "standard",
            "adapters": [],
            "managedHooks": {},
        }
    if raw.get("schema") != PROTECT_SCHEMA:
        raise ProtectError("unsupported Protect configuration schema")
    mode = str(raw.get("mode") or "off")
    policy = str(raw.get("policy") or "standard")
    if mode not in MODES or policy not in POLICIES:
        raise ProtectError("invalid Protect mode or policy")
    adapters = [
        str(item)
        for item in raw.get("adapters", [])
        if str(item) in SUPPORTED_ADAPTERS
    ]
    return {
        **raw,
        "mode": mode,
        "policy": policy,
        "adapters": list(dict.fromkeys(adapters)),
        "managedHooks": raw.get("managedHooks") if isinstance(raw.get("managedHooks"), dict) else {},
    }


def _adapter_path(repo: Path, adapter: str) -> Path:
    if adapter == "claude":
        return repo / ".claude" / "settings.local.json"
    if adapter == "codex":
        return repo / ".codex" / "hooks.json"
    raise ProtectError(f"unsupported Protect adapter: {adapter}")


def _entry_command(entry: Mapping[str, Any]) -> str | None:
    direct = entry.get("command")
    if isinstance(direct, str):
        return direct
    hooks = entry.get("hooks")
    if isinstance(hooks, list):
        for item in hooks:
            if isinstance(item, Mapping) and isinstance(item.get("command"), str):
                return str(item["command"])
    return None


def _managed_command(dw_command: str, event: str, provider: str | None = None) -> str:
    values = [dw_command, "ide-hook", event]
    if provider is not None:
        if provider not in SUPPORTED_ADAPTERS:
            raise ProtectError(f"unsupported Protect provider: {provider}")
        values.extend(["--provider", provider])
    if os.name == "nt":
        import subprocess
        return subprocess.list2cmdline(values)
    return " ".join(shlex.quote(value) for value in values)


def _hook_entry(command: str, timeout: int) -> dict[str, Any]:
    return {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}


def _read_hook_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtectError(f"refusing to modify unreadable hook file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtectError(f"refusing to modify non-object hook file {path}")
    return value


def _write_hook_file(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text(json.dumps(dict(value), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    staged.replace(path)


def _resolve_dw_command() -> str:
    configured = os.environ.get("DIFFWITNESS_BIN")
    if configured:
        return configured
    return shutil.which("dw") or "dw"


def _detect_adapters(repo: Path) -> list[str]:
    found: list[str] = []
    if (repo / ".claude").exists() or shutil.which("claude"):
        found.append("claude")
    if (repo / ".codex").exists() or shutil.which("codex"):
        found.append("codex")
    return found


def detect_external_harness(repo: Path) -> dict[str, Any]:
    signals: list[dict[str, str]] = []
    for marker in _HIGH_CONFIDENCE_HARNESS_MARKERS:
        if (repo / marker).exists():
            signals.append({"kind": "marker", "path": marker, "confidence": "high"})

    for adapter in SUPPORTED_ADAPTERS:
        path = _adapter_path(repo, adapter)
        if not path.is_file():
            continue
        try:
            data = _read_hook_file(path)
        except ProtectError:
            signals.append(
                {
                    "kind": "hook-file",
                    "path": path.relative_to(repo).as_posix(),
                    "confidence": "unknown",
                }
            )
            continue
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            continue
        foreign = 0
        for entries in hooks.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                command = (_entry_command(entry) or "").lower()
                if command and "diffwitness" not in command and "dw ide-hook" not in command:
                    foreign += 1
        if foreign:
            signals.append(
                {
                    "kind": "foreign-hooks",
                    "path": path.relative_to(repo).as_posix(),
                    "confidence": "medium",
                }
            )
    high = any(item["confidence"] == "high" for item in signals)
    return {
        "schema": "diffwitness.protect-detection.v1",
        "externalHarnessDetected": high,
        "otherHookActivityDetected": any(item["kind"] == "foreign-hooks" for item in signals),
        "signals": signals,
        "recommendation": "external" if high else "builtin",
    }


def _install_hooks(repo: Path, adapters: Iterable[str], *, dw_command: str) -> dict[str, bool]:
    created: dict[str, bool] = {}
    for adapter in adapters:
        pre = _managed_command(dw_command, "protect-pre", adapter)
        post = _managed_command(dw_command, "protect-post", adapter)
        path = _adapter_path(repo, adapter)
        existed = path.exists()
        data = _read_hook_file(path)
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            hooks = {}
            data["hooks"] = hooks
        for event, command, timeout in (
            ("PreToolUse", pre, 3),
            ("PostToolUse", post, 4),
        ):
            entries = hooks.get(event)
            if not isinstance(entries, list):
                entries = []
                hooks[event] = entries
            if not any(
                isinstance(item, Mapping) and _entry_command(item) == command
                for item in entries
            ):
                entries.append(_hook_entry(command, timeout))
        _write_hook_file(path, data)
        created[path.relative_to(repo).as_posix()] = not existed
    return created


def _remove_hooks(repo: Path, config: Mapping[str, Any]) -> None:
    dw_command = str(config.get("diffwitnessCommand") or _resolve_dw_command())
    commands = {
        _managed_command(dw_command, "protect-pre"),
        _managed_command(dw_command, "protect-post"),
    }
    for provider in SUPPORTED_ADAPTERS:
        commands.add(_managed_command(dw_command, "protect-pre", provider))
        commands.add(_managed_command(dw_command, "protect-post", provider))
    created = config.get("managedHooks") if isinstance(config.get("managedHooks"), Mapping) else {}
    adapters = config.get("adapters") if isinstance(config.get("adapters"), list) else list(SUPPORTED_ADAPTERS)
    for adapter in adapters:
        if adapter not in SUPPORTED_ADAPTERS:
            continue
        path = _adapter_path(repo, str(adapter))
        if not path.is_file():
            continue
        data = _read_hook_file(path)
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            continue
        for event in list(hooks):
            entries = hooks.get(event)
            if not isinstance(entries, list):
                continue
            kept = [
                item
                for item in entries
                if not (isinstance(item, Mapping) and _entry_command(item) in commands)
            ]
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)
        rel = path.relative_to(repo).as_posix()
        scaffold = not hooks and set(data) <= {"hooks", "version"}
        if bool(created.get(rel)) and scaffold:
            try:
                path.unlink()
                continue
            except OSError:
                pass
        _write_hook_file(path, data)


def set_protect_mode(
    repo: Path,
    mode: str,
    *,
    policy: str = "standard",
    force: bool = False,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ProtectError(f"Protect mode must be one of: {', '.join(MODES)}")
    if policy not in POLICIES:
        raise ProtectError(f"Protect policy must be one of: {', '.join(POLICIES)}")
    previous = load_protect_config(repo)
    if previous.get("mode") == "builtin":
        _remove_hooks(repo, previous)

    detection = detect_external_harness(repo)
    if mode == "builtin" and detection["externalHarnessDetected"] and not force:
        mode = "external"

    adapters = _detect_adapters(repo) if mode == "builtin" else []
    dw_command = _resolve_dw_command()
    managed: dict[str, bool] = {}
    if mode == "builtin":
        managed = _install_hooks(repo, adapters, dw_command=dw_command)

    config = {
        "schema": PROTECT_SCHEMA,
        "mode": mode,
        "policy": policy,
        "adapters": adapters,
        "managedHooks": managed,
        "diffwitnessCommand": dw_command,
        "externalDetection": detection,
        "updatedAt": _now(),
    }
    _write_json(_config_path(repo), config)
    return protect_status(repo)


def _hook_installed(repo: Path, adapter: str, config: Mapping[str, Any]) -> bool:
    path = _adapter_path(repo, adapter)
    if not path.is_file():
        return False
    try:
        data = _read_hook_file(path)
    except ProtectError:
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    dw_command = str(config.get("diffwitnessCommand") or _resolve_dw_command())
    expected = {
        _managed_command(dw_command, "protect-pre", adapter),
        _managed_command(dw_command, "protect-post", adapter),
    }
    found: set[str] = set()
    for event in ("PreToolUse", "PostToolUse"):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, Mapping):
                command = _entry_command(item)
                if command in expected:
                    found.add(str(command))
    return found == expected


def protect_status(repo: Path) -> dict[str, Any]:
    config = load_protect_config(repo)
    mode = str(config["mode"])
    detection = detect_external_harness(repo)
    adapters = list(config.get("adapters") or [])
    receipt_values, _ = _iter_receipts(repo)
    enabled_at = str(config.get("updatedAt") or "")
    active_providers = {
        str(item.get("provider"))
        for item in receipt_values
        if str(item.get("provider")) in SUPPORTED_ADAPTERS
        and (not enabled_at or str(item.get("ts") or "") >= enabled_at)
    }
    details: dict[str, dict[str, Any]] = {}
    for adapter in adapters:
        installed = _hook_installed(repo, adapter, config)
        active_seen = adapter in active_providers
        requires_activation = adapter == "codex" and not active_seen
        details[adapter] = {
            "path": _adapter_path(repo, adapter).relative_to(repo).as_posix(),
            "installed": installed,
            "activeSeen": active_seen,
            "ready": installed and not requires_activation,
            "activation": (
                "observed"
                if active_seen
                else "requires-provider-feature-and-trust"
                if adapter == "codex"
                else "installed"
            ),
        }
    if mode == "builtin":
        health = "ready" if adapters and all(item["ready"] for item in details.values()) else "degraded"
    elif mode == "external":
        health = "delegated"
    else:
        health = "off"
    summary = protection_summary(repo)
    return {
        "schema": "diffwitness.protect-status.v1",
        "mode": mode,
        "policy": config["policy"],
        "health": health,
        "enabled": mode == "builtin",
        "delegated": mode == "external",
        "adapters": details,
        "externalHarnessDetected": detection["externalHarnessDetected"],
        "otherHookActivityDetected": detection["otherHookActivityDetected"],
        "receipts": summary,
    }


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _receipt_lock_path(repo: Path) -> Path:
    return _state_dir(repo) / "protection.lock"


@contextmanager
def _receipt_lock(repo: Path, *, timeout: float = 10.0):
    path = _receipt_lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime > 60.0
            except OSError:
                stale = False
            if stale:
                try:
                    path.unlink()
                    continue
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                raise ProtectError("timed out waiting for the Protect receipt lock")
            time.sleep(0.02)
    try:
        os.write(fd, f"{os.getpid()}\n".encode("ascii", errors="ignore"))
    finally:
        os.close(fd)
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _last_receipt_hash(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProtectError(f"cannot read Protect receipt tail: {exc}") from exc
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProtectError("refusing to extend a damaged Protect receipt chain") from exc
        if not isinstance(value, dict) or value.get("schema") != RECEIPT_SCHEMA:
            raise ProtectError("refusing to extend an invalid Protect receipt chain")
        claimed = value.get("hash")
        if not isinstance(claimed, str):
            raise ProtectError("refusing to extend a Protect receipt chain with no tail hash")
        stable = dict(value)
        stable.pop("hash", None)
        stable.pop("id", None)
        calculated = hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()
        if claimed != calculated:
            raise ProtectError("refusing to extend a tampered Protect receipt chain")
        return claimed
    return None


def append_receipt(
    repo: Path,
    *,
    payload: Mapping[str, Any],
    phase: str,
    decision: str,
    category: str,
    rule: str,
    message: str,
    path: str | None = None,
) -> dict[str, Any]:
    receipt_path = _receipts_path(repo)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    session = str(
        payload.get("session_id")
        or payload.get("sessionId")
        or payload.get("conversation_id")
        or payload.get("conversationId")
        or "unknown"
    )
    tool = str(
        payload.get("tool_name")
        or payload.get("toolName")
        or payload.get("tool")
        or "unknown"
    )[:80]
    provider = str(payload.get("provider") or payload.get("agent") or "unknown")[:40]
    with _receipt_lock(repo):
        previous = _last_receipt_hash(receipt_path)
        stable = {
            "schema": RECEIPT_SCHEMA,
            "ts": _now(),
            "sessionDigest": hashlib.sha256(session.encode("utf-8")).hexdigest()[:16],
            "provider": provider,
            "phase": phase[:24],
            "decision": decision[:24],
            "category": category[:80],
            "rule": rule[:100],
            "tool": tool,
            "path": path[:300] if isinstance(path, str) else None,
            "message": message[:240],
            "prev": previous,
        }
        digest = hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()
        receipt = {**stable, "id": "dwpr_" + digest[:20], "hash": digest}
        try:
            with receipt_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_canonical(receipt) + "\n")
        except OSError as exc:
            raise ProtectError(f"cannot append Protect receipt: {exc}") from exc
    return receipt


def _iter_receipts(repo: Path, limit: int = _MAX_RECEIPTS) -> tuple[list[dict[str, Any]], bool]:
    path = _receipts_path(repo)
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return [], True
    except OSError:
        return [], False
    values: list[dict[str, Any]] = []
    integrity = True
    previous: str | None = None
    for line in raw_lines[-max(1, limit):]:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            integrity = False
            continue
        if not isinstance(value, dict) or value.get("schema") != RECEIPT_SCHEMA:
            integrity = False
            continue
        claimed = value.get("hash")
        stable = dict(value)
        stable.pop("hash", None)
        stable.pop("id", None)
        calculated = hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()
        if claimed != calculated:
            integrity = False
        if previous is not None and value.get("prev") != previous:
            integrity = False
        previous = str(claimed) if isinstance(claimed, str) else None
        values.append(value)
    return values, integrity


def protection_summary(repo: Path) -> dict[str, Any]:
    values, integrity = _iter_receipts(repo)
    decisions: dict[str, int] = {}
    categories: dict[str, int] = {}
    for item in values:
        decision = str(item.get("decision") or "unknown")
        category = str(item.get("category") or "unknown")
        decisions[decision] = decisions.get(decision, 0) + 1
        categories[category] = categories.get(category, 0) + 1
    return {
        "schema": SUMMARY_SCHEMA,
        "count": len(values),
        "integrity": integrity,
        "decisions": dict(sorted(decisions.items())),
        "categories": dict(sorted(categories.items())),
    }


def _mark_provider_active(repo: Path, payload: Mapping[str, Any]) -> None:
    provider = str(payload.get("provider") or payload.get("agent") or "").strip().lower()
    if provider not in SUPPORTED_ADAPTERS:
        return
    config = load_protect_config(repo)
    if config.get("mode") != "builtin" or provider not in set(config.get("adapters") or []):
        return
    enabled_at = str(config.get("updatedAt") or "")
    values, _ = _iter_receipts(repo)
    if any(
        str(item.get("provider")) == provider
        and (not enabled_at or str(item.get("ts") or "") >= enabled_at)
        for item in values
    ):
        return
    append_receipt(
        repo,
        payload=payload,
        phase="runtime",
        decision="active",
        category="runtime",
        rule="hook-live",
        message="The configured provider invoked DiffWitness Protect.",
    )


def _tool_input(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("tool_input", "toolInput", "input", "arguments"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _tool_name(payload: Mapping[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "").strip()


def _command(payload: Mapping[str, Any]) -> str:
    tool_input = _tool_input(payload)
    for key in ("command", "cmd", "script"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value[:20000]
    return ""


def _candidate_path(payload: Mapping[str, Any]) -> str | None:
    tool_input = _tool_input(payload)
    for key in ("file_path", "filePath", "path", "filename"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:2000]
    return None


def _candidate_content(payload: Mapping[str, Any]) -> str:
    tool_input = _tool_input(payload)
    for key in ("content", "new_string", "newString", "patch"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value[:_MAX_CONTENT_SCAN]
    return ""


def _repo_relative(repo: Path, raw: str | None) -> tuple[str | None, bool]:
    if not raw:
        return None, True
    path = Path(raw).expanduser()
    target = path if path.is_absolute() else repo / path
    try:
        resolved = target.resolve(strict=False)
        rel = resolved.relative_to(repo.resolve())
    except (OSError, ValueError):
        return None, False
    return rel.as_posix(), True


def _destructive_command_rule(command: str) -> tuple[str, str, str] | None:
    lower = command.lower()
    if _PIPE_TO_SHELL_RE.search(command):
        return ("remote-execution", "pipe-to-shell", "Remote content was piped directly into a shell.")
    if _DROP_DATABASE_RE.search(command):
        return ("destructive-command", "drop-database", "A database/schema destructive command was blocked.")
    if re.search(r"\bgit\s+push\b[^\n]*(?:--force(?:-with-lease)?|\s-f(?:\s|$))", lower):
        return ("destructive-git", "force-push", "A force-push command was blocked.")
    if re.search(r"\bgit\s+reset\b[^\n]*--hard\b", lower):
        return ("destructive-git", "hard-reset", "A hard reset command was blocked.")
    if re.search(r"\bgit\s+clean\b[^\n]*-[a-z]*f[a-z]*\b", lower):
        return ("destructive-git", "forced-clean", "A forced Git clean command was blocked.")
    if re.search(r"\bgit\s+branch\b[^\n]*\s-D(?:\s|$)", command):
        return ("destructive-git", "force-delete-branch", "A forced branch deletion was blocked.")
    if re.search(r"\bgit\s+worktree\s+remove\b[^\n]*--force\b", lower):
        return ("destructive-git", "force-remove-worktree", "A forced worktree removal was blocked.")
    if re.search(r"\bgit\s+(?:checkout|restore)\b[^\n]*(?:--\s+\.$|\s\.$)", lower.strip()):
        return ("destructive-git", "discard-worktree", "A command that can discard repository-wide working changes was blocked.")
    if re.search(r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(?:/|~|\.\.?)(?:\s|$)", lower):
        return ("destructive-filesystem", "recursive-delete-root", "A broad recursive filesystem deletion was blocked.")
    if re.search(r"\b(?:del|rmdir)\b[^\n]*(?:/s|/q)[^\n]*(?:\\|/|\.)", lower):
        return ("destructive-filesystem", "recursive-delete", "A broad filesystem deletion was blocked.")
    if re.search(r"\bremove-item\b[^\n]*-recurse\b[^\n]*-force\b", lower):
        return ("destructive-filesystem", "recursive-delete", "A forced recursive filesystem deletion was blocked.")
    return None


def _secret_rule(content: str) -> tuple[str, str, str] | None:
    if not content:
        return None
    for rule, pattern in _SECRET_PATTERNS:
        if pattern.search(content):
            return ("secret-exposure", rule, "Proposed source content appears to contain a credential or private key.")
    return None


def _is_mutating_tool(tool: str) -> bool:
    lower = tool.lower()
    return any(token in lower for token in ("write", "edit", "patch", "bash", "shell", "exec", "command"))


def evaluate_pre_tool(repo: Path, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    config = load_protect_config(repo)
    if config["mode"] != "builtin":
        return None
    _mark_provider_active(repo, payload)
    policy = str(config["policy"])
    tool = _tool_name(payload)
    raw_path = _candidate_path(payload)
    rel_path, confined = _repo_relative(repo, raw_path)

    finding: tuple[str, str, str] | None = None
    if _is_mutating_tool(tool) and raw_path and not confined:
        finding = ("repository-boundary", "write-outside-repository", "A write outside the active repository was blocked.")
    elif rel_path and (rel_path == ".git" or rel_path.startswith(".git/")):
        finding = ("repository-boundary", "write-git-metadata", "Direct agent writes into Git metadata were blocked.")
    else:
        finding = _secret_rule(_candidate_content(payload))
        if finding is None:
            finding = _destructive_command_rule(_command(payload))

    decision: str | None = None
    if finding is not None:
        decision = "observed" if policy == "observe" else "block"
    elif _DEPENDENCY_RE.search(_command(payload)):
        provider = str(payload.get("provider") or "").strip().lower()
        finding = ("supply-chain", "dependency-install", "The agent requested a dependency installation.")
        if policy == "strict" and provider == "codex":
            finding = (
                "supply-chain",
                "dependency-install",
                "The dependency installation was blocked because the current Codex PreToolUse hook cannot safely request confirmation.",
            )
            decision = "block"
        else:
            decision = "ask" if policy == "strict" else "observed"

    if finding is None or decision is None:
        return None
    category, rule, message = finding
    append_receipt(
        repo,
        payload=payload,
        phase="pre-tool",
        decision=decision,
        category=category,
        rule=rule,
        message=message,
        path=rel_path,
    )
    if decision == "observed":
        return None
    return {
        "decision": decision,
        "reason": message,
        "category": category,
        "rule": rule,
    }


def evaluate_post_tool(repo: Path, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    config = load_protect_config(repo)
    if config["mode"] != "builtin":
        return None
    _mark_provider_active(repo, payload)
    raw_path = _candidate_path(payload)
    rel_path, confined = _repo_relative(repo, raw_path)
    if not confined or not rel_path:
        return None
    path = repo / rel_path
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > _MAX_CONTENT_SCAN:
            return None
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    finding: tuple[str, str, str] | None = _secret_rule(text)
    if finding is None and path.suffix.lower() == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            finding = ("quality", "invalid-json", "The edited JSON file is not syntactically valid.")
    if finding is None and path.suffix.lower() == ".py":
        try:
            compile(text, rel_path, "exec")
        except SyntaxError:
            finding = ("quality", "python-syntax", "The edited Python file is not syntactically valid.")
    if finding is None:
        return None
    category, rule, message = finding
    append_receipt(
        repo,
        payload=payload,
        phase="post-tool",
        decision="observed",
        category=category,
        rule=rule,
        message=message,
        path=rel_path,
    )
    return {"decision": "observed", "reason": message, "category": category, "rule": rule}


def protect_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw protect",
        description="Optional local runtime protection for AI coding agents. Proof/Debt continue to work when Protect is off or delegated.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    detect = sub.add_parser("detect")
    detect.add_argument("--json", action="store_true")
    enable = sub.add_parser("enable")
    enable.add_argument("--policy", choices=POLICIES, default="standard")
    enable.add_argument("--force", action="store_true", help="enable builtin Protect even when a high-confidence external harness marker is detected")
    enable.add_argument("--json", action="store_true")
    disable = sub.add_parser("disable")
    disable.add_argument("--json", action="store_true")
    use = sub.add_parser("use")
    use.add_argument("mode", choices=("external", "builtin", "off"))
    use.add_argument("--policy", choices=POLICIES, default="standard")
    use.add_argument("--force", action="store_true")
    use.add_argument("--json", action="store_true")
    log = sub.add_parser("log")
    log.add_argument("--limit", type=int, default=20)
    log.add_argument("--json", action="store_true")
    parser.add_argument("--repo", default=".", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        repo = repo_root(args.repo)
        if args.action == "detect":
            result = detect_external_harness(repo)
        elif args.action == "status":
            result = protect_status(repo)
        elif args.action == "enable":
            result = set_protect_mode(repo, "builtin", policy=args.policy, force=args.force)
        elif args.action == "disable":
            result = set_protect_mode(repo, "off")
        elif args.action == "use":
            result = set_protect_mode(repo, args.mode, policy=args.policy, force=args.force)
        else:
            values, integrity = _iter_receipts(repo, limit=max(1, min(args.limit, 200)))
            result = {
                "schema": "diffwitness.protection-log.v1",
                "integrity": integrity,
                "receipts": values[-max(1, min(args.limit, 200)):],
            }
    except (ProtectError, OSError, ValueError) as exc:
        print(f"DiffWitness Protect: {exc}", file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    if args.action == "detect":
        print(f"Protect recommendation: {result['recommendation']}")
        if result["externalHarnessDetected"]:
            print("A high-confidence external harness marker was detected; builtin Protect will delegate unless --force is explicit.")
        elif result["otherHookActivityDetected"]:
            print("Other agent hook activity exists. DiffWitness will merge non-destructively and will not remove foreign hooks.")
        else:
            print("No conflicting harness signal detected.")
        return 0
    if args.action == "log":
        print(f"Protection receipts: {len(result['receipts'])} · integrity {'ok' if result['integrity'] else 'INVALID'}")
        for item in result["receipts"]:
            print(f"{item.get('ts')}  {str(item.get('decision')).upper():8}  {item.get('category')} / {item.get('rule')}  {item.get('path') or '-'}")
        return 0
    print(f"Protect: {result['mode']} · policy {result['policy']} · {result['health']}")
    if result["mode"] == "external":
        print("Runtime protection is delegated. DiffWitness Proof, Debt, Continuity and IdleProof remain active.")
    elif result["mode"] == "off":
        print("Runtime protection is off. DiffWitness Proof, Debt, Continuity and IdleProof remain active.")
    else:
        adapters = ", ".join(result["adapters"]) or "none"
        print(f"Builtin runtime guards: {adapters}")
        codex = result.get("adapters", {}).get("codex") if isinstance(result.get("adapters"), dict) else None
        if isinstance(codex, dict) and codex.get("installed") and not codex.get("ready"):
            print("Codex hook files are installed but no trusted live hook has been observed since enablement.")
            print("Current Codex requires its hooks feature plus explicit user approval in `/hooks`; DiffWitness never bypasses Codex hook trust.")
    return 0 if result["health"] != "degraded" else 1


__all__ = [
    "MODES",
    "POLICIES",
    "ProtectError",
    "append_receipt",
    "detect_external_harness",
    "evaluate_post_tool",
    "evaluate_pre_tool",
    "load_protect_config",
    "protect_cli",
    "protect_status",
    "protection_summary",
    "set_protect_mode",
]
