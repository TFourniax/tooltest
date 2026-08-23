from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import load_config
from .continuity_state import ensure_state
from .engine_protocol import repository_fingerprint
from .gitops import git, repo_root

# Split paths/qualified identifiers into semantic terms rather than treating `payments/refund.py`
# as one opaque token. This keeps the compiler deterministic while materially improving recall.
_WORD = re.compile(r"[A-Za-z0-9]+")
_KIND_BONUS = {"invariant": 8, "decision": 6, "failed-approach": 7, "objective": 5, "component": 3, "file": 2, "debt": 4}
_STATUS_BONUS = {"VERIFIED": 3, "OBSERVED": 2, "INFERRED": 1, "DECLARED": 0}
_MAX_GRAPH_DEPTH = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _WORD.findall(value or "") if len(token) >= 3}


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _entity_text(row: sqlite3.Row) -> str:
    payload = _loads(row["payload_json"])
    return " ".join(
        [str(row["label"] or ""), str(row["entity_id"]), json.dumps(payload, ensure_ascii=False, sort_keys=True)]
    )


def _entity_view(row: sqlite3.Row) -> dict[str, Any]:
    payload = _loads(row["payload_json"])
    return {
        "id": row["entity_id"],
        "kind": row["kind"],
        "label": row["label"],
        "epistemicStatus": row["epistemic_status"],
        "updatedAt": row["updated_at"],
        "details": payload,
    }


def _related_files(conn: sqlite3.Connection, task: str, limit: int = 12) -> list[dict[str, Any]]:
    tokens = _tokens(task)
    rows = conn.execute(
        "select component_id,path,language,module_name,epistemic_status,provider from structure_components order by path"
    ).fetchall()
    scored: list[tuple[int, sqlite3.Row]] = []
    for row in rows:
        text = f"{row['path']} {row['module_name'] or ''}"
        overlap = len(tokens & _tokens(text))
        if overlap:
            scored.append((overlap, row))
    scored.sort(key=lambda item: (-item[0], item[1]["path"]))
    return [
        {
            "id": row["component_id"],
            "path": row["path"],
            "language": row["language"],
            "module": row["module_name"],
            "epistemicStatus": row["epistemic_status"],
            "provider": row["provider"],
            "relevance": score,
        }
        for score, row in scored[:limit]
    ]


def _semantic_relations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    # Project memory must not silently forget an old relation merely because newer history crossed an
    # arbitrary row cap. Performance is handled by the reconstructible SQLite projection and is
    # continuously measured by ContinuityBench; correctness wins over hidden recency truncation.
    return conn.execute(
        "select source_id,predicate,target_id,target_kind,epistemic_status,metadata_json from relations where lifecycle='active' order by updated_at desc"
    ).fetchall()


def _relevant_entities(
    conn: sqlite3.Connection,
    task: str,
    limit: int,
    *,
    seed_component_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Rank project memory by direct task match *and* bounded relation propagation.

    Lexical matching is only a seed. Once an objective/component is relevant, decisions, invariants,
    and failed approaches connected to that seed can enter context even when they use different
    wording. No arbitrary recency window is allowed to erase older still-relevant project memory.
    """
    task_tokens = _tokens(task)
    rows = conn.execute(
        "select * from entities where lifecycle='active' and kind in ('objective','decision','invariant','failed-approach','component','file') order by updated_at desc"
    ).fetchall()
    by_id = {str(row["entity_id"]): row for row in rows}
    scores: dict[str, int] = {}
    depths: dict[str, int] = {}
    reasons: dict[str, str] = {}

    # Direct semantic seeds.
    for entity_id, row in by_id.items():
        payload = _loads(row["payload_json"])
        overlap = len(task_tokens & _tokens(_entity_text(row)))
        if overlap:
            score = overlap * 10 + _KIND_BONUS.get(str(row["kind"]), 0) + _STATUS_BONUS.get(str(row["epistemic_status"]), 0)
            scores[entity_id] = score
            depths[entity_id] = 0
            reasons[entity_id] = f"task-token-overlap:{overlap}"
        if row["kind"] == "invariant" and payload.get("critical") is True:
            score = max(scores.get(entity_id, 0), 30 + _STATUS_BONUS.get(str(row["epistemic_status"]), 0))
            scores[entity_id] = score
            depths[entity_id] = 0
            reasons[entity_id] = "critical-invariant"

    relations = _semantic_relations(conn)
    component_ids = set(seed_component_ids)

    # A task-matched code component is a first-class graph seed. Human project memory attached to
    # that component should surface even if its prose uses completely different words.
    for relation in relations:
        source = str(relation["source_id"])
        target = str(relation["target_id"])
        if target in component_ids and source in by_id:
            candidate = 22 + _STATUS_BONUS.get(str(by_id[source]["epistemic_status"]), 0)
            if candidate > scores.get(source, -1):
                scores[source] = candidate
                depths[source] = 1
                reasons[source] = f"component:{relation['predicate']}:{target}"
        if source in component_ids and target in by_id:
            candidate = 22 + _STATUS_BONUS.get(str(by_id[target]["epistemic_status"]), 0)
            if candidate > scores.get(target, -1):
                scores[target] = candidate
                depths[target] = 1
                reasons[target] = f"component:{relation['predicate']}:{source}"

    adjacency: dict[str, list[tuple[str, str]]] = {entity_id: [] for entity_id in by_id}
    for relation in relations:
        source = str(relation["source_id"])
        target = str(relation["target_id"])
        predicate = str(relation["predicate"])
        if source in by_id and target in by_id:
            # Relevance is traversable in either direction: if an objective matters, a decision
            # motivated_by it matters; if the decision matters, the objective remains useful too.
            adjacency[source].append((target, predicate))
            adjacency[target].append((source, predicate))

    # Two hops are enough to recover patterns such as objective <- decision <- failed approach,
    # while preventing a large project graph from flooding a task with distant history.
    frontier = {entity_id for entity_id, depth in depths.items() if depth <= 1}
    for _ in range(_MAX_GRAPH_DEPTH):
        next_frontier: set[str] = set()
        for source in frontier:
            source_depth = depths.get(source, 0)
            if source_depth >= _MAX_GRAPH_DEPTH:
                continue
            source_score = scores[source]
            for target, predicate in adjacency.get(source, []):
                candidate_depth = source_depth + 1
                if candidate_depth > _MAX_GRAPH_DEPTH:
                    continue
                candidate_score = max(1, int(source_score * 0.68))
                candidate_score += _STATUS_BONUS.get(str(by_id[target]["epistemic_status"]), 0)
                current_depth = depths.get(target, 999)
                if candidate_score > scores.get(target, -1) or candidate_depth < current_depth:
                    scores[target] = max(candidate_score, scores.get(target, 0))
                    depths[target] = min(candidate_depth, current_depth)
                    reasons[target] = f"relation:{predicate}:{source}"
                    next_frontier.add(target)
        frontier = next_frontier
        if not frontier:
            break

    ranked = [
        (scores[entity_id], depths.get(entity_id, 0), by_id[entity_id], reasons.get(entity_id, "graph"))
        for entity_id in scores
    ]
    ranked.sort(key=lambda item: (-item[0], item[1], str(item[2]["updated_at"]), str(item[2]["entity_id"])))
    return [
        {
            **_entity_view(row),
            "relevance": score,
            "relationDepth": depth,
            "relevanceReason": reason,
        }
        for score, depth, row, reason in ranked[:limit]
    ]


def _relations_for(conn: sqlite3.Connection, ids: list[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"select source_id,predicate,target_id,target_kind,epistemic_status,metadata_json from relations where lifecycle='active' and (source_id in ({placeholders}) or target_id in ({placeholders})) order by updated_at desc limit 200",
        (*ids, *ids),
    ).fetchall()
    return [
        {
            "source": row["source_id"],
            "predicate": row["predicate"],
            "target": row["target_id"],
            "targetKind": row["target_kind"],
            "epistemicStatus": row["epistemic_status"],
            "metadata": _loads(row["metadata_json"]),
        }
        for row in rows
    ]


def _recent_changes(
    conn: sqlite3.Connection,
    relevant_ids: list[str],
    related_files: list[dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    change_ids: set[str] = set()
    if relevant_ids:
        placeholders = ",".join("?" for _ in relevant_ids)
        rows = conn.execute(
            f"select source_id,target_id from relations where predicate in ('affects','introduced_in','motivated_by','created','protects','constrains') and (source_id in ({placeholders}) or target_id in ({placeholders}))",
            (*relevant_ids, *relevant_ids),
        ).fetchall()
        for row in rows:
            for value in (row["source_id"], row["target_id"]):
                if isinstance(value, str) and value.startswith("dwchg_"):
                    change_ids.add(value)
    related_paths = {str(item["path"]) for item in related_files}
    rows = conn.execute(
        """
        select c.*,
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
        """
    ).fetchall()
    ranked: list[tuple[int, sqlite3.Row, list[str]]] = []
    for row in rows:
        files: list[str] = []
        try:
            loaded = json.loads(row["changed_files_json"])
            if isinstance(loaded, list):
                files = [str(value) for value in loaded]
        except Exception:
            pass
        overlap = len(related_paths & set(files))
        explicit = 2 if row["change_id"] in change_ids else 0
        score = overlap * 4 + explicit
        if score or not (change_ids or related_paths):
            ranked.append((score, row, files))
    ranked.sort(key=lambda item: (-item[0], str(item[1]["updated_at"])))
    result: list[dict[str, Any]] = []
    for _, row, files in ranked[:limit]:
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
            }
        )
    return result


def _open_debts(conn: sqlite3.Connection, recent_changes: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    ids = [item["changeId"] for item in recent_changes]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"select debt_id,status,introduced_change_id,last_change_id,epistemic_status,updated_at from debts where status='open' and (introduced_change_id in ({placeholders}) or last_change_id in ({placeholders})) order by updated_at desc limit ?",
            (*ids, *ids, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "select debt_id,status,introduced_change_id,last_change_id,epistemic_status,updated_at from debts where status='open' order by updated_at desc limit ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def compile_context(
    repo: str | Path,
    task: str,
    *,
    max_items: int = 12,
    refresh_structure: bool = True,
) -> dict[str, Any]:
    root = repo_root(repo)
    state_path = ensure_state(root, include_structure=refresh_structure)
    conn = sqlite3.connect(state_path)
    conn.row_factory = sqlite3.Row
    try:
        components = _related_files(conn, task, limit=max_items)
        entities = _relevant_entities(
            conn,
            task,
            max_items,
            seed_component_ids=[str(item["id"]) for item in components],
        )
        ids = [item["id"] for item in entities]
        relations = _relations_for(conn, ids)
        changes = _recent_changes(conn, ids, components, limit=min(8, max_items))
        debts = _open_debts(conn, changes, limit=max_items)
        event_head_row = conn.execute("select value from meta where key='event_head'").fetchone()
        structure_tree_row = conn.execute("select value from meta where key='structure_tree'").fetchone()
    finally:
        conn.close()

    config = load_config(root, None)
    evidence: list[dict[str, Any]] = []
    test = config.get("test")
    if isinstance(test, str) and test.strip():
        evidence.append({"kind": "configured-test", "command": test.strip(), "authority": "execution"})
    critical = [entity for entity in entities if entity["kind"] == "invariant" and entity["details"].get("critical") is True]
    for invariant in critical:
        evidence.append(
            {
                "kind": "invariant",
                "id": invariant["id"],
                "requirement": invariant["label"],
                "authority": invariant["epistemicStatus"],
            }
        )
    evidence.append(
        {
            "kind": "change-proof",
            "command": "dw guard -- <agent>",
            "authority": "diffwitness",
            "note": "Proof claims remain authoritative only when established by executed evidence.",
        }
    )

    warnings: list[str] = []
    try:
        if git(root, "status", "--porcelain=v1").strip():
            warnings.append("Working tree is dirty; structure index is bound to HEAD and may lag uncommitted edits.")
    except Exception:
        warnings.append("Git working-tree status could not be checked.")

    payload = {
        "schema_version": "continuity-context-1",
        "generated_at": _now(),
        "project": {"name": root.name, "fingerprint": repository_fingerprint(root)},
        "task": task,
        "state": {
            "eventHead": event_head_row[0] if event_head_row else None,
            "structureTree": structure_tree_row[0] if structure_tree_row else None,
        },
        "objectives": [entity for entity in entities if entity["kind"] == "objective"],
        "decisions": [entity for entity in entities if entity["kind"] == "decision"],
        "invariants": [entity for entity in entities if entity["kind"] == "invariant"],
        "failedApproaches": [entity for entity in entities if entity["kind"] == "failed-approach"],
        "components": components,
        "relations": relations,
        "knownDebt": debts,
        "recentRelatedChanges": changes,
        "requiredEvidence": evidence,
        "warnings": warnings,
        "trustBoundary": {
            "declared": "human/project declaration",
            "inferred": "heuristic relation",
            "observed": "directly parsed/recorded fact",
            "verified": "executed authoritative evidence",
            "contextIsAdvisory": True,
            "proofRemainsAuthoritative": True,
        },
    }
    stable = {key: value for key, value in payload.items() if key != "generated_at"}
    payload["context_id"] = "dwctx_" + hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return payload


def render_context(context: dict[str, Any], *, max_chars: int = 12000) -> str:
    def block(title: str, items: list[Any], formatter) -> list[str]:
        lines = [title]
        if not items:
            lines.append("  — none recorded/relevant")
        else:
            for item in items:
                lines.append("  " + formatter(item))
        return lines

    lines = [f"TASK\n{context['task']}", ""]
    lines += block("PROJECT OBJECTIVES", context["objectives"], lambda item: f"{item['id']} [{item['epistemicStatus']}] {item['label']}") + [""]
    lines += block("RELEVANT COMPONENTS", context["components"], lambda item: f"[{item['epistemicStatus']}] {item['path']} ({item['provider']})") + [""]
    lines += block("RELATED DECISIONS", context["decisions"], lambda item: f"{item['id']} [{item['epistemicStatus']}] {item['label']}") + [""]
    lines += block("CRITICAL / RELEVANT INVARIANTS", context["invariants"], lambda item: f"{item['id']} [{item['epistemicStatus']}] {item['label']}") + [""]
    lines += block("KNOWN DEBT", context["knownDebt"], lambda item: f"{item['debt_id']} [{item['epistemic_status']}] open · introduced {item['introduced_change_id'] or 'unknown'}") + [""]
    lines += block("PREVIOUS FAILED APPROACHES", context["failedApproaches"], lambda item: f"{item['id']} [{item['epistemicStatus']}] {item['label']}") + [""]
    lines += block(
        "RECENT RELATED CHANGES",
        context["recentRelatedChanges"],
        lambda item: f"{item['changeId']} · files {', '.join(item['files'][:4]) or 'not recorded'} · proof {(item['proof'] or {}).get('claim', 'n/a')} [{(item['proof'] or {}).get('epistemicStatus', 'n/a')}]",
    ) + [""]
    lines += block("REQUIRED EVIDENCE", context["requiredEvidence"], lambda item: f"{item['kind']}: {item.get('command') or item.get('requirement') or item.get('note') or ''}") + [""]
    if context["warnings"]:
        lines += ["WARNINGS", *[f"  ! {warning}" for warning in context["warnings"]], ""]
    lines += [f"CONTEXT {context['context_id']} · advisory context; executed DiffWitness evidence remains authoritative."]
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 80)].rstrip() + "\n… context truncated to configured local budget …\n"
    return text
