from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .continuity_state import ensure_state
from .gitops import git, repo_root

_WORD = re.compile(r"[A-Za-z0-9_.:/@-]+")
_KIND_BONUS = {'invariant': 8, 'decision': 6, 'failed-approach': 7, 'objective': 5, 'component': 3, 'file': 2, 'debt': 4}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _WORD.findall(value or '') if len(token) >= 3}


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _score(task_tokens: set[str], row: sqlite3.Row) -> int:
    payload = _loads(row['payload_json'])
    text = ' '.join([str(row['label'] or ''), str(row['entity_id']), json.dumps(payload, ensure_ascii=False, sort_keys=True)])
    overlap = len(task_tokens & _tokens(text))
    score = overlap * 5 + _KIND_BONUS.get(str(row['kind']), 0)
    if row['kind'] == 'invariant' and payload.get('critical') is True:
        score += 20
    if row['epistemic_status'] == 'VERIFIED':
        score += 3
    elif row['epistemic_status'] == 'OBSERVED':
        score += 2
    return score


def _entity_view(row: sqlite3.Row) -> dict[str, Any]:
    payload = _loads(row['payload_json'])
    return {
        'id': row['entity_id'], 'kind': row['kind'], 'label': row['label'], 'epistemicStatus': row['epistemic_status'],
        'updatedAt': row['updated_at'], 'details': payload,
    }


def _relevant_entities(conn: sqlite3.Connection, task: str, limit: int) -> list[dict[str, Any]]:
    task_tokens = _tokens(task)
    rows = conn.execute("select * from entities where lifecycle='active' and kind in ('objective','decision','invariant','failed-approach','component','file') order by updated_at desc limit 1000").fetchall()
    ranked = []
    for row in rows:
        score = _score(task_tokens, row)
        payload = _loads(row['payload_json'])
        if score > _KIND_BONUS.get(str(row['kind']), 0) or (row['kind'] == 'invariant' and payload.get('critical') is True):
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], str(item[1]['updated_at'])))
    return [{**_entity_view(row), 'relevance': score} for score, row in ranked[:limit]]


def _relations_for(conn: sqlite3.Connection, ids: list[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = ','.join('?' for _ in ids)
    rows = conn.execute(
        f"select source_id,predicate,target_id,target_kind,epistemic_status,metadata_json from relations where lifecycle='active' and (source_id in ({placeholders}) or target_id in ({placeholders})) order by updated_at desc limit 200",
        (*ids, *ids),
    ).fetchall()
    return [{
        'source': row['source_id'], 'predicate': row['predicate'], 'target': row['target_id'], 'targetKind': row['target_kind'],
        'epistemicStatus': row['epistemic_status'], 'metadata': _loads(row['metadata_json'])
    } for row in rows]


def _related_files(conn: sqlite3.Connection, task: str, limit: int = 12) -> list[dict[str, Any]]:
    tokens = _tokens(task)
    rows = conn.execute("select component_id,path,language,module_name,epistemic_status,provider from structure_components order by path limit 5000").fetchall()
    scored = []
    for row in rows:
        text = f"{row['path']} {row['module_name'] or ''}"
        overlap = len(tokens & _tokens(text))
        if overlap:
            scored.append((overlap, row))
    scored.sort(key=lambda x: (-x[0], x[1]['path']))
    return [{
        'id': row['component_id'], 'path': row['path'], 'language': row['language'], 'module': row['module_name'],
        'epistemicStatus': row['epistemic_status'], 'provider': row['provider'], 'relevance': score,
    } for score, row in scored[:limit]]


def _recent_changes(conn: sqlite3.Connection, relevant_ids: list[str], related_files: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    change_ids: set[str] = set()
    if relevant_ids:
        placeholders = ','.join('?' for _ in relevant_ids)
        rows = conn.execute(
            f"select source_id,target_id from relations where predicate in ('affects','introduced_in','motivated_by','created','protects','constrains') and (source_id in ({placeholders}) or target_id in ({placeholders}))",
            (*relevant_ids, *relevant_ids),
        ).fetchall()
        for row in rows:
            for value in (row['source_id'], row['target_id']):
                if isinstance(value, str) and value.startswith('dwchg_'):
                    change_ids.add(value)
    related_paths = {str(item['path']) for item in related_files}
    rows = conn.execute(
        "select c.*,p.claim,p.accepted,ds.points,ds.obligations,ds.budget_passed,u.coverage,u.knowledge_debt from changes c left join proofs p on p.change_id=c.change_id left join debt_snapshots ds on ds.change_id=c.change_id left join understanding u on u.change_id=c.change_id order by c.updated_at desc limit 200"
    ).fetchall()
    ranked = []
    for row in rows:
        files = []
        try:
            files = json.loads(row['changed_files_json'])
        except Exception:
            pass
        overlap = len(related_paths & set(files))
        explicit = 2 if row['change_id'] in change_ids else 0
        score = overlap * 4 + explicit
        if score or not (change_ids or related_paths):
            ranked.append((score, row, files))
    ranked.sort(key=lambda item: (-item[0], str(item[1]['updated_at'])))
    result = []
    for _, row, files in ranked[:limit]:
        result.append({
            'changeId': row['change_id'], 'updatedAt': row['updated_at'], 'files': files[:20],
            'proof': None if row['claim'] is None else {'claim': row['claim'], 'accepted': bool(row['accepted'])},
            'softwareDebt': None if row['points'] is None else {'points': row['points'], 'obligations': row['obligations'], 'budgetPassed': None if row['budget_passed'] is None else bool(row['budget_passed'])},
            'understanding': None if row['coverage'] is None else {'coverage': row['coverage'], 'knowledgeDebt': row['knowledge_debt']},
        })
    return result


def _open_debts(conn: sqlite3.Connection, recent_changes: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    ids = [item['changeId'] for item in recent_changes]
    if ids:
        placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(
            f"select debt_id,status,introduced_change_id,last_change_id,epistemic_status,updated_at from debts where status='open' and (introduced_change_id in ({placeholders}) or last_change_id in ({placeholders})) order by updated_at desc limit ?",
            (*ids, *ids, limit),
        ).fetchall()
    else:
        rows = conn.execute("select debt_id,status,introduced_change_id,last_change_id,epistemic_status,updated_at from debts where status='open' order by updated_at desc limit ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def compile_context(repo: str | Path, task: str, *, max_items: int = 12, refresh_structure: bool = True) -> dict[str, Any]:
    root = repo_root(repo)
    state_path = ensure_state(root, include_structure=refresh_structure)
    conn = sqlite3.connect(state_path)
    conn.row_factory = sqlite3.Row
    try:
        entities = _relevant_entities(conn, task, max_items)
        ids = [item['id'] for item in entities]
        relations = _relations_for(conn, ids)
        components = _related_files(conn, task, limit=max_items)
        changes = _recent_changes(conn, ids, components, limit=min(8, max_items))
        debts = _open_debts(conn, changes, limit=max_items)
        event_head_row = conn.execute("select value from meta where key='event_head'").fetchone()
        structure_tree_row = conn.execute("select value from meta where key='structure_tree'").fetchone()
    finally:
        conn.close()
    config = load_config(root, None)
    evidence = []
    test = config.get('test')
    if isinstance(test, str) and test.strip():
        evidence.append({'kind': 'configured-test', 'command': test.strip(), 'authority': 'execution'})
    critical = [e for e in entities if e['kind'] == 'invariant' and e['details'].get('critical') is True]
    for inv in critical:
        evidence.append({'kind': 'invariant', 'id': inv['id'], 'requirement': inv['label'], 'authority': inv['epistemicStatus']})
    evidence.append({'kind': 'change-proof', 'command': 'dw guard -- <agent>', 'authority': 'diffwitness', 'note': 'Proof claims remain authoritative only when established by executed evidence.'})
    warnings = []
    try:
        if git(root, 'status', '--porcelain=v1').strip():
            warnings.append('Working tree is dirty; structure index is bound to HEAD and may lag uncommitted edits.')
    except Exception:
        warnings.append('Git working-tree status could not be checked.')
    payload = {
        'schema_version': 'continuity-context-1', 'generated_at': _now(), 'project': {'name': root.name, 'root': str(root)}, 'task': task,
        'state': {'eventHead': event_head_row[0] if event_head_row else None, 'structureTree': structure_tree_row[0] if structure_tree_row else None},
        'objectives': [e for e in entities if e['kind'] == 'objective'],
        'decisions': [e for e in entities if e['kind'] == 'decision'],
        'invariants': [e for e in entities if e['kind'] == 'invariant'],
        'failedApproaches': [e for e in entities if e['kind'] == 'failed-approach'],
        'components': components, 'relations': relations, 'knownDebt': debts, 'recentRelatedChanges': changes,
        'requiredEvidence': evidence, 'warnings': warnings,
        'trustBoundary': {
            'declared': 'human/project declaration', 'inferred': 'heuristic relation', 'observed': 'directly parsed/recorded fact', 'verified': 'executed authoritative evidence',
            'contextIsAdvisory': True, 'proofRemainsAuthoritative': True,
        },
    }
    stable = {k: v for k, v in payload.items() if k != 'generated_at'}
    payload['context_id'] = 'dwctx_' + hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()[:24]
    return payload


def render_context(context: dict[str, Any], *, max_chars: int = 12000) -> str:
    def block(title: str, items: list[Any], formatter) -> list[str]:
        lines = [title]
        if not items:
            lines.append('  — none recorded/relevant')
        else:
            for item in items:
                lines.append('  ' + formatter(item))
        return lines
    lines = [f"TASK\n{context['task']}", ""]
    lines += block('PROJECT OBJECTIVES', context['objectives'], lambda x: f"{x['id']} [{x['epistemicStatus']}] {x['label']}") + ['']
    lines += block('RELEVANT COMPONENTS', context['components'], lambda x: f"[{x['epistemicStatus']}] {x['path']} ({x['provider']})") + ['']
    lines += block('RELATED DECISIONS', context['decisions'], lambda x: f"{x['id']} [{x['epistemicStatus']}] {x['label']}") + ['']
    lines += block('CRITICAL / RELEVANT INVARIANTS', context['invariants'], lambda x: f"{x['id']} [{x['epistemicStatus']}] {x['label']}") + ['']
    lines += block('KNOWN DEBT', context['knownDebt'], lambda x: f"{x['debt_id']} [{x['epistemic_status']}] open · introduced {x['introduced_change_id'] or 'unknown'}") + ['']
    lines += block('PREVIOUS FAILED APPROACHES', context['failedApproaches'], lambda x: f"{x['id']} [{x['epistemicStatus']}] {x['label']}") + ['']
    lines += block('RECENT RELATED CHANGES', context['recentRelatedChanges'], lambda x: f"{x['changeId']} · files {', '.join(x['files'][:4]) or 'not recorded'} · proof {(x['proof'] or {}).get('claim', 'n/a')}") + ['']
    lines += block('REQUIRED EVIDENCE', context['requiredEvidence'], lambda x: f"{x['kind']}: {x.get('command') or x.get('requirement') or x.get('note') or ''}") + ['']
    if context['warnings']:
        lines += ['WARNINGS', *[f"  ! {w}" for w in context['warnings']], ""]
    lines += [f"CONTEXT {context['context_id']} · advisory context; executed DiffWitness evidence remains authoritative."]
    text = '\n'.join(lines).rstrip() + "\n"
    if len(text) > max_chars:
        text = text[:max(0, max_chars - 80)].rstrip() + "\n… context truncated to configured local budget …\n"
    return text
