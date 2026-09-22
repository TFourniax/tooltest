"""Bounded committed-code references and read-only drift observations."""
from __future__ import annotations

import time
from pathlib import Path

from .continuity_events import ContinuityError, continuity_paths, read_project_events
from .continuity_lifecycle_contract import MemoryHistoryValidator
from .continuity_memory_code_contract import MAX_CODE_PATHS, MEMORY_CODE_PROFILE, code_subject
from .continuity_lineage_contract import lineage_path


def _history(repo: Path, kind: str, identity: str):
    validator = MemoryHistoryValidator()
    for event in read_project_events(continuity_paths(repo).events):
        validator.admit(event)
    current = validator.current.get(identity)
    if current is None or current['assertion']['subject']['kind'] != kind:
        raise ContinuityError(f'unknown {kind}: {identity}')
    binding = validator.code_bindings.get(code_subject(identity, kind)['id'])
    return current, binding


def _selection(paths, dependencies):
    selected = [{'path': path, 'role': role} for role, values in
                (('code', paths or []), ('dependency', dependencies or [])) for path in values]
    if (not 1 <= len(selected) <= MAX_CODE_PATHS
            or any(not lineage_path(f['path']) for f in selected)
            or len({f['path'] for f in selected}) != len(selected)):
        raise ContinuityError('select 1 to 32 distinct safe relative file paths')
    return sorted(selected, key=lambda f: f['path'])


def _snapshot(repo: Path, selected: list[dict], ref: str, *, deadline=None):
    from .continuity_git_history import _git, _oid, _commit, PAGE_SECONDS
    from .continuity_git_lineage import LineageReader
    if not isinstance(ref, str) or not 1 <= len(ref) <= 500 or any(ord(c) < 32 for c in ref):
        raise ContinuityError('invalid commit reference')
    deadline = deadline if deadline is not None else time.monotonic() + PAGE_SECONDS
    oid = _oid(_git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}',
                    limit=128, deadline=deadline).strip())
    commit = _commit(repo, oid, deadline)
    reader = LineageReader(repo, deadline)
    files, _, occupied, _ = reader.inventory(commit['tree'])
    entries, total = [], 0
    for selection in selected:
        path = selection['path']
        value = files.get(path)
        if value is None:
            entries.append({**selection, 'status': 'unsupported' if path.encode('utf-8') in occupied else 'missing'})
            continue
        mode, blob = value
        digest, size = reader.blob(blob)
        total += size
        if total > 8 * 1024 * 1024:
            raise ContinuityError('selected file bytes exceed the total budget')
        entries.append({**selection, 'mode': mode, 'blob': blob, 'sha256': digest, 'bytes': size})
    reader.check_time()
    return {'commit': oid, 'tree': commit['tree'], 'files': entries}


def binding_spec(repo: Path, kind: str, identity: str, action: str, reason: str,
                 *, paths=None, dependencies=None, ref='HEAD') -> dict:
    if action not in ('bind-code', 'revalidate-code'):
        raise ContinuityError('unknown code binding action')
    current, previous = _history(repo, kind, identity)
    if not current['active']:
        raise ContinuityError('code binding requires an active memory')
    if (action == 'bind-code') != (previous is None):
        raise ContinuityError('use bind-code for the first reference, revalidate-code for later references')
    if previous is not None:
        if paths is None:
            paths = [f['path'] for f in previous['payload']['files'] if f['role'] == 'code']
        if dependencies is None:
            dependencies = [f['path'] for f in previous['payload']['files'] if f['role'] == 'dependency']
    selected = _selection(paths, dependencies)
    deadline = time.monotonic() + 60
    snapshot = _snapshot(repo, selected, ref, deadline=deadline)
    if any('status' in f for f in snapshot['files']):
        raise ContinuityError('all selected binding paths must exist as regular committed files')
    return {'event_type': 'memory.code-bound' if previous is None else 'memory.code-revalidated',
            'subject': code_subject(identity, kind), 'epistemic_status': 'DECLARED',
            'payload': {'memory_id': identity, 'memory_kind': kind,
                        'source_event_id': current['assertion']['event_id'],
                        'revision_event_id': current['revision']['event_id'],
                        'previous_binding_event_id': previous['event_id'] if previous else None,
                        'reason': reason, **snapshot},
            'relations': [], 'actor': {'kind': 'human', 'id': 'local-user'}, 'dedupe_key': None,
            'provenance': {'producer': 'diffwitness', 'source': 'human-cli',
                           'diffwitness_profile': MEMORY_CODE_PROFILE}}


def binding_result(kind: str, identity: str, binding: dict) -> dict:
    return {'schema_version': 'memory-code-binding-1', 'identity': identity, 'kind': kind,
            'scope': 'selected committed files', 'worktree_checked': False, 'binding': binding}


def memory_drift(repo: Path, kind: str, identity: str, *, ref='HEAD') -> dict:
    current, binding = _history(repo, kind, identity)
    if binding is None:
        raise ContinuityError('memory has no explicit code reference')
    payload = binding['payload']
    selected = [{key: f[key] for key in ('path', 'role')} for f in payload['files']]
    deadline = time.monotonic() + 60
    snapshot = _snapshot(repo, selected, ref, deadline=deadline)
    # Re-read and verify the old immutable bytes too. Journal hashes establish
    # integrity, not the truth of an externally supplied Git-object assertion.
    baseline = _snapshot(repo, selected, payload['commit'], deadline=deadline)
    if baseline['tree'] != payload['tree'] or baseline['files'] != payload['files']:
        raise ContinuityError('retained code reference does not match its Git objects')
    items = []
    for before, after in zip(payload['files'], snapshot['files']):
        status = after.get('status') or ('unchanged' if before == after else 'changed')
        items.append({'path': before['path'], 'role': before['role'], 'status': status,
                      'before': before, 'after': after})
    stale = (not current['active'] or payload['source_event_id'] != current['assertion']['event_id']
             or payload['revision_event_id'] != current['revision']['event_id'])
    status = 'stale-memory' if stale else ('unchanged' if all(f['status'] == 'unchanged' for f in items) else 'changed')
    return {'schema_version': 'memory-code-drift-1', 'identity': identity, 'kind': kind,
            'scope': 'selected committed files', 'worktree_checked': False,
            'status': status, 'epistemic_status': 'OBSERVED',
            'binding_event_id': binding['event_id'], 'binding_event_hash': binding['event_hash'],
            'assertion_event_id': payload['source_event_id'], 'revision_event_id': payload['revision_event_id'],
            'current_assertion_event_id': current['assertion']['event_id'],
            'current_revision_event_id': current['revision']['event_id'],
            'baseline_commit': payload['commit'], 'baseline_tree': payload['tree'],
            'commit': snapshot['commit'], 'tree': snapshot['tree'], 'items': items}


def render_memory_code(result: dict) -> str:
    from .language import tr
    lines = [tr('Committed code reference: ', 'Référence au code commité : ') + result['identity']]
    if 'binding' in result:
        binding = result['binding']
        lines.extend(['[DECLARED] ' + binding['payload']['reason'], binding['event_id'],
                      binding['payload']['commit']])
        lines.extend(f['path'] + ' [' + f['role'] + ']' for f in binding['payload']['files'])
    else:
        statuses = {'unchanged': 'inchangé', 'changed': 'modifié', 'missing': 'absent',
                    'unsupported': 'type non pris en charge', 'stale-memory': 'révision de mémoire périmée'}
        lines.append('[OBSERVED] ' + tr(result['status'], statuses[result['status']]))
        lines.extend(tr(item['status'], statuses[item['status']]) + ': ' + item['path'] for item in result['items'])
        lines.extend([result['binding_event_id'], result['commit']])
    lines.append(tr('Selected committed files only; local changes and behavior are not validated.',
                    'Fichiers commités sélectionnés uniquement ; modifications locales et comportement non validés.'))
    lines.append(tr('Revalidation is a declared judgment, not executed Proof.',
                    'La revalidation est un jugement déclaré, pas une preuve exécutée.'))
    return '\n'.join(lines)
