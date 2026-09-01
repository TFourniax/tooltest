from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_config
from .continuity_events import ContinuityError, append_project_events
from .debt_budget import ledger_path, merged_debt_config
from .engine_protocol import change_id, repository_fingerprint
from .gitops import git, repo_root
from .ledger import DebtLedger, LedgerError

_EVENT_MAP = {
    "introduced": "debt.introduced",
    "refreshed": "debt.refreshed",
    "accepted": "debt.accepted",
    "unaccepted": "debt.unaccepted",
    "resolved": "debt.resolved",
    "reopened": "debt.reopened",
}


def _event_change_id(repo: Path, event: dict[str, Any]) -> str | None:
    payload = event.get("payload") or {}
    report = payload.get("report")
    if not isinstance(report, dict):
        return None
    base_sha = report.get("base_sha")
    candidate_tree = report.get("candidate_tree")
    if not isinstance(base_sha, str) or not base_sha or not isinstance(candidate_tree, str) or not candidate_tree:
        return None
    try:
        base_tree = git(repo, "rev-parse", f"{base_sha}^{{tree}}").strip()
    except Exception:
        # Historical Git objects can legitimately disappear after aggressive history rewriting.
        # Never invent a longitudinal change identity when the old base tree is unavailable.
        return None
    if not base_tree:
        return None
    return change_id(
        repository=repository_fingerprint(repo),
        base_tree=base_tree,
        candidate_tree=candidate_tree,
    )


def _bounded_signal(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("signal")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("category", "rule_id", "title", "severity", "measurement", "points", "path", "line", "end_line"):
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            result[key] = value[:500]
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
    verification = raw.get("verification")
    if isinstance(verification, dict):
        result["verification"] = {
            str(key)[:80]: (str(value)[:300] if not isinstance(value, (int, float, bool)) and value is not None else value)
            for key, value in list(verification.items())[:20]
        }
    return result


def _bounded_resolution(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    reason = payload.get("reason")
    if isinstance(reason, str):
        result["reason"] = reason[:1000]
    if isinstance(payload.get("forced"), bool):
        result["forced"] = payload["forced"]
    verification = payload.get("verification")
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
        semantic_payload["reason"] = str(payload.get("reason") or "")[:1000] or None
    elif legacy_type == "resolved":
        semantic_payload.update(_bounded_resolution(payload))

    relations: list[dict[str, Any]] = []
    if cid:
        predicate = {
            "introduced": "introduced_in",
            "refreshed": "refreshed_in",
            "reopened": "reopened_in",
        }.get(legacy_type)
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
    status = "DECLARED" if legacy_type in {"accepted", "unaccepted"} else "OBSERVED"
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
