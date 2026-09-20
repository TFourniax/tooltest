"""Typed, conservative relocation hypotheses; no transfer of prior authority."""
from __future__ import annotations

import json
import re

from .continuity_git_contract import file_identity

GIT_LINEAGE_PROFILE = 'project-memory-git-lineage-1'
LINEAGE_METHOD = 'unique-exact-regular-blob-first-parent-1'
MAX_LINEAGE_PAIRS = 32
MAX_LINEAGE_ENTRIES = 32768


def lineage_path(value: object) -> bool:
    try:
        encoded_length = len(json.dumps(value, ensure_ascii=False).encode('utf-8')) if isinstance(value, str) else 0
    except UnicodeError:
        return False
    return (isinstance(value, str) and bool(value) and len(value) <= 500
            and encoded_length <= 512
            and not value.startswith('/') and '\\' not in value and ':' not in value
            and all(part and part not in ('.', '..') and part.casefold() != '.git' for part in value.split('/'))
            and all(ord(char) >= 32 and ord(char) != 127 for char in value))


def lineage_relations(payload: dict) -> list[dict]:
    from .structure_provider import component_id_for_path
    relations = [{'predicate':'describes', 'target':{'id':'git-commit:' + payload['commit'], 'kind':'git-commit'},
                  'epistemic_status':'INFERRED'}]
    for pair in payload['pairs']:
        for direction in ('from', 'to'):
            path = pair[direction]
            for kind, identity in (('file', file_identity), ('component', component_id_for_path)):
                relations.append({'predicate':'relocation_' + direction,
                    'target':{'id':identity(path), 'kind':kind, 'label':path},
                    'epistemic_status':'INFERRED',
                    'metadata':{'from':pair['from'], 'to':pair['to'], 'basis':LINEAGE_METHOD}})
    return relations


def lineage_subject(commit: str) -> dict:
    return {'id':'git-lineage:' + commit, 'kind':'git-lineage', 'label':'Git lineage ' + commit[:12]}


def validate_git_lineage(event: dict) -> None:
    def require(condition, message):
        if not condition:
            raise ValueError('Git lineage profile: ' + message)
    def oid(value):
        return isinstance(value, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value) is not None
    payload = event['payload']
    require(set(payload) == {'commit', 'tree', 'parent', 'parent_tree', 'method', 'pairs', 'coverage'}, 'payload fields')
    commit = payload['commit']
    require(oid(commit) and oid(payload['tree']) and len(commit) == len(payload['tree']), 'commit/tree identities')
    parent = payload['parent']
    require((parent is None and payload['parent_tree'] is None) or
            (oid(parent) and oid(payload['parent_tree']) and len(parent) == len(payload['parent_tree']) == len(commit)), 'parent bindings')
    require(event['event_type'] == 'lineage.inferred' and event['epistemic_status'] == 'INFERRED', 'inferred authority')
    require(event['subject'] == lineage_subject(commit), 'separate assessment subject')
    require(event['actor'] == {'kind':'system', 'id':'diffwitness-git-lineage'}, 'actor')
    require(event['provenance'] == {'producer':'diffwitness', 'source':'git-object', 'source_oid':commit,
                                  'diffwitness_profile':GIT_LINEAGE_PROFILE}, 'provenance')
    require(event.get('dedupe_key') == 'git-lineage-v1:' + commit, 'dedupe identity')
    require(payload['method'] == LINEAGE_METHOD, 'method')
    pairs = payload['pairs']
    require(isinstance(pairs, list) and len(pairs) <= MAX_LINEAGE_PAIRS, 'bounded pairs')
    for pair in pairs:
        require(isinstance(pair, dict) and set(pair) == {'from', 'to', 'mode', 'blob', 'blob_sha256', 'blob_bytes'}, 'pair fields')
        require(lineage_path(pair['from']) and lineage_path(pair['to']) and pair['from'] != pair['to'], 'pair paths')
        require(pair['mode'] in ('100644', '100755') and oid(pair['blob']) and len(pair['blob']) == len(commit), 'regular blob')
        require(isinstance(pair['blob_sha256'], str) and re.fullmatch('[0-9a-f]{64}', pair['blob_sha256']) is not None, 'blob digest')
        require(type(pair['blob_bytes']) is int and 0 <= pair['blob_bytes'] <= 2 * 1024 * 1024, 'blob size')
    require(pairs == sorted(pairs, key=lambda p:(p['from'], p['to'])), 'pair order')
    require(len({(p['mode'], p['blob']) for p in pairs}) == len(pairs), 'unique content groups')
    blobs = {}
    for pair in pairs:
        binding = pair['blob_sha256'], pair['blob_bytes']
        require(pair['blob'] not in blobs or blobs[pair['blob']] == binding, 'consistent blob content')
        blobs[pair['blob']] = binding
    require(len({p['from'] for p in pairs}) == len(pairs) == len({p['to'] for p in pairs}), 'unique endpoints')
    require(not ({p['from'] for p in pairs} & {p['to'] for p in pairs}), 'removed/added disjoint endpoints')
    coverage = payload['coverage']
    counters = {'before_files', 'after_files', 'excluded_before', 'excluded_after', 'removed', 'added',
                'ambiguous_removed', 'ambiguous_added', 'unmatched_removed', 'unmatched_added'}
    require(isinstance(coverage, dict) and set(coverage) == counters | {'complete'}, 'coverage fields')
    require(all(type(coverage[k]) is int and 0 <= coverage[k] <= MAX_LINEAGE_ENTRIES for k in counters), 'coverage counts')
    require(type(coverage['complete']) is bool and coverage['complete'] == (coverage['excluded_before'] == coverage['excluded_after'] == 0), 'coverage limitations')
    require(coverage['removed'] <= coverage['before_files'] and coverage['added'] <= coverage['after_files'], 'inventory coverage')
    for direction, total in (('removed', 'removed'), ('added', 'added')):
        require(coverage[total] == len(pairs) + coverage['ambiguous_' + direction] + coverage['unmatched_' + direction], 'matching coverage')
    require(parent is not None or coverage['before_files'] == coverage['excluded_before'] == coverage['removed'] == 0, 'root coverage')
    require(event.get('relations') == lineage_relations(payload), 'endpoint relation binding')


def git_lineage_descriptor() -> dict:
    return {'event_types':{'lineage.inferred':'INFERRED'}, 'method':LINEAGE_METHOD,
            'max_pairs':MAX_LINEAGE_PAIRS, 'source':'verified immutable tree and matched blob bytes',
            'meaning':'unique exact-byte removed/added file hypothesis; not authenticated move intent',
            'identity_merge':False, 'transfers_assertion_authority':False, 'grants_proof_authority':False}
