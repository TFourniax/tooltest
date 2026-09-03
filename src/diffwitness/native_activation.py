from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .gitops import GitError, git_metadata_path

NATIVE_ACTIVATION_SCHEMA = "diffwitness.native-activation.v1"
SUPPORTED_NATIVE_PROVIDERS = ("claude", "codex", "cursor")
_LOCK_TIMEOUT_SECONDS = 5.0
_STALE_LOCK_SECONDS = 60.0


class NativeActivationError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_metadata_path(repo: Path, relative: str) -> Path:
    """Resolve per-worktree Git metadata without assuming ``repo/.git`` is a directory.

    Linked Git worktrees store a text ``.git`` file in the working directory. ``git rev-parse
    --git-path`` is the authoritative cross-platform way to resolve writable per-worktree metadata
    for both ordinary repositories and linked worktrees.
    """
    try:
        return git_metadata_path(repo, relative)
    except GitError as exc:
        raise NativeActivationError(f"cannot resolve Git metadata path for {relative}: {exc}") from exc


def activation_path(repo: Path) -> Path:
    return _git_metadata_path(repo, "diffwitness/native-activation.json")


def _lock_path(repo: Path) -> Path:
    return _git_metadata_path(repo, "diffwitness/native-activation.lock")


@contextmanager
def _activation_lock(repo: Path, *, timeout: float = _LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Serialize native-provider observations across simultaneous local agent sessions."""
    path = _lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}:{time.time_ns()}"
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except (FileExistsError, PermissionError) as exc:
            if isinstance(exc, PermissionError) and os.name != "nt":
                raise NativeActivationError(f"cannot acquire native activation lock: {exc}") from exc
            try:
                stale = time.time() - path.stat().st_mtime > _STALE_LOCK_SECONDS
            except FileNotFoundError:
                continue
            except OSError:
                stale = False
            if stale:
                try:
                    path.unlink()
                    continue
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                raise NativeActivationError("timed out waiting for native activation lock")
            time.sleep(0.02)
            continue
        try:
            os.write(fd, token.encode("ascii", errors="ignore"))
            os.fsync(fd)
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        try:
            owner = path.read_text(encoding="ascii")
        except OSError:
            owner = None
        if owner == token:
            try:
                path.unlink()
            except (FileNotFoundError, OSError):
                pass


def load_native_activation(repo: Path) -> dict[str, Any]:
    path = activation_path(repo)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        # Readiness is informational and fails closed: damaged/missing local state means no provider
        # is considered observed. It can never manufacture Proof or provider trust.
        return {"schema": NATIVE_ACTIVATION_SCHEMA, "providers": {}}
    if not isinstance(value, dict) or value.get("schema") != NATIVE_ACTIVATION_SCHEMA:
        return {"schema": NATIVE_ACTIVATION_SCHEMA, "providers": {}}
    providers = value.get("providers")
    bounded: dict[str, dict[str, str]] = {}
    if isinstance(providers, dict):
        for name, item in providers.items():
            if name not in SUPPORTED_NATIVE_PROVIDERS or not isinstance(item, dict):
                continue
            observed_at = item.get("observedAt")
            if isinstance(observed_at, str) and observed_at:
                bounded[name] = {"observedAt": observed_at}
    return {"schema": NATIVE_ACTIVATION_SCHEMA, "providers": bounded}


def record_native_activation(repo: Path, provider: str) -> None:
    provider = str(provider or "").strip().lower()
    if provider not in SUPPORTED_NATIVE_PROVIDERS:
        return
    with _activation_lock(repo):
        current = load_native_activation(repo)
        providers = dict(current.get("providers") or {})
        providers[provider] = {"observedAt": _now()}
        payload = {"schema": NATIVE_ACTIVATION_SCHEMA, "providers": providers}
        path = activation_path(repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        staged = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            staged.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            staged.replace(path)
        finally:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass


def clear_native_activation(repo: Path) -> None:
    with _activation_lock(repo):
        try:
            activation_path(repo).unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise NativeActivationError(f"cannot clear native activation state: {exc}") from exc


def native_activation_summary(repo: Path, configured: Iterable[str]) -> dict[str, Any]:
    configured_list = list(dict.fromkeys(str(item) for item in configured if str(item) in SUPPORTED_NATIVE_PROVIDERS))
    observed = load_native_activation(repo).get("providers") or {}
    adapters: dict[str, dict[str, Any]] = {}
    for provider in configured_list:
        seen = observed.get(provider) if isinstance(observed, dict) else None
        observed_at = seen.get("observedAt") if isinstance(seen, dict) else None
        trust_required = provider == "codex" and not observed_at
        adapters[provider] = {
            "configured": True,
            "observed": bool(observed_at),
            "observedAt": observed_at,
            "requiresProviderTrust": trust_required,
            "activation": (
                "observed"
                if observed_at
                else "requires-provider-trust-and-observation"
                if provider == "codex"
                else "awaiting-first-session"
            ),
        }
    pending_trust = [name for name, item in adapters.items() if item["requiresProviderTrust"]]
    pending_observation = [name for name, item in adapters.items() if not item["observed"]]
    return {
        "schema": NATIVE_ACTIVATION_SCHEMA,
        "adapters": adapters,
        "observedAdapters": [name for name, item in adapters.items() if item["observed"]],
        "pendingTrustAdapters": pending_trust,
        "pendingObservationAdapters": pending_observation,
        "fullyObserved": bool(configured_list) and not pending_observation,
    }


__all__ = [
    "NATIVE_ACTIVATION_SCHEMA",
    "NativeActivationError",
    "SUPPORTED_NATIVE_PROVIDERS",
    "activation_path",
    "clear_native_activation",
    "load_native_activation",
    "native_activation_summary",
    "record_native_activation",
]
