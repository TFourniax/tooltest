from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .continuity_context import compile_context as _compile_base_context
from .continuity_context import render_context
from .continuity_events import continuity_paths
from .gitops import repo_root


def _context_id(context: dict[str, Any]) -> str:
    stable = {key: value for key, value in context.items() if key not in {"generated_at", "context_id"}}
    return "dwctx_" + hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]


def _linked_debt_ids(context: dict[str, Any]) -> set[str]:
    relevant_ids = {
        str(item.get("id"))
        for bucket in ("objectives", "decisions", "invariants", "failedApproaches")
        for item in context.get(bucket, [])
        if isinstance(item, dict) and item.get("id")
    }
    result: set[str] = set()
    for relation in context.get("relations", []):
        if not isinstance(relation, dict):
            continue
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        if source in relevant_ids and target.startswith("DW-"):
            result.add(target)
        if target in relevant_ids and source.startswith("DW-"):
            result.add(source)
    return result


def _debt_rows(repo: Path, identities: set[str]) -> list[dict[str, Any]]:
    if not identities:
        return []
    state = continuity_paths(repo).state
    placeholders = ",".join("?" for _ in identities)
    conn = sqlite3.connect(state)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            select debt_id,status,accepted,accepted_reason,category,rule_id,title,points,path,
                   introduced_change_id,last_change_id,epistemic_status,updated_at
            from debts
            where debt_id in ({placeholders}) and status='open'
            order by points desc, updated_at desc, debt_id
            """,
            tuple(sorted(identities)),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def compile_context(
    repo: str | Path,
    task: str,
    *,
    max_items: int = 12,
    refresh_structure: bool = True,
) -> dict[str, Any]:
    """Compile base context and promote explicitly graph-linked open debt into the agent view.

    A decision/objective/invariant can therefore explain a durable DW-* obligation even when the
    debt is old and its introducing change would not otherwise rank among the task's recent changes.
    The human relation remains DECLARED; the debt's own accounting status remains OBSERVED/verified
    only according to the authoritative Debt Ledger projection.
    """
    root = repo_root(repo)
    context = _compile_base_context(
        root,
        task,
        max_items=max_items,
        refresh_structure=refresh_structure,
    )
    linked = _debt_rows(root, _linked_debt_ids(context))
    existing = {
        str(item.get("debt_id")): item
        for item in context.get("knownDebt", [])
        if isinstance(item, dict) and item.get("debt_id")
    }
    for item in linked:
        existing[str(item["debt_id"])] = item
    debts = list(existing.values())
    debts.sort(key=lambda item: (-int(item.get("points") or 0), str(item.get("updated_at") or "")), reverse=False)
    context["knownDebt"] = debts[: max(1, max_items)]
    context["context_id"] = _context_id(context)
    return context


__all__ = ["compile_context", "render_context"]
