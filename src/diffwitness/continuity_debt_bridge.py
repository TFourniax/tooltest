from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Any

from .config import load_config
from .continuity_contract import (
    DEBT_LIFECYCLE_PROFILE, DEBT_LIFECYCLE_SPECS, DEBT_SIGNAL_FIELDS, PROFILE_PROVENANCE_FIELD,
)
from .continuity_events import ContinuityError, append_project_events
from .debt_budget import ledger_path, merged_debt_config
from .engine_protocol import change_id, repository_fingerprint
from .gitops import repo_root
from .ledger import DebtLedger, LedgerError

_EVENT_MAP = {name: "debt." + name for name in DEBT_LIFECYCLE_SPECS}


def _event_change_id(repo: Path, event: dict[str, Any]) -> str | None:
    payload = event.get("payload") or {}
    report = payload.get("report")
    if report is None:
        return None
    if not isinstance(report, dict):
        raise ContinuityError("Debt Ledger report must be an object or null")
    base_sha = report.get("base_sha")
    candidate_tree = report.get("candidate_tree")
    for key, value in (("base_sha", base_sha), ("candidate_tree", candidate_tree)):
        if value is not None and not isinstance(value, str):
            raise ContinuityError(f"Debt Ledger report.{key} must be a string or null")
    if not isinstance(base_sha, str) or not base_sha or not isinstance(candidate_tree, str) or not candidate_tree:
        return None
    # A mutable ref or an echoed rev-parse option cannot identify historical
    # code. Native reports already contain full immutable object identities.
    if (not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", base_sha)
            or not re.fullmatch(r"[0-9a-f]{" + str(len(base_sha)) + r"}", candidate_tree)):
        return None
    from .continuity_git_history import _git

    raw = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{base_sha}^{{tree}}",
               limit=65, deadline=time.monotonic() + 15, missing_ok=(1, 128))
    if raw is None:
        # Historical Git objects can legitimately disappear after aggressive history rewriting.
        # Never invent a longitudinal change identity when the old base tree is unavailable.
        return None
    base_tree = raw.decode('ascii').strip()
    if not re.fullmatch(r"[0-9a-f]{" + str(len(base_sha)) + r"}", base_tree):
        return None
    return change_id(
        repository=repository_fingerprint(repo),
        base_tree=base_tree,
        candidate_tree=candidate_tree,
    )


def _bounded_signal(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("signal")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ContinuityError("Debt Ledger signal must be an object or null")
    result: dict[str, Any] = {}
    for key, rule in DEBT_SIGNAL_FIELDS.items():
        value = raw.get(key)
        if value is None:
            continue
        if rule == "string" and isinstance(value, str):
            result[key] = value[:500]
        elif rule != "string" and type(value) is int and value >= (1 if rule == "positive-integer" else 0):
            result[key] = value
        else:
            raise ContinuityError(f"Debt Ledger signal.{key} must be {rule}")
    verification = raw.get("verification")
    if verification is not None and not isinstance(verification, dict):
        raise ContinuityError("Debt Ledger signal.verification must be an object or null")
    if isinstance(verification, dict):
        result["verification"] = {
            str(key)[:80]: (str(value)[:300] if not isinstance(value, (int, float, bool)) and value is not None else value)
            for key, value in list(verification.items())[:20]
        }
    return result


def _bounded_resolution(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ContinuityError("Debt Ledger reason must be a string or null")
    if isinstance(reason, str):
        result["reason"] = reason[:1000]
    if isinstance(payload.get("forced"), bool):
        result["forced"] = payload["forced"]
    elif payload.get("forced") is not None:
        raise ContinuityError("Debt Ledger forced must be boolean or null")
    verification = payload.get("verification")
    if verification is not None and not isinstance(verification, dict):
        raise ContinuityError("Debt Ledger verification must be an object or null")
    if isinstance(verification, dict):
        result["verification"] = {
            str(key)[:80]: (str(value)[:300] if not isinstance(value, (int, float, bool)) and value is not None else value)
            for key, value in list(verification.items())[:20]
        }
    return result


def _spec(repo: Path, event: dict[str, Any]) -> dict[str, Any]:
    legacy_type = str(event.get("event_type") or "")
    mapped = _EVENT_MAP.get(legacy_type)
    if mapped is None:
        raise ContinuityError(f"unsupported Debt Ledger lifecycle event: {legacy_type!r}")
    debt_id = str(event.get("debt_id") or "")
    event_hash = str(event.get("event_hash") or "")
    if not debt_id.startswith("DW-") or len(event_hash) != 64:
        raise ContinuityError("validated Debt Ledger event has invalid identity")
    payload = event.get("payload") or {}
    cid = _event_change_id(repo, event)
    semantic_payload: dict[str, Any] = {
        "legacy_event_type": legacy_type,
        "change_id": cid,
    }
    if legacy_type in {"introduced", "refreshed", "reopened"}:
        semantic_payload["signal"] = _bounded_signal(payload)
    elif legacy_type == "accepted":
        reason = payload.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ContinuityError("Debt Ledger acceptance reason must be a string or null")
        semantic_payload["reason"] = reason[:1000] or None if reason is not None else None
    elif legacy_type == "resolved":
        semantic_payload.update(_bounded_resolution(payload))

    relations: list[dict[str, Any]] = []
    if cid:
        predicate = DEBT_LIFECYCLE_SPECS[legacy_type]["change_relation"]
        if predicate:
            relations.append(
                {
                    "predicate": predicate,
                    "target": {"id": cid, "kind": "change"},
                    "epistemic_status": "OBSERVED",
                    "metadata": {"basis": "validated-debt-ledger-report"},
                }
            )

    # Acceptance/unacceptance is a human/project policy declaration. The fact that such a declaration
    # exists is observed in the ledger, but the semantic acceptance itself should not masquerade as
    # an executed technical verification.
    status = DEBT_LIFECYCLE_SPECS[legacy_type]["epistemic_status"]
    return {
        "event_type": mapped,
        "subject": {"id": debt_id, "kind": "debt", "label": debt_id},
        "epistemic_status": status,
        "payload": semantic_payload,
        "relations": relations,
        "provenance": {
            "producer": "debt-ledger",
            "source": "debt-event-1",
            "legacy_event_hash": event_hash,
            PROFILE_PROVENANCE_FIELD: DEBT_LIFECYCLE_PROFILE,
        },
        "actor": {"kind": "ledger-actor", "id": str(event.get("actor") or "unknown")[:128]},
        "dedupe_key": "legacy-debt:" + event_hash,
        "timestamp": str(event.get("timestamp") or ""),
    }


def sync_debt_history(
    repo: str | Path = ".",
    *,
    explicit_config: str | None = None,
    batch_size: int = 1024,
) -> dict[str, Any]:
    """Idempotently project the validated existing Debt Ledger into ProjectEvent history."""
    root = repo_root(repo)
    config = load_config(root, explicit_config)
    debt_config = merged_debt_config(config.get("debt") or {})
    path = ledger_path(root, debt_config)
    try:
        ledger = DebtLedger.load(path)
    except LedgerError as exc:
        raise ContinuityError(f"Debt Ledger cannot be projected because its own integrity gate failed: {exc}") from exc
    if not ledger.events:
        return {"ledger_events": 0, "created": 0, "last_hash": None, "path": str(path)}
    size = max(1, min(int(batch_size), 2048))
    created = 0
    for start in range(0, len(ledger.events), size):
        specs = [_spec(root, event) for event in ledger.events[start : start + size]]
        results = append_project_events(repo=root, events=specs)
        created += sum(1 for _, was_created in results if was_created)
    return {
        "ledger_events": len(ledger.events),
        "created": created,
        "last_hash": ledger.last_hash,
        "path": str(path),
    }
