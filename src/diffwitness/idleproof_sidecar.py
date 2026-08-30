from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .engine_protocol import repository_fingerprint
from .gitops import repo_root


INTEGRATION_SCHEMA = "diffwitness.integration-status.v1"
LOCAL_PROJECT_SCHEMA = "idleproof.local-project.v1"
PORTAL_CONFIG_SCHEMA = "idleproof.portal-config.v1"
SNAPSHOT_SCHEMA = "idleproof.portal-snapshot.v1"
ACK_SCHEMA = "idleproof.portal-ingest-ack.v1"
ERROR_SCHEMA = "idleproof.portal-ingest-error.v1"
MAX_RESPONSE_BYTES = 96 * 1024


class IdleProofSidecarError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, *, required: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise IdleProofSidecarError(f"required file does not exist: {path}")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise IdleProofSidecarError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise IdleProofSidecarError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    staged.replace(path)


def _state_dir(repo: Path) -> Path:
    return repo / ".idleproof"


def _integration_state_path(repo: Path) -> Path:
    return _state_dir(repo) / "integration.json"


def _local_project_path(repo: Path) -> Path:
    return _state_dir(repo) / "project.json"


def _portal_config_path(repo: Path) -> Path:
    return _state_dir(repo) / "portal.json"


def _assurance_path(repo: Path) -> Path:
    return _state_dir(repo) / "assurance.json"


def _safe_project_name(repo: Path) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "-", repo.name).strip(" .-") or "project"
    return value[:120]


def ensure_local_project(repo: Path) -> dict[str, Any]:
    path = _local_project_path(repo)
    current = _read_json(path)
    local_id = current.get("localId")
    fingerprint = repository_fingerprint(repo)
    if isinstance(local_id, str) and re.fullmatch(r"[a-f0-9]{24}", local_id):
        payload = {
            "schema": LOCAL_PROJECT_SCHEMA,
            "localId": local_id,
            "repositoryFingerprint": fingerprint,
            "name": _safe_project_name(repo),
            "createdAt": current.get("createdAt") if isinstance(current.get("createdAt"), str) else _now(),
        }
    else:
        payload = {
            "schema": LOCAL_PROJECT_SCHEMA,
            "localId": secrets.token_hex(12),
            "repositoryFingerprint": fingerprint,
            "name": _safe_project_name(repo),
            "createdAt": _now(),
        }
    if payload != current:
        _write_json(path, payload)
    return payload


def _shell_command(executable: str, *args: str) -> str:
    values = [executable, *args]
    if os.name == "nt":
        return subprocess.list2cmdline(values)
    return " ".join(shlex.quote(value) for value in values)


def _agent_commands(dw_command: str) -> dict[str, tuple[str, str, str]]:
    return {
        "claude": (
            _shell_command(dw_command, "ide-hook", "session-start"),
            _shell_command(dw_command, "ide-hook", "user-prompt-submit"),
            _shell_command(dw_command, "ide-hook", "session-stop"),
        ),
        "codex": (
            _shell_command(dw_command, "ide-hook", "session-start"),
            _shell_command(dw_command, "ide-hook", "user-prompt-submit"),
            _shell_command(dw_command, "ide-hook", "session-stop"),
        ),
        "cursor": (
            _shell_command(dw_command, "ide-hook", "session-start"),
            _shell_command(dw_command, "ide-hook", "user-prompt-submit"),
            _shell_command(dw_command, "ide-hook", "session-stop"),
        ),
    }


def _adapter_path(repo: Path, adapter: str) -> Path:
    if adapter == "claude":
        return repo / ".claude" / "settings.local.json"
    if adapter == "codex":
        return repo / ".codex" / "hooks.json"
    if adapter == "cursor":
        return repo / ".cursor" / "hooks.json"
    raise IdleProofSidecarError(f"unsupported adapter: {adapter}")


def _claude_like_entry(command: str, timeout: int, *, additional_context_limit: int | None = None) -> dict[str, Any]:
    hook: dict[str, Any] = {"type": "command", "command": command, "timeout": timeout}
    if additional_context_limit is not None:
        hook["additionalContextLimit"] = additional_context_limit
    return {"hooks": [hook]}


def _append_unique(items: list[Any], entry: dict[str, Any]) -> None:
    command = _entry_command(entry)
    if command and any(_entry_command(item) == command for item in items if isinstance(item, dict)):
        return
    items.append(entry)


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


def _install_adapter(repo: Path, adapter: str, *, dw_command: str) -> tuple[Path, bool]:
    path = _adapter_path(repo, adapter)
    existed = path.exists()
    data = _read_json(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    start, prompt, stop = _agent_commands(dw_command)[adapter]

    if adapter in {"claude", "codex"}:
        specs = {
            "SessionStart": _claude_like_entry(start, 10),
            "UserPromptSubmit": _claude_like_entry(prompt, 8, additional_context_limit=2500 if adapter == "codex" else None),
            "Stop": _claude_like_entry(stop, 900),
        }
    else:
        data["version"] = 1
        specs = {
            "sessionStart": {"command": start},
            "beforeSubmitPrompt": {"command": prompt},
            "stop": {"command": stop, "loop_limit": 4},
        }

    for event, entry in specs.items():
        entries = hooks.get(event)
        if not isinstance(entries, list):
            entries = []
            hooks[event] = entries
        _append_unique(entries, entry)
    _write_json(path, data)
    return path, existed


def _resolve_adapters(raw: str, repo: Path) -> list[str]:
    normalized = str(raw or "auto").strip().lower()
    if normalized in {"all", "auto"}:
        if normalized == "all":
            return ["claude", "codex", "cursor"]
        detected: list[str] = []
        if (repo / ".claude").exists() or shutil.which("claude"):
            detected.append("claude")
        if (repo / ".codex").exists() or shutil.which("codex"):
            detected.append("codex")
        if (repo / ".cursor").exists() or shutil.which("cursor"):
            detected.append("cursor")
        # A fresh repository may not contain editor-local directories yet. Installing all three
        # project-local hook files is deterministic and keeps `dw setup` useful before first launch.
        return detected or ["claude", "codex", "cursor"]
    values = [item.strip() for item in normalized.split(",") if item.strip()]
    unknown = [value for value in values if value not in {"claude", "codex", "cursor"}]
    if unknown:
        raise IdleProofSidecarError(f"unsupported integration adapter(s): {', '.join(unknown)}")
    if not values:
        raise IdleProofSidecarError("at least one integration adapter is required")
    return list(dict.fromkeys(values))


def _adapter_installed(repo: Path, adapter: str, dw_command: str) -> bool:
    path = _adapter_path(repo, adapter)
    if not path.is_file():
        return False
    try:
        data = _read_json(path, required=True)
    except IdleProofSidecarError:
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    start, prompt, stop = _agent_commands(dw_command)[adapter]
    expected = {start, prompt, stop}
    found: set[str] = set()
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, Mapping):
                command = _entry_command(entry)
                if command in expected:
                    found.add(command)
    return found == expected


def integration_status(repo: Path) -> dict[str, Any]:
    state = _read_json(_integration_state_path(repo))
    expected = state.get("expectedAdapters")
    adapters = [str(value) for value in expected if str(value) in {"claude", "codex", "cursor"}] if isinstance(expected, list) else []
    dw_command = str(state.get("diffwitnessCommand") or shutil.which("dw") or "dw")
    if not adapters:
        adapters = [name for name in ("claude", "codex", "cursor") if _adapter_installed(repo, name, dw_command)]
    details = {
        adapter: {
            "path": _adapter_path(repo, adapter).relative_to(repo).as_posix(),
            "installed": _adapter_installed(repo, adapter, dw_command),
        }
        for adapter in adapters
    }
    healthy = bool(adapters) and all(bool(item["installed"]) for item in details.values())
    local = ensure_local_project(repo)
    return {
        "schema": INTEGRATION_SCHEMA,
        "healthy": healthy,
        "installed": healthy,
        "expectedAdapters": adapters,
        "adapters": details,
        "localProjectId": local["localId"],
        "repositoryFingerprint": local["repositoryFingerprint"],
    }


def integration_install(repo: Path, *, agent: str, dw_command: str) -> dict[str, Any]:
    resolved_dw = shutil.which(dw_command) if os.path.sep not in dw_command and not (os.path.altsep and os.path.altsep in dw_command) else dw_command
    executable = str(Path(resolved_dw or dw_command).expanduser())
    adapters = _resolve_adapters(agent, repo)
    created: dict[str, bool] = {}
    for adapter in adapters:
        path, existed = _install_adapter(repo, adapter, dw_command=executable)
        created[path.relative_to(repo).as_posix()] = not existed
    ensure_local_project(repo)
    _write_json(
        _integration_state_path(repo),
        {
            "schema": "idleproof.integration-state.v1",
            "expectedAdapters": adapters,
            "diffwitnessCommand": executable,
            "createdFiles": created,
            "installedAt": _now(),
        },
    )
    status = integration_status(repo)
    if not status["healthy"]:
        raise IdleProofSidecarError("integration files were written but health verification failed")
    return status


def _remove_commands_from_hooks(data: dict[str, Any], commands: set[str]) -> dict[str, Any]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [entry for entry in entries if not (isinstance(entry, Mapping) and _entry_command(entry) in commands)]
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    return data


def integration_uninstall(repo: Path) -> None:
    state_path = _integration_state_path(repo)
    state = _read_json(state_path)
    dw_command = str(state.get("diffwitnessCommand") or shutil.which("dw") or "dw")
    adapters = state.get("expectedAdapters") if isinstance(state.get("expectedAdapters"), list) else ["claude", "codex", "cursor"]
    created_files = state.get("createdFiles") if isinstance(state.get("createdFiles"), dict) else {}
    commands = {value for triple in _agent_commands(dw_command).values() for value in triple}
    for adapter in adapters:
        if adapter not in {"claude", "codex", "cursor"}:
            continue
        path = _adapter_path(repo, adapter)
        if not path.is_file():
            continue
        data = _remove_commands_from_hooks(_read_json(path, required=True), commands)
        rel = path.relative_to(repo).as_posix()
        hooks = data.get("hooks")
        only_empty_scaffold = isinstance(hooks, dict) and not hooks and set(data) <= {"hooks", "version"}
        if bool(created_files.get(rel)) and only_empty_scaffold:
            try:
                path.unlink()
            except OSError:
                _write_json(path, data)
        else:
            _write_json(path, data)
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass


def _validate_endpoint(raw: str) -> str:
    value = str(raw or "").strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise IdleProofSidecarError("Portal endpoint must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise IdleProofSidecarError("Portal endpoint must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise IdleProofSidecarError("Portal endpoint must not contain a query string or fragment")
    hostname = parsed.hostname.lower()
    loopback = hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not loopback:
        raise IdleProofSidecarError("Portal endpoint must use HTTPS except for loopback development")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def portal_configure(repo: Path, *, endpoint: str, token_env: str) -> dict[str, Any]:
    endpoint = _validate_endpoint(endpoint)
    token_env = str(token_env or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", token_env):
        raise IdleProofSidecarError("--token-env must be a valid environment variable name")
    local = ensure_local_project(repo)
    payload = {
        "schema": PORTAL_CONFIG_SCHEMA,
        "endpoint": endpoint,
        "tokenEnv": token_env,
        "configuredAt": _now(),
    }
    _write_json(_portal_config_path(repo), payload)
    return {**payload, "localProjectId": local["localId"], "repositoryFingerprint": local["repositoryFingerprint"]}


def _bounded_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 300:
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    if re.match(r"^[A-Za-z]:/", normalized):
        return None
    return normalized


def _explanation(repo: Path) -> dict[str, Any]:
    path = repo / ".git" / "diffwitness" / "idleproof-explanation.json"
    value = _read_json(path)
    return value if value.get("schema") == "idleproof.explanation.v2" else {}


def _envelope(repo: Path) -> dict[str, Any]:
    path = repo / ".git" / "diffwitness" / "change-envelope.json"
    value = _read_json(path)
    return value if value.get("schema_version") == "change-envelope-1" else {}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _snapshot_id(snapshot: Mapping[str, Any]) -> str:
    stable = dict(snapshot)
    stable.pop("generatedAt", None)
    stable.pop("snapshotId", None)
    return "ipsnap_" + hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()[:24]


def build_portal_snapshot(repo: Path) -> dict[str, Any]:
    local = ensure_local_project(repo)
    envelope = _envelope(repo)
    explanation = _explanation(repo)
    summary = explanation.get("summary") if isinstance(explanation.get("summary"), Mapping) else {}
    file_facts = explanation.get("files") if isinstance(explanation.get("files"), list) else []
    files: list[str] = []
    explanation_files: list[dict[str, Any]] = []
    for raw in file_facts[:40]:
        if not isinstance(raw, Mapping):
            continue
        path = _bounded_path(raw.get("path"))
        if not path:
            continue
        files.append(path)
        explanation_files.append(
            {
                "path": path,
                "role": str(raw.get("kind") or "observed")[:60],
                "confidence": str(explanation.get("confidence") or "observed")[:40],
            }
        )
    files = list(dict.fromkeys(files))[:40]

    change_id = envelope.get("change_id") if isinstance(envelope.get("change_id"), str) else None
    proof = envelope.get("proof") if isinstance(envelope.get("proof"), Mapping) else None
    debt = envelope.get("debt") if isinstance(envelope.get("debt"), Mapping) else None
    understanding = envelope.get("understanding") if isinstance(envelope.get("understanding"), Mapping) else None

    assurance: dict[str, Any] | None = None
    if change_id and (proof or debt):
        assurance = {"schema": "idleproof.change-assurance.v1", "proof": None, "softwareDebt": None}
        if proof and isinstance(proof.get("certificate_id"), str) and len(str(proof["certificate_id"])) >= 6:
            assurance["proof"] = {
                "claim": str(proof.get("claim") or "unknown")[:20],
                "accepted": bool(proof.get("accepted")),
                "certificateId": str(proof["certificate_id"])[:128],
            }
        if debt:
            lineages = debt.get("open_lineages") if isinstance(debt.get("open_lineages"), list) else []
            points = debt.get("points") if isinstance(debt.get("points"), int) and not isinstance(debt.get("points"), bool) else 0
            budget = debt.get("budget_passed") if debt.get("budget_passed") in {True, False, None} else None
            assurance["softwareDebt"] = {
                "points": max(0, points),
                "obligations": len(lineages),
                "budgetPassed": budget,
            }
        if assurance["proof"] is None and assurance["softwareDebt"] is None:
            assurance = None

    has_understanding = understanding is not None
    coverage = int(understanding.get("coverage", 0)) if understanding and isinstance(understanding.get("coverage"), int) else 0
    knowledge_debt = int(understanding.get("knowledge_debt", 0)) if understanding and isinstance(understanding.get("knowledge_debt"), int) else 1
    feature_coverage = int(understanding.get("feature_coverage", 0)) if understanding and isinstance(understanding.get("feature_coverage"), int) else 0
    feature_debt = int(understanding.get("feature_debt", 0)) if understanding and isinstance(understanding.get("feature_debt"), int) else 1
    coverage = max(0, min(100, coverage))
    feature_coverage = max(0, min(100, feature_coverage))

    file_count = int(summary.get("files", len(files))) if isinstance(summary.get("files", len(files)), int) else len(files)
    additions = int(summary.get("additions", 0)) if isinstance(summary.get("additions", 0), int) else 0
    deletions = int(summary.get("deletions", 0)) if isinstance(summary.get("deletions", 0), int) else 0
    task_summary = (
        f"DiffWitness captured a bounded change affecting {max(0, file_count)} file(s)."
        if change_id
        else "IdleProof connected this local project without claiming a code change."
    )

    portal_explanation = None
    if change_id or explanation_files:
        portal_explanation = {
            "concept": "Deterministic DiffWitness change explanation",
            "certainty": str(explanation.get("confidence") or ("observed" if change_id else "unknown"))[:40],
            "files": explanation_files[:20],
        }

    snapshot: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "snapshotId": "",
        "generatedAt": _now(),
        "project": {
            "name": local["name"],
            "localId": local["localId"],
            "repositoryFingerprint": local["repositoryFingerprint"],
        },
        "task": {
            "summary": task_summary,
            "promptDigest": None,
            "promptChars": 0,
            "source": "diffwitness",
            "status": "completed" if change_id else "observed",
            "changed": {"added": max(0, additions), "deleted": max(0, deletions)},
        },
        "change": {"changeId": change_id, "diffSha256": None},
        "understanding": {
            "conceptsSeen": 0 if not has_understanding else max(0, len(explanation_files)),
            "cognitiveCoverage": coverage,
            "knowledgeDebt": max(0, knowledge_debt),
            "featuresSeen": 0,
            "featureCoverage": feature_coverage,
            "featureDebt": max(0, feature_debt),
        },
        "files": files,
        "privacy": {
            "sourceCodeIncluded": False,
            "rawDiffIncluded": False,
            "rawAgentEventsIncluded": False,
            "rawPromptIncluded": False,
            "secretsRedacted": True,
        },
    }
    if assurance is not None:
        snapshot["assurance"] = assurance
    if portal_explanation is not None:
        snapshot["explanation"] = portal_explanation
    snapshot["snapshotId"] = _snapshot_id(snapshot)
    return snapshot


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _post_snapshot(endpoint: str, token: str, snapshot: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    body = _canonical(snapshot).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "DiffWitness-IdleProof/0.4",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=12)
    except urllib.error.HTTPError as exc:
        response = exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IdleProofSidecarError(f"Portal sync could not reach the configured endpoint: {exc}") from exc
    try:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
    finally:
        response.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise IdleProofSidecarError("Portal returned an oversized response")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdleProofSidecarError(f"Portal returned an invalid response (HTTP {status})") from exc
    if not isinstance(payload, dict):
        raise IdleProofSidecarError(f"Portal returned a non-object response (HTTP {status})")
    return status, payload


def portal_status(repo: Path) -> dict[str, Any]:
    local = ensure_local_project(repo)
    config = _read_json(_portal_config_path(repo))
    configured = config.get("schema") == PORTAL_CONFIG_SCHEMA
    token_env = str(config.get("tokenEnv") or "") if configured else ""
    return {
        "schema": "idleproof.portal-status.v1",
        "configured": configured,
        "endpoint": config.get("endpoint") if configured else None,
        "tokenEnv": token_env or None,
        "tokenAvailable": bool(token_env and os.environ.get(token_env)),
        "localProjectId": local["localId"],
        "repositoryFingerprint": local["repositoryFingerprint"],
        "lastSnapshotAvailable": bool(_envelope(repo) or _explanation(repo)),
    }


def portal_sync(repo: Path, *, dry_run: bool = False) -> dict[str, Any]:
    config = _read_json(_portal_config_path(repo), required=True)
    if config.get("schema") != PORTAL_CONFIG_SCHEMA:
        raise IdleProofSidecarError("Portal is not configured; run `dw portal configure` first")
    endpoint = _validate_endpoint(str(config.get("endpoint") or ""))
    token_env = str(config.get("tokenEnv") or "")
    token = os.environ.get(token_env, "")
    if not dry_run and not re.fullmatch(r"ipd_[A-Za-z0-9_-]{20,}", token):
        raise IdleProofSidecarError(f"environment variable {token_env or '<unset>'} does not contain a valid ingest-only device token")
    snapshot = build_portal_snapshot(repo)
    if dry_run:
        return {
            "schema": "idleproof.portal-sync.v1",
            "status": "dry-run",
            "snapshotId": snapshot["snapshotId"],
            "snapshot": snapshot,
            "codeUploaded": False,
            "rawPromptUploaded": False,
            "rawDiffUploaded": False,
        }
    status, payload = _post_snapshot(endpoint, token, snapshot)
    if status not in {200, 202} or payload.get("schema") != ACK_SCHEMA or payload.get("status") not in {"accepted", "duplicate"}:
        code = ((payload.get("error") or {}).get("code") if isinstance(payload.get("error"), Mapping) else None) or f"HTTP_{status}"
        message = ((payload.get("error") or {}).get("message") if isinstance(payload.get("error"), Mapping) else None) or "Portal rejected the snapshot"
        raise IdleProofSidecarError(f"Portal sync rejected: {code}: {str(message)[:500]}")
    if payload.get("snapshotId") != snapshot["snapshotId"]:
        raise IdleProofSidecarError("Portal acknowledged a different snapshot identity")
    return {
        "schema": "idleproof.portal-sync.v1",
        "status": payload["status"],
        "snapshotId": snapshot["snapshotId"],
        "codeUploaded": False,
        "rawPromptUploaded": False,
        "rawDiffUploaded": False,
    }


def portal_assurance(repo: Path, envelope_path: Path) -> dict[str, Any]:
    path = envelope_path if envelope_path.is_absolute() else repo / envelope_path
    envelope = _read_json(path, required=True)
    if envelope.get("schema_version") != "change-envelope-1" or not isinstance(envelope.get("change_id"), str):
        raise IdleProofSidecarError("assurance bridge requires a valid change-envelope-1 artifact")
    privacy = envelope.get("privacy") if isinstance(envelope.get("privacy"), Mapping) else {}
    if privacy.get("code_uploaded") is not False or privacy.get("contains_prompt_text") is not False:
        raise IdleProofSidecarError("assurance envelope does not satisfy the local privacy boundary")
    payload = {
        "schema": "idleproof.local-assurance.v1",
        "changeId": envelope["change_id"],
        "repositoryFingerprint": ((envelope.get("repository") or {}).get("fingerprint") if isinstance(envelope.get("repository"), Mapping) else None),
        "proof": envelope.get("proof") if isinstance(envelope.get("proof"), Mapping) else None,
        "debt": envelope.get("debt") if isinstance(envelope.get("debt"), Mapping) else None,
        "updatedAt": _now(),
    }
    _write_json(_assurance_path(repo), payload)
    return payload


def _integration_parser(subparsers: argparse._SubParsersAction) -> None:
    integration = subparsers.add_parser("integration", help="install/status/uninstall local IDE hooks")
    actions = integration.add_subparsers(dest="integration_action", required=True)
    install = actions.add_parser("install")
    install.add_argument("--agent", default="auto")
    install.add_argument("--diffwitness-command", default=shutil.which("dw") or "dw")
    install.add_argument("--json", action="store_true")
    status = actions.add_parser("status")
    status.add_argument("--json", action="store_true")
    uninstall = actions.add_parser("uninstall")
    uninstall.add_argument("--json", action="store_true")


def _portal_parser(subparsers: argparse._SubParsersAction) -> None:
    portal = subparsers.add_parser("portal", help="configure and sync bounded receipts to IdleProof Portal")
    actions = portal.add_subparsers(dest="portal_action", required=True)
    project_id = actions.add_parser("id", help="show the local project id to paste into Portal enrollment")
    project_id.add_argument("--json", action="store_true")
    configure = actions.add_parser("configure")
    configure.add_argument("--endpoint", required=True)
    configure.add_argument("--token-env", required=True)
    configure.add_argument("--json", action="store_true")
    status = actions.add_parser("status")
    status.add_argument("--json", action="store_true")
    sync = actions.add_parser("sync")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--json", action="store_true")
    assurance = actions.add_parser("assurance")
    assurance.add_argument("--envelope", required=True, type=Path)
    assurance.add_argument("--quiet", action="store_true")
    assurance.add_argument("--json", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="idleproof", description="Local IdleProof integration/Portal sidecar shipped with DiffWitness.")
    parser.add_argument("--version", action="store_true", help="print the bundled sidecar version")
    parser.add_argument("--repo", default=".", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")
    _integration_parser(subparsers)
    _portal_parser(subparsers)
    return parser


def _print_result(value: Mapping[str, Any], *, as_json: bool, quiet: bool = False) -> None:
    if quiet:
        return
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))
        return
    schema = value.get("schema")
    if schema == INTEGRATION_SCHEMA:
        print(f"IdleProof integration: {'ready' if value.get('healthy') else 'not ready'} · adapters: {', '.join(value.get('expectedAdapters') or []) or 'none'}")
        print(f"Local project id: {value.get('localProjectId')}")
    elif schema == PORTAL_CONFIG_SCHEMA:
        print("IdleProof Portal configured without storing the device token.")
        print(f"Local project id: {value.get('localProjectId')}")
        print(f"Endpoint: {value.get('endpoint')}")
    elif schema == "idleproof.portal-status.v1":
        print(f"Portal: {'configured' if value.get('configured') else 'not configured'} · token {'available' if value.get('tokenAvailable') else 'not present in environment'}")
        print(f"Local project id: {value.get('localProjectId')}")
    elif schema == "idleproof.portal-sync.v1":
        print(f"Portal sync: {value.get('status')} · {value.get('snapshotId')}")
        print("Privacy: no source code, raw prompt, or raw diff uploaded.")
    elif schema == LOCAL_PROJECT_SCHEMA:
        print(value.get("localId"))
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.version:
        from . import __version__

        print(f"idleproof {__version__} (bundled with DiffWitness)")
        return 0
    if not args.command:
        parser.print_help()
        return 0
    try:
        repo = repo_root(args.repo)
        if args.command == "integration":
            if args.integration_action == "install":
                result = integration_install(repo, agent=args.agent, dw_command=args.diffwitness_command)
                _print_result(result, as_json=args.json)
                return 0
            if args.integration_action == "status":
                result = integration_status(repo)
                _print_result(result, as_json=args.json)
                return 0 if result.get("healthy") else 1
            integration_uninstall(repo)
            result = {"schema": "diffwitness.integration-uninstall.v1", "installed": False}
            _print_result(result, as_json=args.json)
            return 0

        if args.portal_action == "id":
            local = ensure_local_project(repo)
            _print_result(local, as_json=args.json)
            return 0
        if args.portal_action == "configure":
            result = portal_configure(repo, endpoint=args.endpoint, token_env=args.token_env)
            _print_result(result, as_json=args.json)
            return 0
        if args.portal_action == "status":
            result = portal_status(repo)
            _print_result(result, as_json=args.json)
            return 0
        if args.portal_action == "sync":
            result = portal_sync(repo, dry_run=args.dry_run)
            _print_result(result, as_json=args.json)
            return 0
        result = portal_assurance(repo, args.envelope)
        _print_result(result, as_json=args.json, quiet=args.quiet)
        return 0
    except IdleProofSidecarError as exc:
        print(f"IdleProof: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Fail closed without dumping arbitrary payloads/secrets into logs.
        print(f"IdleProof failed before the requested operation could be completed: {str(exc)[:500]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "IdleProofSidecarError",
    "build_portal_snapshot",
    "ensure_local_project",
    "integration_install",
    "integration_status",
    "integration_uninstall",
    "main",
    "portal_configure",
    "portal_status",
    "portal_sync",
]
