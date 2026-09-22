"""Explicit code-reference judgments, separate from assertion and Proof authority."""
from __future__ import annotations

import hashlib
import json
import re

from .continuity_lineage_contract import lineage_path

MEMORY_CODE_PROFILE = 'project-memory-code-1'
MAX_CODE_PATHS = 32


def is_memory_code(event: dict) -> bool:
    return event['provenance'].get('diffwitness_profile') == MEMORY_CODE_PROFILE


def code_subject(identity: str, kind: str) -> dict:
    raw = json.dumps([kind, identity], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return {'id': 'memory-code:' + hashlib.sha256(raw).hexdigest(), 'kind': 'memory-code'}


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError('memory code ' + message)


def _digest(value, size=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(size) + '}', value) is not None


def _event_ref(value):
    return isinstance(value, str) and re.fullmatch('dwev_[0-9a-f]{24}', value) is not None


def validate_memory_code(event: dict) -> None:
    p = event['payload']
    _check(set(p) == {'memory_id', 'memory_kind', 'source_event_id', 'revision_event_id',
                      'previous_binding_event_id', 'reason', 'commit', 'tree', 'files'}, 'payload fields')
    _check(isinstance(p['memory_id'], str) and 0 < len(p['memory_id']) <= 500, 'memory identity')
    _check(p['memory_kind'] in ('objective', 'decision', 'invariant', 'failed-approach'), 'memory kind')
    _check(event['subject'] == code_subject(p['memory_id'], p['memory_kind']), 'separate subject')
    _check(event['event_type'] in ('memory.code-bound', 'memory.code-revalidated'), 'event type')
    _check(event['epistemic_status'] == 'DECLARED', 'association cannot grant Proof authority')
    _check(event['actor'] == {'kind': 'human', 'id': 'local-user'}, 'explicit human source')
    _check(event['provenance'] == {'producer': 'diffwitness', 'source': 'human-cli',
                                  'diffwitness_profile': MEMORY_CODE_PROFILE}, 'provenance')
    _check(event.get('dedupe_key') is None and event.get('relations') == [], 'no unchecked relations or dedupe')
    _check(_event_ref(p['source_event_id']) and _event_ref(p['revision_event_id']), 'assertion/revision references')
    previous = p['previous_binding_event_id']
    _check((event['event_type'] == 'memory.code-bound' and previous is None)
           or (event['event_type'] == 'memory.code-revalidated' and _event_ref(previous)), 'previous binding')
    _check(isinstance(p['reason'], str) and 0 < len(p['reason'].strip()) <= 2000, 'nonempty bounded reason')
    _check((_digest(p['commit'], 40) or _digest(p['commit']))
           and _digest(p['tree'], len(p['commit'])), 'commit/tree identity')
    files = p['files']
    _check(isinstance(files, list) and 1 <= len(files) <= MAX_CODE_PATHS, 'selected path bound')
    for f in files:
        _check(isinstance(f, dict) and set(f) == {'path', 'role', 'mode', 'blob', 'sha256', 'bytes'}, 'file fields')
        _check(lineage_path(f['path']) and f['role'] in ('code', 'dependency'), 'path/role')
        _check(f['mode'] in ('100644', '100755') and _digest(f['blob'], len(p['commit'])), 'regular file identity')
        _check(_digest(f['sha256']) and type(f['bytes']) is int and 0 <= f['bytes'] <= 2 * 1024 * 1024, 'file digest/size')
    _check(files == sorted(files, key=lambda f: f['path']) and len({f['path'] for f in files}) == len(files), 'unique sorted paths')
    _check(sum(f['bytes'] for f in files) <= 8 * 1024 * 1024, 'total selected bytes')
    blobs = {}
    for f in files:
        binding = f['sha256'], f['bytes']
        _check(f['blob'] not in blobs or blobs[f['blob']] == binding, 'consistent blob binding')
        blobs[f['blob']] = binding


def code_descriptor() -> dict:
    return {'event_types': ['memory.code-bound', 'memory.code-revalidated'],
            'association_status': 'DECLARED', 'scope': 'explicit selected committed files',
            'max_paths': MAX_CODE_PATHS, 'worktree_checked': False,
            'grants_proof_authority': False, 'changes_lifecycle': False,
            'reference_policy': 'current active assertion/revision and previous binding',
            'unknown_payload_fields': 'reject'}
