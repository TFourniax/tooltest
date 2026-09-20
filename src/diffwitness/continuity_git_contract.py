"""Admission rules for Git observations and separately declared commit messages."""
from __future__ import annotations

import hashlib
import json
import re

GIT_HISTORY_PROFILE = 'project-memory-git-history-1'
MAX_HISTORY_PATHS = 64
MAX_MESSAGE_CHARS = 4096


def file_identity(path: str) -> str:
    return 'file:' + hashlib.sha256(path.encode('utf-8')).hexdigest()[:24]


def validate_git_history(event: dict) -> None:
    def require(condition, message):
        if not condition:
            raise ValueError('Git history profile: ' + message)
    def oid(value):
        return isinstance(value, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value) is not None
    def sha256(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None

    payload, provenance = event['payload'], event['provenance']
    require(set(provenance) == {'producer', 'source', 'source_oid', 'diffwitness_profile'}, 'provenance fields')
    commit = payload.get('commit')
    require(oid(commit), 'commit identity')
    require(provenance.get('producer') == 'diffwitness' and provenance.get('source') == 'git-object'
            and provenance.get('source_oid') == commit, 'source binding')
    require(event['actor'] == {'kind':'system', 'id':'diffwitness-git-history'}, 'import actor')
    require(sha256(payload.get('message_sha256')), 'message digest')
    require(type(payload.get('message_bytes')) is int and 0 <= payload['message_bytes'] <= 256 * 1024, 'message bytes')
    relations = event.get('relations', [])
    if event['event_type'] == 'commit.observed':
        require(set(payload) == {'commit', 'tree', 'parents', 'committed_at_unix', 'message_sha256',
                                'message_bytes', 'diff_basis', 'changed_files', 'files_omitted'}, 'commit fields')
        require(event['epistemic_status'] == 'OBSERVED', 'commit authority')
        require(event['subject'] == {'id':'git-commit:' + commit, 'kind':'git-commit', 'label':'Git commit ' + commit[:12]}, 'commit subject')
        require(oid(payload.get('tree')) and len(payload['tree']) == len(commit), 'tree identity')
        parents = payload.get('parents')
        require(isinstance(parents, list) and len(parents) <= 64
                and all(oid(value) and len(value) == len(commit) for value in parents), 'parent identities')
        require(payload.get('diff_basis') == 'first-parent', 'diff basis')
        require(type(payload.get('committed_at_unix')) is int, 'commit timestamp')
        paths = payload.get('changed_files')
        require(isinstance(paths, list) and len(paths) <= MAX_HISTORY_PATHS
                and all(isinstance(value, str) and value and len(value) <= 500 and '\0' not in value
                        and not value.startswith('/') and '..' not in value.split('/')
                        and len(json.dumps(value, ensure_ascii=False).encode('utf-8')) <= 512 for value in paths), 'changed paths')
        require(len(set(paths)) == len(paths) and len(relations) == len(paths), 'path relation coverage')
        require(type(payload.get('files_omitted')) is int and payload['files_omitted'] >= 0, 'omitted paths')
        for name, relation in zip(paths, relations, strict=True):
            require(relation == {'predicate':'affects', 'target':{'id':file_identity(name), 'kind':'file', 'label':name},
                    'epistemic_status':'OBSERVED', 'metadata':{'basis':'git-first-parent-diff'}}, 'path relation binding')
    elif event['event_type'] == 'commit.message':
        require(set(payload) == {'commit', 'message_sha256', 'message_bytes', 'text', 'truncated'}, 'message fields')
        require(event['epistemic_status'] == 'DECLARED', 'message authority')
        text = payload.get('text')
        require(isinstance(text, str) and len(text) <= MAX_MESSAGE_CHARS, 'message preview')
        require(type(payload.get('truncated')) is bool, 'message truncation')
        encoded = text.encode('utf-8')
        if payload['truncated']:
            require(len(text) == MAX_MESSAGE_CHARS and payload['message_bytes'] > len(encoded), 'truncated message coverage')
        else:
            require(len(encoded) == payload['message_bytes'] and hashlib.sha256(encoded).hexdigest() == payload['message_sha256'], 'message digest binding')
        require(event['subject'] == {'id':'git-message:' + commit, 'kind':'git-message', 'label':'Git message ' + commit[:12]}, 'message subject')
        require(relations == [{'predicate':'describes', 'target':{'id':'git-commit:' + commit, 'kind':'git-commit'},
                               'epistemic_status':'DECLARED'}], 'message relation authority/binding')
    else:
        raise ValueError('Git history profile: unsupported event type')


def git_history_descriptor() -> dict:
    return {'event_types':{'commit.observed':'OBSERVED', 'commit.message':'DECLARED'},
            'source':'git-object', 'source_binding':'commit object ID; not authenticated authorship',
            'traversal':'first-parent', 'messages':'explicit opt-in, bounded UTF-8 preview',
            'traversal_modes':['first-parent', 'all-branches'],
            'all_branches':'opt-in captured local HEAD/heads/remotes; journal-bound continuation; first-parent file diffs',
            'max_paths':MAX_HISTORY_PATHS, 'max_message_chars':MAX_MESSAGE_CHARS,
            'grants_proof_authority':False, 'unprofiled_history':'preserve'}
