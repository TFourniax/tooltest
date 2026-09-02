from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

NATIVE_ACTIVATION_SCHEMA = "diffwitness.native-activation.v1"
SUPPORTED_NATIVE_PROVIDERS = ("claude", "codex", "cursor")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def activation_path(repo: Path) -> Path:
    return repo / ".git" / "diffwitness" / "native-activation.json"


def load_native_activation(repo: Path) -> dict[str, Any]:
    path = activation_path(repo)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
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
    current = load_native_activation(repo)
    providers = dict(current.get("providers") or {})
    providers[provider] = {"observedAt": _now()}
    payload = {"schema": NATIVE_ACTIVATION_SCHEMA, "providers": providers}
    path = activation_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".json.tmp")
    staged.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    staged.replace(path)


def clear_native_activation(repo: Path) -> None:
    try:
        activation_path(repo).unlink()
    except (FileNotFoundError, OSError):
        pass


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
    "SUPPORTED_NATIVE_PROVIDERS",
    "activation_path",
    "clear_native_activation",
    "load_native_activation",
    "native_activation_summary",
    "record_native_activation",
]
