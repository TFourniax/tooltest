from __future__ import annotations

from pathlib import Path
from typing import Any

from . import idleproof_sidecar as _sidecar

_ORIGINAL_BUILD_PORTAL_SNAPSHOT = _sidecar.build_portal_snapshot


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
    # Sidecar functions resolve build_portal_snapshot from their module globals at call time. Keep
    # the established implementation and install only this bounded projection at the public entry.
    _sidecar.build_portal_snapshot = build_portal_snapshot
    return _sidecar.main(argv)


__all__ = ["build_portal_snapshot", "main"]
