"""Bounded first-parent Git bootstrap, independent of the working tree."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .continuity_events import ContinuityError, append_project_events
from .continuity_git_contract import GIT_HISTORY_PROFILE, MAX_HISTORY_PATHS, MAX_MESSAGE_CHARS, file_identity

MAX_COMMIT_BYTES = 256 * 1024
PAGE_SECONDS = 60


def _git(repo: Path, *args: str, limit: int, deadline: float, missing_ok: tuple[int, ...] = ()) -> bytes | None:
    remaining = min(15.0, deadline - time.monotonic())
    if remaining <= 0:
        raise ContinuityError('Git history page exceeded its time budget; retry a smaller page')
    env = {**os.environ, 'GIT_NO_LAZY_FETCH':'1', 'GIT_TERMINAL_PROMPT':'0', 'GIT_OPTIONAL_LOCKS':'0'}
    expired = threading.Event()
    with subprocess.Popen(['git', '--no-replace-objects', '--no-pager', *args], cwd=repo, env=env,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
        def expire():
            expired.set()
            try:
                child.kill()
            except OSError:
                pass
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        try:
            data = child.stdout.read(limit + 1)
            if len(data) > limit:
                child.kill()
                raise ContinuityError('Git history command exceeded its output budget')
            code = child.wait()
            if expired.is_set():
                raise ContinuityError('Git history command timed out; no page was imported')
            if code:
                if code in missing_ok:
                    return None
                raise ContinuityError('Git history object/ref could not be read; no page was imported')
            return data
        finally:
            timer.cancel()
            timer.join()
            if child.poll() is None:
                child.kill()
            child.wait()


def _oid(raw: bytes) -> str:
    value = raw.decode('ascii').strip()
    if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value):
        raise ContinuityError('invalid Git object identity')
    return value


def _commit(repo: Path, oid: str, deadline: float) -> dict:
    size = int(_git(repo, 'cat-file', '-s', oid, limit=32, deadline=deadline))
    if not 0 <= size <= MAX_COMMIT_BYTES:
        raise ContinuityError('Git commit exceeds the 256 KiB bootstrap limit')
    raw = _git(repo, 'cat-file', 'commit', oid, limit=size, deadline=deadline)
    algorithm = 'sha1' if len(oid) == 40 else 'sha256'
    if len(raw) != size or hashlib.new(algorithm, b'commit ' + str(size).encode() + b'\0' + raw).hexdigest() != oid:
        raise ContinuityError('Git commit content does not match its object identity')
    headers, separator, message = raw.partition(b'\n\n')
    if not separator:
        raise ContinuityError('malformed Git commit headers')
    lines = headers.split(b'\n')
    trees = [line[5:] for line in lines if line.startswith(b'tree ')]
    parents = [_oid(line[7:]) for line in lines if line.startswith(b'parent ')]
    committers = [line for line in lines if line.startswith(b'committer ')]
    if len(trees) != 1 or len(committers) != 1 or len(parents) > 64:
        raise ContinuityError('unsupported Git commit headers')
    return {'commit':oid, 'tree':_oid(trees[0]), 'parents':parents,
            'committed_at_unix':int(committers[0].rsplit(b' ', 2)[-2]),
            'message_sha256':hashlib.sha256(message).hexdigest(), 'message_bytes':len(message), '_message':message}


def _files(repo: Path, commit: dict, deadline: float) -> tuple[list[str], int] | None:
    parents = commit['parents']
    if parents and _git(repo, 'cat-file', '-e', parents[0] + '^{commit}', limit=1, deadline=deadline, missing_ok=(1, 128)) is None:
        return None
    refs = [parents[0], commit['commit']] if parents else ['--root', commit['commit']]
    raw = _git(repo, 'diff-tree', '--no-ext-diff', '--no-textconv', '--no-commit-id', '--name-only',
               '--no-renames', '--ignore-submodules=none', '-r', '-z', *refs, '--', limit=1024 * 1024, deadline=deadline)
    if raw and not raw.endswith(b'\0'):
        raise ContinuityError('truncated Git changed-path output')
    paths, omitted = [], 0
    for raw_path in sorted(raw.split(b'\0')[:-1]):
        try:
            name = raw_path.decode('utf-8', errors='strict')
        except UnicodeDecodeError:
            omitted += 1
            continue
        if not name or len(name) > 500 or len(json.dumps(name, ensure_ascii=False).encode('utf-8')) > 512 or len(paths) >= MAX_HISTORY_PATHS:
            omitted += 1
            continue
        paths.append(name)
    return paths, omitted


def _spec(commit: dict, *, message: bool = False) -> dict:
    oid = commit['commit']
    if message:
        text = commit['_message'].decode('utf-8', errors='strict')
        payload = {key:commit[key] for key in ('commit', 'message_sha256', 'message_bytes')}
        payload.update(text=text[:MAX_MESSAGE_CHARS], truncated=len(text)>MAX_MESSAGE_CHARS)
        event_type, kind, label, status = 'commit.message', 'git-message', 'Git message ', 'DECLARED'
        relations = [{'predicate':'describes', 'target':{'id':'git-commit:' + oid, 'kind':'git-commit'}, 'epistemic_status':'DECLARED'}]
    else:
        payload = {key:value for key, value in commit.items() if key != '_message'}
        event_type, kind, label, status = 'commit.observed', 'git-commit', 'Git commit ', 'OBSERVED'
        relations = [{'predicate':'affects', 'target':{'id':file_identity(name), 'kind':'file', 'label':name},
                      'epistemic_status':'OBSERVED', 'metadata':{'basis':'git-first-parent-diff'}} for name in payload['changed_files']]
    return {'event_type':event_type, 'subject':{'id':kind + ':' + oid, 'kind':kind, 'label':label + oid[:12]},
            'epistemic_status':status, 'payload':payload, 'relations':relations,
            'actor':{'kind':'system', 'id':'diffwitness-git-history'},
            'provenance':{'producer':'diffwitness', 'source':'git-object', 'source_oid':oid, 'diffwitness_profile':GIT_HISTORY_PROFILE},
            'dedupe_key':'git-history-v1:' + event_type + ':' + oid}


def bootstrap_git_history(repo: str | Path, *, ref: str = 'HEAD', max_commits: int = 25,
                          include_messages: bool = False) -> dict:
    if type(max_commits) is not int or not 1 <= max_commits <= 100:
        raise ValueError('max_commits must be an integer between 1 and 100')
    if type(include_messages) is not bool or not isinstance(ref, str) or not ref or len(ref) > 512:
        raise ValueError('invalid Git history options')
    deadline = time.monotonic() + PAGE_SECONDS
    root = Path(_git(Path(repo).resolve(), 'rev-parse', '--show-toplevel', limit=8192,
                     deadline=deadline).decode('utf-8').strip()).resolve()
    raw_tip = _git(root, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}',
                   limit=128, deadline=deadline, missing_ok=(128,))
    if raw_tip is None:
        branch = _git(root, 'symbolic-ref', '--quiet', 'HEAD', limit=1024, deadline=deadline).decode('utf-8').strip() if ref == 'HEAD' else ''
        if not branch.startswith('refs/heads/') or _git(root, 'show-ref', '--verify', '--quiet', branch,
                limit=1, deadline=deadline, missing_ok=(1,)) is not None:
            raise ContinuityError('Git history ref is unavailable and is not an unborn HEAD')
        tip = None
    else:
        tip = _oid(raw_tip)
    current, commits, boundary = tip, [], None
    while current is not None and len(commits) < max_commits:
        commit = _commit(root, current, deadline)
        paths = _files(root, commit, deadline)
        if paths is None:
            boundary = 'first parent object unavailable; deepen/repair the repository before resuming'
            break
        commit.update(changed_files=paths[0], files_omitted=paths[1], diff_basis='first-parent')
        commits.append(commit)
        current = commit['parents'][0] if commit['parents'] else None
    specs, messages_unreadable = [], 0
    for commit in reversed(commits):
        specs.append(_spec(commit))
        if include_messages:
            try:
                specs.append(_spec(commit, message=True))
            except UnicodeDecodeError:
                messages_unreadable += 1
    result = append_project_events(repo=root, events=specs)
    return {'schema_version':'git-history-bootstrap-1', 'tip':tip, 'next_ref':current,
            'complete':current is None, 'scope':'first-parent', 'boundary':boundary,
            'commits':len(commits), 'events':len(result), 'created':sum(created for _, created in result),
            'files_omitted':sum(commit['files_omitted'] for commit in commits),
            'messages_unreadable':messages_unreadable, 'include_messages':include_messages,
            'limits':{'commits':max_commits, 'commitBytes':MAX_COMMIT_BYTES, 'pathsPerCommit':MAX_HISTORY_PATHS,
                      'collectionSeconds':PAGE_SECONDS, 'messageChars':MAX_MESSAGE_CHARS}}
