"""Bounded Git history pages, independent of the working tree."""
from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .continuity_events import ContinuityError, append_project_events, continuity_paths, read_project_events
from .continuity_git_contract import GIT_HISTORY_PROFILE, MAX_HISTORY_PATHS, MAX_MESSAGE_CHARS, file_identity
from .json_contract import strict_json_loads

MAX_COMMIT_BYTES = 256 * 1024
PAGE_SECONDS = 60
MAX_BRANCH_REFS = 256
MAX_CURSOR_BYTES = 64 * 1024
MAX_TRAVERSAL_BYTES = 16 * 1024 * 1024
MAX_CURSOR_OFFSET = 1000000


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
        payload = {key:value for key, value in commit.items() if not key.startswith('_')}
        event_type, kind, label, status = 'commit.observed', 'git-commit', 'Git commit ', 'OBSERVED'
        relations = [{'predicate':'affects', 'target':{'id':file_identity(name), 'kind':'file', 'label':name},
                      'epistemic_status':'OBSERVED', 'metadata':{'basis':'git-first-parent-diff'}} for name in payload['changed_files']]
    return {'event_type':event_type, 'subject':{'id':kind + ':' + oid, 'kind':kind, 'label':label + oid[:12]},
            'epistemic_status':status, 'payload':payload, 'relations':relations,
            'actor':{'kind':'system', 'id':'diffwitness-git-history'},
            'provenance':{'producer':'diffwitness', 'source':'git-object', 'source_oid':oid, 'diffwitness_profile':GIT_HISTORY_PROFILE},
            'dedupe_key':'git-history-v1:' + event_type + ':' + oid}


def _cursor_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def _encode_cursor(tips: list[str], offset: int, prefix: bytes, include_messages: bool, include_lineage: bool = False) -> str:
    if offset > MAX_CURSOR_OFFSET:
        raise ContinuityError('Git history cursor exceeds its traversal-count bound')
    body = {'schema_version':'git-history-cursor-1', 'tips':tips, 'offset':offset,
            'prefix_sha256':hashlib.sha256(prefix).hexdigest(), 'include_messages':include_messages}
    if include_lineage:
        body.update(schema_version='git-history-cursor-2', include_lineage=True)
    value = {**body, 'checksum':hashlib.sha256(_cursor_json(body)).hexdigest()}
    return base64.urlsafe_b64encode(_cursor_json(value)).decode('ascii')


def _decode_cursor(cursor: str, include_messages: bool, include_lineage: bool = False) -> dict:
    try:
        if not isinstance(cursor, str) or not 0 < len(cursor) <= MAX_CURSOR_BYTES:
            raise ValueError('cursor size/type')
        raw = base64.b64decode(cursor, altchars=b'-_', validate=True)
        value = strict_json_loads(raw.decode('ascii'))
        keys = {'schema_version', 'tips', 'offset', 'prefix_sha256', 'include_messages', 'checksum'}
        if include_lineage:
            keys.add('include_lineage')
        if not isinstance(value, dict) or set(value) != keys or _cursor_json(value) != raw:
            raise ValueError('cursor shape/encoding')
        version = 'git-history-cursor-2' if include_lineage else 'git-history-cursor-1'
        if include_lineage and value['include_lineage'] is not True:
            raise ValueError('cursor lineage policy')
        if value['schema_version'] != version or type(value['offset']) is not int or not 0 <= value['offset'] <= MAX_CURSOR_OFFSET:
            raise ValueError('cursor version/count')
        tips = value['tips']
        if not isinstance(tips, list) or not 1 <= len(tips) <= MAX_BRANCH_REFS:
            raise ValueError('cursor tips')
        if any(not isinstance(tip, str) or _oid(tip.encode('ascii')) != tip for tip in tips) or tips != sorted(set(tips)) or len({len(tip) for tip in tips}) != 1:
            raise ValueError('cursor tip identities')
        if type(value['include_messages']) is not bool or value['include_messages'] != include_messages:
            raise ValueError('cursor message policy')
        if any(not isinstance(value[k], str) or not re.fullmatch('[0-9a-f]{64}', value[k]) for k in ('checksum', 'prefix_sha256')):
            raise ValueError('cursor digest')
        body = {key:item for key,item in value.items() if key != 'checksum'}
        if hashlib.sha256(_cursor_json(body)).hexdigest() != value['checksum'] or base64.urlsafe_b64encode(raw).decode('ascii') != cursor:
            raise ValueError('cursor checksum')
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, ContinuityError) as exc:
        raise ContinuityError('invalid Git history cursor or message policy') from exc


def _capture_tips(root: Path, deadline: float) -> list[str]:
    raw = _git(root, 'for-each-ref', '--format=%(objectname) %(objecttype)',
               f'--count={MAX_BRANCH_REFS + 1}', 'refs/heads/', 'refs/remotes/',
               limit=32 * 1024, deadline=deadline)
    rows = raw.splitlines()
    if len(rows) > MAX_BRANCH_REFS:
        raise ContinuityError('Git history branch capture exceeds 256 refs; no page imported')
    tips = set()
    for row in rows:
        parts = row.split(b' ')
        if len(parts) != 2 or parts[1] != b'commit':
            raise ContinuityError('Git history branch does not name a commit')
        tips.add(_oid(parts[0]))
    head = _git(root, 'rev-parse', '--verify', 'HEAD^{commit}', limit=128,
                deadline=deadline, missing_ok=(128,))
    if head is not None:
        tips.add(_oid(head))
    if len(tips) > MAX_BRANCH_REFS:
        raise ContinuityError('Git history capture exceeds 256 distinct tips')
    return sorted(tips)


def _validate_imported_prefix(root: Path, rows: list[list[str]], include_messages: bool,
                              deadline: float, include_lineage: bool = False) -> None:
    if not rows:
        return
    wanted = {row[0] for row in rows}
    observed, lineage = {}, {}
    from .continuity_lineage_contract import GIT_LINEAGE_PROFILE
    # A cursor checksum is not authority that earlier pages were imported.
    # Validate actual journal bytes, then require matching admitted history.
    for event in read_project_events(continuity_paths(root).events):
        if include_lineage and event['provenance'].get('diffwitness_profile') == GIT_LINEAGE_PROFILE:
            payload = event['payload']
            if payload['commit'] in wanted:
                if payload['commit'] in lineage and lineage[payload['commit']] != payload:
                    raise ContinuityError('conflicting Git lineage cursor prefix')
                lineage[payload['commit']] = payload
        if event['provenance'].get('diffwitness_profile') != GIT_HISTORY_PROFILE:
            continue
        payload = event['payload']
        if payload['commit'] not in wanted:
            continue
        key = event['event_type'], payload['commit']
        if key in observed and observed[key] != payload:
            raise ContinuityError('conflicting imported Git history in cursor prefix')
        observed[key] = payload
    for oid, *parents in rows:
        commit = observed.get(('commit.observed', oid))
        if commit is None or commit['parents'] != parents:
            raise ContinuityError('Git cursor prefix has unimported or inconsistent commits; restart')
        if include_lineage:
            assessment = lineage.get(oid)
            parent = parents[0] if parents else None
            if assessment is None or assessment['tree'] != commit['tree'] or assessment['parent'] != parent:
                raise ContinuityError('Git cursor prefix has unimported or inconsistent lineage; restart')
            if parent is not None:
                parent_commit = observed.get(('commit.observed', parent))
                parent_tree = parent_commit['tree'] if parent_commit else _commit(root, parent, deadline)['tree']
                if assessment['parent_tree'] != parent_tree:
                    raise ContinuityError('Git cursor lineage parent tree is inconsistent')
        if include_messages:
            message = observed.get(('commit.message', oid))
            if message is None:
                original = _commit(root, oid, deadline)
                try:
                    original['_message'].decode('utf-8', errors='strict')
                except UnicodeDecodeError:
                    continue
                raise ContinuityError('Git cursor prefix has unimported messages; restart with opt-in')
            if any(message[key] != commit[key] for key in ('message_sha256', 'message_bytes')):
                raise ContinuityError('Git cursor prefix message binding is inconsistent')


def _all_branch_page(root: Path, max_commits: int, include_messages: bool,
                     cursor: str | None, deadline: float, include_lineage: bool = False) -> dict:
    previous = _decode_cursor(cursor, include_messages, include_lineage) if cursor is not None else None
    tips = previous['tips'] if previous else _capture_tips(root, deadline)
    offset = previous['offset'] if previous else 0
    raw = _git(root, 'rev-list', '--topo-order', '--parents',
               f'--max-count={offset + max_commits + 1}', *tips, '--',
               limit=MAX_TRAVERSAL_BYTES, deadline=deadline) if tips else b''
    if raw and not raw.endswith(b'\n'):
        raise ContinuityError('truncated Git history traversal')
    lines = raw.splitlines(keepends=True)
    rows, seen = [], set()
    for line in lines:
        fields = line[:-1].split(b' ')
        if not 1 <= len(fields) <= 65:
            raise ContinuityError('invalid Git history parent row')
        row = [_oid(field) for field in fields]
        if any(len(oid) != len(tips[0]) for oid in row) or row[0] in seen:
            raise ContinuityError('duplicate or mixed Git history identities')
        seen.add(row[0])
        rows.append(row)
    prefix = b''.join(lines[:offset])
    if offset > len(rows) or (previous and hashlib.sha256(prefix).hexdigest() != previous['prefix_sha256']):
        raise ContinuityError('Git history continuation order/topology changed; restart idempotently')
    _validate_imported_prefix(root, rows[:offset], include_messages, deadline, include_lineage)
    commits, boundary = [], None
    for row in rows[offset:offset + max_commits]:
        commit = _commit(root, row[0], deadline)
        if commit['parents'] != row[1:]:
            boundary = 'Git traversal parent boundary differs from raw commit; deepen/repair and resume or restart'
            break
        paths = _files(root, commit, deadline)
        if paths is None:
            boundary = 'first parent object unavailable; deepen/repair before resuming'
            break
        commit.update(changed_files=paths[0], files_omitted=paths[1], diff_basis='first-parent')
        commits.append(commit)
    end = offset + len(commits)
    complete = boundary is None and end == len(rows)
    if complete and not set(tips).issubset(seen):
        raise ContinuityError('Git traversal omitted a captured tip')
    following = None if complete else _encode_cursor(tips, end, b''.join(lines[:end]), include_messages, include_lineage)
    _collect_lineage(root, commits, include_lineage, deadline)
    if time.monotonic() >= deadline:
        raise ContinuityError('Git history page exceeded its collection time budget; no page imported')
    result = _append_page(root, commits, include_messages, include_lineage)
    return {**result, 'schema_version':'git-history-bootstrap-2', 'tip':None,
            'tips':tips, 'next_ref':None, 'next_cursor':following, 'complete':complete,
            'scope':'all-branches', 'refs':'HEAD + refs/heads + refs/remotes; locally available only',
            'ref_snapshot_atomic':False, 'boundary':boundary,
            'limits':{**_limits(max_commits, include_lineage), 'branchRefs':MAX_BRANCH_REFS,
                      'cursorBytes':MAX_CURSOR_BYTES, 'traversalBytes':MAX_TRAVERSAL_BYTES,
                      'cursorOffset':MAX_CURSOR_OFFSET}}


def _limits(max_commits: int, include_lineage: bool = False) -> dict:
    result = {'commits':max_commits, 'commitBytes':MAX_COMMIT_BYTES, 'pathsPerCommit':MAX_HISTORY_PATHS,
            'collectionSeconds':PAGE_SECONDS, 'messageChars':MAX_MESSAGE_CHARS}
    if include_lineage:
        from .continuity_git_lineage import lineage_limits
        result['lineage'] = lineage_limits()
    return result


def _collect_lineage(root: Path, commits: list[dict], include_lineage: bool, deadline: float) -> None:
    if include_lineage:
        from .continuity_git_lineage import LineageReader
        reader = LineageReader(root, deadline)
        for commit in commits:
            commit['_lineage'] = reader.assessment(commit)


def _append_page(root: Path, commits: list[dict], include_messages: bool, include_lineage: bool = False) -> dict:
    specs, messages_unreadable = [], 0
    for commit in reversed(commits):
        specs.append(_spec(commit))
        if include_lineage:
            specs.append(commit['_lineage'])
        if include_messages:
            try:
                specs.append(_spec(commit, message=True))
            except UnicodeDecodeError:
                messages_unreadable += 1
    result = append_project_events(repo=root, events=specs)
    return {'commits':len(commits), 'events':len(result), 'created':sum(created for _, created in result),
            'files_omitted':sum(commit['files_omitted'] for commit in commits),
            'messages_unreadable':messages_unreadable, 'include_messages':include_messages,
            'include_lineage':include_lineage,
            'lineage_pairs':sum(len(commit['_lineage']['payload']['pairs']) for commit in commits) if include_lineage else 0,
            'lineage_limited_commits':sum(not commit['_lineage']['payload']['coverage']['complete'] for commit in commits) if include_lineage else 0}


def bootstrap_git_history(repo: str | Path, *, ref: str = 'HEAD', max_commits: int = 25,
                          include_messages: bool = False, all_branches: bool = False,
                          cursor: str | None = None, include_lineage: bool = False) -> dict:
    if type(max_commits) is not int or not 1 <= max_commits <= 100:
        raise ValueError('max_commits must be an integer between 1 and 100')
    if type(include_lineage) is not bool or type(include_messages) is not bool or not isinstance(ref, str) or not ref or len(ref) > 512:
        raise ValueError('invalid Git history options')
    if type(all_branches) is not bool or (all_branches and ref != 'HEAD') or (cursor is not None and not all_branches):
        raise ValueError('all-branches/cursor and first-parent ref options are incompatible')
    deadline = time.monotonic() + PAGE_SECONDS
    root = Path(_git(Path(repo).resolve(), 'rev-parse', '--show-toplevel', limit=8192,
                     deadline=deadline).decode('utf-8').strip()).resolve()
    if all_branches:
        return _all_branch_page(root, max_commits, include_messages, cursor, deadline, include_lineage)
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
    _collect_lineage(root, commits, include_lineage, deadline)
    if time.monotonic() >= deadline:
        raise ContinuityError('Git history page exceeded its collection time budget; no page imported')
    return {**_append_page(root, commits, include_messages, include_lineage),
            'schema_version':'git-history-bootstrap-1', 'tip':tip, 'next_ref':current,
            'complete':current is None, 'scope':'first-parent', 'boundary':boundary,
            'limits':_limits(max_commits, include_lineage)}
