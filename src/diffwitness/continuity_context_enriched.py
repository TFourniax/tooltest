from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
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


def _search_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    asciiish = "".join(char for char in normalized if not unicodedata.combining(char)).lower()
    return {token for token in re.findall(r"[a-z0-9]+", asciiish) if len(token) >= 4}


def _token_overlap(left: set[str], right: set[str]) -> int:
    score = 0
    for one in left:
        for two in right:
            if one == two:
                score += 3
            elif len(one) >= 5 and len(two) >= 5 and (one.startswith(two) or two.startswith(one)):
                score += 2
    return score


def _fallback_related_changes(repo: Path, task: str, *, limit: int) -> list[dict[str, Any]]:
    """Recover recent change relevance from bounded file-name semantics when graph seeding is empty.

    This is deliberately conservative: no source or raw prompt is persisted. It handles natural
    queries such as French ``calcul`` against ``calculator.py`` without returning every recent
    change merely because it is recent.
    """
    task_tokens = _search_tokens(task)
    if not task_tokens:
        return []
    state = continuity_paths(repo).state
    conn = sqlite3.connect(state)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select c.change_id,c.updated_at,c.changed_files_json,
                   p.claim,p.accepted,p.epistemic_status as proof_epistemic_status,
                   ds.points,ds.obligations,ds.budget_passed,
                   u.coverage,u.knowledge_debt
            from changes c
            left join proofs p on p.certificate_id = (
              select p2.certificate_id from proofs p2 where p2.change_id=c.change_id
              order by case p2.epistemic_status when 'VERIFIED' then 4 when 'OBSERVED' then 3 when 'INFERRED' then 2 else 1 end desc,
                       p2.updated_at desc, p2.certificate_id desc limit 1
            )
            left join debt_snapshots ds on ds.change_id=c.change_id
            left join understanding u on u.change_id=c.change_id
            order by c.updated_at desc
            limit 40
            """
        ).fetchall()
    finally:
        conn.close()

    ranked: list[tuple[int, str, sqlite3.Row, list[str]]] = []
    for row in rows:
        try:
            loaded = json.loads(row["changed_files_json"])
            files = [str(value) for value in loaded] if isinstance(loaded, list) else []
        except Exception:
            files = []
        file_tokens: set[str] = set()
        for path in files[:20]:
            file_tokens.update(_search_tokens(path.replace("/", " ").replace("_", " ").replace("-", " ")))
        score = _token_overlap(task_tokens, file_tokens)
        if score:
            verified_bonus = 1 if row["proof_epistemic_status"] == "VERIFIED" and bool(row["accepted"]) else 0
            ranked.append((score + verified_bonus, str(row["updated_at"] or ""), row, files))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)

    result: list[dict[str, Any]] = []
    for _, _, row, files in ranked[: max(1, limit)]:
        result.append(
            {
                "changeId": row["change_id"],
                "updatedAt": row["updated_at"],
                "files": files[:20],
                "proof": None
                if row["claim"] is None
                else {
                    "claim": row["claim"],
                    "accepted": bool(row["accepted"]),
                    "epistemicStatus": row["proof_epistemic_status"],
                },
                "softwareDebt": None
                if row["points"] is None
                else {
                    "points": row["points"],
                    "obligations": row["obligations"],
                    "budgetPassed": None if row["budget_passed"] is None else bool(row["budget_passed"]),
                },
                "understanding": None
                if row["coverage"] is None
                else {"coverage": row["coverage"], "knowledgeDebt": row["knowledge_debt"]},
                "relevanceBasis": "bounded-file-name-overlap",
            }
        )
    return result


def _seeded_base_changes(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep base-layer recent changes only when the task actually seeded their relevance.

    The historical base compiler intentionally had a recency fallback: when neither a graph relation
    nor a related component existed it returned recent changes anyway. That is useful for browsing,
    but unsafe for a task context because recency is not evidence of relevance. The enriched product
    surface therefore requires either an explicit graph link to the change or overlap with a task-
    selected component path. Unknown relevance fails closed and lets the bounded lexical fallback try.
    """
    component_paths = {
        str(item.get("path") or "")
        for item in context.get("components", [])
        if isinstance(item, dict) and item.get("path")
    }
    graph_change_ids: set[str] = set()
    for relation in context.get("relations", []):
        if not isinstance(relation, dict):
            continue
        for endpoint in (relation.get("source"), relation.get("target")):
            value = str(endpoint or "")
            if value.startswith("dwchg_"):
                graph_change_ids.add(value)

    result: list[dict[str, Any]] = []
    for raw in context.get("recentRelatedChanges", []):
        if not isinstance(raw, dict):
            continue
        change_id = str(raw.get("changeId") or "")
        files = {str(value) for value in raw.get("files", []) if str(value)}
        graph_match = change_id in graph_change_ids
        file_match = bool(component_paths & files)
        if not (graph_match or file_match):
            continue
        item = dict(raw)
        item["relevanceBasis"] = "graph-relation" if graph_match else "component-path-overlap"
        result.append(item)
    return result


def _native_setup_scope(repo: Path) -> list[str]:
    path = repo / ".git" / "diffwitness" / "setup-scope.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(value, dict) or value.get("schema") != "diffwitness.setup-scope.v1":
        return []
    adapters = value.get("adapters")
    return [str(item) for item in adapters if str(item)] if isinstance(adapters, list) else []


def _coherent_evidence_guidance(repo: Path, context: dict[str, Any]) -> None:
    adapters = _native_setup_scope(repo)
    if not adapters:
        return
    required = context.get("requiredEvidence")
    if not isinstance(required, list):
        return
    filtered = [
        item
        for item in required
        if not (isinstance(item, dict) and str(item.get("kind") or "") == "change-proof")
    ]
    filtered.append(
        {
            "kind": "native-task-boundary",
            "authority": "diffwitness",
            "note": (
                "Use the configured coding agent normally; its native Stop boundary runs DiffWitness "
                "Proof, Debt and Continuity. `dw guard` is only a manual fallback outside native integration."
            ),
            "adapters": adapters,
        }
    )
    context["requiredEvidence"] = filtered


def compile_context(
    repo: str | Path,
    task: str,
    *,
    max_items: int = 12,
    refresh_structure: bool = True,
) -> dict[str, Any]:
    """Compile base context with bounded debt and fail-closed recent-change relevance."""
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

    seeded = _seeded_base_changes(context)
    context["recentRelatedChanges"] = seeded or _fallback_related_changes(
        root,
        task,
        limit=min(8, max_items),
    )
    _coherent_evidence_guidance(root, context)
    context["context_id"] = _context_id(context)
    return context


__all__ = ["compile_context", "render_context"]
