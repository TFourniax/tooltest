"""Local, content-bound structural snapshots. Never Proof, debt, execution or network.

Capture freezes admissible bytes; extraction runs in resumable bounded steps.
The public CLI is the consumer boundary, not the implementation's files/tables.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import time

from .continuity_git_history import _git
from .continuity_events import ContinuityError
from .gitops import repo_root
from .json_contract import strict_json_loads
from .structure_provider import component_id_for_path, _id, resolve_import_reference
from .structure_contract import (FileExtraction, StructuralSymbol, StructuralImport,
                                StructuralCall, validate_extraction)
from .structure_registry import extract_structure, provider_profile, SUPPORTED_SUFFIXES
from .structure_sources import MAX_SOURCE_FILE_BYTES, MAX_SOURCE_TOTAL_BYTES, decode_blob_batch

SCHEMA = 'structure-snapshot-1'
PROFILE = 'project-inventory-5'
MAX_FILES, MAX_INVENTORY, MAX_PAGE, MAX_PAGE_BYTES = 2000, 20000, 100, 2 * 1024 * 1024
EXCLUDED = {'.git', '.idleproof', '.venv', 'venv', 'node_modules', 'vendor', 'dist', 'build', 'target', 'coverage', '__pycache__', '.next', '.cache'}
MANIFESTS = {'package.json', 'pyproject.toml', 'requirements.txt', 'Cargo.toml', 'go.mod', 'pom.xml', 'Gemfile', 'composer.json'}
SECRET = re.compile(r'(?i)(^\.env($|[.\-])|(^|[._-])(credentials?|secrets?|tokens?|passwords?)([._-]|$)|^id_(rsa|ed25519)|\.(pem|key|p12|pfx|keystore)$)')
GENERATED = re.compile(r'(?i)(\.min\.[cm]?js$|\.map$|\.lock$|lock\.json$|\.generated\.|\.py[co]$)')
SNAPSHOT_ID = re.compile(r'dwscan_[a-f0-9]{64}\Z')

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def read_git(root, *args, limit=8 * 1024 * 1024):
    return _git(root, '-c', 'core.fsmonitor=false', *args, limit=limit, deadline=time.monotonic() + 30)

def valid_path(value):
    # Unsupported native names remain excluded; never normalize into another identity.
    return isinstance(value, str) and 0 < len(value) <= 4096 and not re.search(r'[\\:\x00-\x1f\x7f-\x9f]', value) and all(p not in ('', '.', '..') for p in value.split('/'))

def exclusion(path, selection):
    if not valid_path(path):
        return 'unsupported-path'
    parts = path.split('/')
    if any(SECRET.search(p) for p in parts):
        return 'sensitive-name'
    workflow = selection['ci'] and len(parts) == 3 and parts[:2] == ['.github', 'workflows'] and path.endswith(('.yml', '.yaml'))
    if any(p in EXCLUDED or p.startswith('.') for p in parts[:-1]) and not workflow:
        return 'excluded-directory'
    if parts[-1].startswith('.') or GENERATED.search(parts[-1]):
        return 'hidden-or-generated'
    if PurePosixPath(path).suffix.lower() in {'.md', '.rst', '.txt'} and path not in selection['documents'] and parts[-1] not in MANIFESTS:
        return 'document-not-selected'
    return None

def role(path, selection):
    p = PurePosixPath(path)
    if path in selection['documents']:
        return 'declared-document'
    if path.startswith('.github/workflows/'):
        return 'ci'
    if p.name in MANIFESTS:
        return 'manifest'
    if any(part in {'tests', 'test', '__tests__', 'spec'} for part in p.parts) or p.name.startswith('test_') or re.search(r'[._](test|spec)\.', p.name):
        return 'test'
    if p.suffix == '.sql':
        return 'ddl'
    if any(part in {'scripts', 'tools', 'benchmarks'} for part in p.parts):
        return 'tooling'
    if p.suffix in {'.json', '.toml', '.yaml', '.yml'}:
        return 'configuration'
    return 'production' if p.suffix in SUPPORTED_SUFFIXES else 'unsupported'

def storage(root):
    gitdir = Path(read_git(root, 'rev-parse', '--absolute-git-dir', limit=8192).decode('utf-8').strip()).resolve()
    parent = gitdir / 'diffwitness'
    if parent.exists() and linked(parent.lstat()):
        raise ValueError('linked DiffWitness metadata directory rejected')
    parent.mkdir(parents=True, exist_ok=True)
    base = parent / 'structure-scans'
    for directory in (base, base / 'blobs', base / 'facts', base / 'snapshots'):
        if directory.is_symlink() or (directory.exists() and getattr(directory.lstat(), 'st_file_attributes', 0) & 1024):
            raise ValueError('scan storage cannot use links or reparse points')
        directory.mkdir(exist_ok=True, mode=0o700)
    return base

def read_json(path, limit=16 * 1024 * 1024):
    if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 1024:
        raise ValueError('linked scan state rejected')
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('scan state exceeds its bound')
    return strict_json_loads(raw.decode('utf-8'))

def atomic(path, value):
    data = canonical(value)
    temporary = path.with_name(path.name + f'.{os.getpid()}.{time.time_ns()}.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

@contextmanager
def lock(base):
    # OS-owned lock releases on process exit/crash; never guess a stale PID or unlink a live lock.
    target = base / 'writer.lock'
    if target.exists() and linked(target.lstat()):
        raise ValueError('linked scan lock rejected')
    fd = os.open(target, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(fd).st_size == 0: os.write(fd,b' ')
            os.lseek(fd,0,os.SEEK_SET)
            msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise ValueError('scan writer busy; retry after the current bounded batch') from exc
    try:
        os.lseek(fd,1,os.SEEK_SET)
        os.write(fd, canonical({'pid': os.getpid(), 'createdAt': now()}))
        yield
    finally:
        os.close(fd)

def tree_inventory(root, tree):
    records = read_git(root, 'ls-tree', '-r', '-l', '-z', '--full-tree', tree).split(b'\0')
    result = []
    for raw in records:
        if not raw:
            continue
        header, name = raw.split(b'\t', 1)
        mode, kind, oid, size = header.split()
        path = name.decode('utf-8', errors='surrogateescape')
        if any(0xD800 <= ord(c) <= 0xDFFF for c in path):
            path = 'unsupported-native-bytes:' + name.hex()
        result.append({'path': path, 'oid': oid.decode(), 'mode': mode.decode(), 'bytes': int(size) if size != b'-' else 0})
        if len(result) >= MAX_INVENTORY:
            break
    return result, len([r for r in records if r]) <= MAX_INVENTORY

def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 1024)

def source_stamp(info):
    # CPython 3.12+ Windows lstat uses creation time for ctime while fstat can
    # return metadata change time (python/cpython#157671). Compare birthtime
    # across these APIs, retaining the actual fstat ctime check during reading.
    origin = getattr(info, 'st_birthtime_ns', info.st_ctime_ns) if os.name == 'nt' else info.st_ctime_ns
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, origin]

def work_inventory(root, selection):
    rows, stack = [], [('', root)]
    visited = 0
    while stack and len(rows) < MAX_INVENTORY:
        prefix, folder = stack.pop()
        if linked(folder.lstat()) or not folder.resolve().is_relative_to(root):
            raise ValueError('worktree directory changed; restart the scan')
        with os.scandir(folder) as entries:
            for e in entries:
                visited += 1
                if visited > MAX_INVENTORY:
                    return sorted(rows, key=lambda x:x['path']), False
                rel = prefix + e.name
                # Windows DirEntry.stat omits device/inode; lstat and fstat must use
                # the same identity fields for the later mutation check.
                info = Path(e.path).lstat()
                if e.is_dir(follow_symlinks=False) and not linked(info):
                    # Account for excluded directories without enumerating downloaded dependencies.
                    admit_github = selection['ci'] and rel in {'.github', '.github/workflows'}
                    if exclusion(rel + '/probe.py', selection) and not admit_github:
                        rows.append({'path': rel + '/', 'mode': 'directory', 'bytes': 0})
                    else:
                        stack.append((rel + '/', Path(e.path)))
                else:
                    rows.append({'path': rel, 'mode': '100644' if stat.S_ISREG(info.st_mode) and not linked(info) else 'link-or-special', 'bytes': info.st_size,
                                 'stamp': source_stamp(info)})
                if len(rows) >= MAX_INVENTORY:
                    return sorted(rows, key=lambda x:x['path']), False
    return sorted(rows, key=lambda x:x['path']), True

def work_bytes(root, item):
    current = root
    for part in item['path'].split('/'):
        current = current / part
        if linked(current.lstat()):
            raise ValueError('worktree link changed; restart the scan')
    if not current.resolve().is_relative_to(root):
        raise ValueError('worktree source escaped selection')
    if os.name != 'nt':
        # Resolve each directory from an already-open parent. A raced symlink cannot escape.
        parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            parts=item['path'].split('/')
            for part in parts[:-1]:
                next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
                os.close(parent_fd);parent_fd=next_fd
            fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    else:
        fd = os.open(current, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
        # Junctions can race lexical checks on Windows. Verify the opened handle before reading.
        import ctypes
        from ctypes import wintypes
        import msvcrt
        get_path=ctypes.windll.kernel32.GetFinalPathNameByHandleW
        get_path.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
        get_path.restype=wintypes.DWORD
        buffer=ctypes.create_unicode_buffer(32768)
        # Compare device-qualified paths. DOS drive translation can be denied in
        # Windows sandboxes even when both handles are readable.
        length=get_path(msvcrt.get_osfhandle(fd),buffer,len(buffer),2)
        final=buffer.value
        create=ctypes.windll.kernel32.CreateFileW
        create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype=wintypes.HANDLE
        close=ctypes.windll.kernel32.CloseHandle
        close.argtypes=[wintypes.HANDLE]
        root_handle=create(str(root),128,7,None,3,0x02000000,None)
        root_length=0
        try:
            if root_handle != wintypes.HANDLE(-1).value:
                root_length=get_path(root_handle,buffer,len(buffer),2)
                final_root=buffer.value
        finally:
            if root_handle != wintypes.HANDLE(-1).value: close(root_handle)
        if not length or length>=len(buffer) or not root_length or root_length>=len(buffer) or not PureWindowsPath(final).is_relative_to(PureWindowsPath(final_root)):
            os.close(fd)
            raise ValueError('opened worktree handle escaped project')
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        expected = source_stamp(before)
        if expected != item['stamp'] or not stat.S_ISREG(before.st_mode):
            raise ValueError('worktree changed during capture; restart the scan')
        data = handle.read(MAX_SOURCE_FILE_BYTES + 1)
        after = os.fstat(handle.fileno())
        if expected != source_stamp(after) or before.st_ctime_ns != after.st_ctime_ns:
            raise ValueError('worktree changed during capture; restart the scan')
    return data

def blob(base, digest):
    if not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('invalid source digest')
    path = base / 'blobs' / digest
    if linked(path.lstat()):
        raise ValueError('linked source cache rejected')
    with path.open('rb') as handle:
        data = handle.read(MAX_SOURCE_FILE_BYTES + 1)
    if len(data) > MAX_SOURCE_FILE_BYTES or sha(data) != digest:
        raise ValueError('source cache integrity mismatch')
    return data


def git_capture_batches(root, selected):
    for offset in range(0,len(selected),32):
        batch=selected[offset:offset+32]
        request=b''.join(item['oid'].encode('ascii')+b'\n' for item in batch)
        limit=sum(item['bytes'] for item in batch)+128*len(batch)
        raw=_git(root,'-c','core.fsmonitor=false','cat-file','--batch',limit=limit,
                 deadline=time.monotonic()+30,input_bytes=request)
        yield from decode_blob_batch(raw,[(item['path'],item['oid'].encode('ascii'),item['bytes']) for item in batch])

def capture(root, *, source='HEAD', documents=(), ci=False, max_files=MAX_FILES):
    if source not in {'HEAD', 'WORKTREE'} or type(max_files) is not int or not 1 <= max_files <= MAX_FILES:
        raise ValueError('invalid scan source or file budget')
    selection = {'documents': sorted(set(documents)), 'ci': bool(ci), 'maxFiles': max_files}
    if len(selection['documents']) > 64 or any(not valid_path(p) for p in selection['documents']):
        raise ValueError('select at most 64 exact relative document paths')
    base = storage(root)
    with lock(base):
        tree_raw = _git(root, '-c', 'core.fsmonitor=false', 'rev-parse', '--verify', 'HEAD^{tree}', limit=128, deadline=time.monotonic()+15, missing_ok=(128,))
        tree = tree_raw.decode().strip() if tree_raw else None
        if source == 'HEAD' and not tree:
            raise ValueError('HEAD is absent; select WORKTREE for an unborn project')
        profile = {'inventory': PROFILE, 'providers': json.loads(provider_profile()), 'python': list(sys.version_info[:3]),
                   'limits':[MAX_INVENTORY,MAX_SOURCE_FILE_BYTES,MAX_SOURCE_TOTAL_BYTES]}
        capture_key=base / ('capture-'+sha(canonical([source,tree,selection,profile]))+'.json')
        if source=='HEAD' and capture_key.exists():
            value=load(base,read_json(capture_key)['snapshotId'])
            atomic(base/'latest.json',{'snapshotId':value['snapshotId']})
            return summary(value)
        inventory, complete = tree_inventory(root, tree) if source == 'HEAD' else work_inventory(root, selection)
        rows, total, selected = [], 0, 0
        admitted=[]
        for item in inventory:
            path = item['path']
            row = {k:v for k,v in item.items() if k != 'stamp'}
            row['role'] = role(path, selection)
            row['roleAuthority'] = 'INFERRED'
            reason = exclusion(path.rstrip('/'), selection)
            if item['mode'] not in {'100644', '100755'}:
                reason = reason or ('excluded-directory' if item['mode']=='directory' else 'link-or-special')
            if not reason and item['bytes'] > MAX_SOURCE_FILE_BYTES:
                reason = 'file-byte-limit'
            if not reason and (selected >= max_files or total + item['bytes'] > MAX_SOURCE_TOTAL_BYTES):
                reason = 'scan-budget'
            row['eligible'] = reason not in {'sensitive-name', 'unsupported-path', 'excluded-directory', 'hidden-or-generated', 'document-not-selected', 'link-or-special'}
            if reason:
                row.update(status='excluded' if not row['eligible'] else 'omitted', reason=reason)
            else:
                row['status']='admitted'
                admitted.append(item)
                selected+=1
                total+=item['bytes']
            rows.append(row)
        contents=iter(git_capture_batches(root,admitted)) if source=='HEAD' else iter((item['path'],work_bytes(root,item)) for item in admitted)
        for row in rows:
            if row['status']=='admitted':
                captured_path,data=next(contents)
                if captured_path!=row['path']:
                    raise ValueError('capture order differs from selected inventory')
                row['readAttempted'] = True
                if len(data) != row['bytes']:
                    raise ValueError('source length changed during capture')
                try:
                    data.decode('utf-8', errors='strict')
                    if b'\0' in data:
                        raise UnicodeError()
                except UnicodeError:
                    row.update(status='excluded', reason='binary-or-encoding')
                else:
                    digest = sha(data)
                    dest = base / 'blobs' / digest
                    if not dest.exists():
                        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with os.fdopen(fd, 'wb') as handle:
                            handle.write(data)
                    row.update(status='pending', sourceSha256=digest, componentId=component_id_for_path(row['path']))
        if source == 'WORKTREE':
            repeated, complete_again = work_inventory(root, selection)
            if inventory != repeated or complete != complete_again:
                raise ValueError('worktree inventory changed during capture; restart explicitly')
        # Commit identity is deliberately absent: unchanged content has unchanged behavior identity.
        identity = {'source': source, 'tree': tree if source == 'HEAD' else None, 'selection': selection, 'profile': profile, 'inventoryComplete': complete, 'files': rows}
        sid = 'dwscan_' + sha(canonical(identity))
        target = base / 'snapshots' / (sid + '.json')
        if target.exists():
            value = load(base,sid)
        else:
            value = {**identity, 'schemaVersion': SCHEMA, 'snapshotId': sid, 'baseTree': tree, 'capturedAt': now(), 'state': 'pending', 'position': 0, 'reused': 0, 'bytesRead': total,
                     'consistency': 'immutable-git-tree' if source == 'HEAD' else 'captured-bytes-with-two-matching-inventory-observations'}
            atomic(target, value)
        atomic(base / 'latest.json', {'snapshotId': sid})
        if source=='HEAD':atomic(capture_key,{'snapshotId':sid})
        return summary(value)

def load(base, sid=None):
    sid = sid or read_json(base / 'latest.json')['snapshotId']
    if not isinstance(sid, str) or not SNAPSHOT_ID.fullmatch(sid):
        raise ValueError('invalid scan identity')
    value = read_json(base / 'snapshots' / (sid + '.json'))
    if value.get('schemaVersion') != SCHEMA or value.get('snapshotId') != sid:
        raise ValueError('incompatible scan state')
    original = []
    for row in value['files']:
        captured = {k:v for k,v in row.items() if k not in {'extractionSha256','module','language'}}
        if captured.get('sourceSha256'):
            captured['status'] = 'pending'
            captured.pop('reason', None)
        original.append(captured)
    identity = {k:value[k] for k in ('source','tree','selection','profile','inventoryComplete')}
    identity['files'] = original
    if 'dwscan_' + sha(canonical(identity)) != sid:
        raise ValueError('scan manifest integrity mismatch')
    if value['state']=='complete' and value.get('resultSha256')!=sha(canonical({'files':value['files'],'triage':value.get('triage')})):
        raise ValueError('published scan result integrity mismatch')
    return value

def fact_key(value, row):
    return sha(canonical([value['profile'], row['path'], row['role'], row['sourceSha256']]))

def facts(base, value, row):
    stored = read_json(base / 'facts' / (fact_key(value, row) + '.json'), MAX_PAGE_BYTES)
    if stored.get('schema') != 'structure-cached-facts-1' or stored.get('key') != fact_key(value, row):
        raise ValueError('cached extraction profile mismatch')
    result = stored['result']
    if sha(canonical(result)) != stored.get('sha256'):
        raise ValueError('cached extraction integrity mismatch')
    if result.get('path') != row['path'] or result.get('source_sha256') != row['sourceSha256']:
        raise ValueError('cached extraction source mismatch')
    if result.get('schema_version') != 'structure-extraction-2':
        raise ValueError('cached extraction version mismatch')
    if 'extractionSha256' in row and sha(canonical(result)) != row['extractionSha256']:
        raise ValueError('cached extraction changed since snapshot publication')
    return result


def admit_cached(result, row, data):
    """Reuse the existing provider contract when admitting a cache into a new snapshot."""
    fields = {k:v for k,v in result.items() if k not in {'description', 'schema_version'}}
    fields['symbols'] = tuple(StructuralSymbol(**v) for v in fields['symbols'])
    fields['imports'] = tuple(StructuralImport(**{**v, 'members':tuple(v['members']) if v.get('members') is not None else None}) for v in fields['imports'])
    fields['calls'] = tuple(StructuralCall(**v) for v in fields['calls'])
    item = FileExtraction(**fields)
    validate_extraction(item, row['path'], data, language=item.language, provider=item.provider)
    description=result.get('description')
    if not isinstance(description,dict) or description.get('authority')!='OBSERVED':
        raise ValueError('cached source description authority mismatch')

def step(root, sid, *, batch=32, action='step'):
    if type(batch) is not int or not 1 <= batch <= 64 or action not in {'step','cancel','resume'}:
        raise ValueError('invalid scan step')
    base = storage(root)
    with lock(base):
        value = load(base, sid)
        if action == 'cancel':
            if value['state'] != 'complete': value['state'] = 'cancelled'
        elif action == 'resume':
            if value['state'] == 'cancelled': value['state'] = 'pending'
        elif value['state'] not in {'cancelled','complete'}:
            value['state'] = 'pending'
            stop = min(len(value['files']), value['position'] + batch)
            for row in value['files'][value['position']:stop]:
                if row['status'] != 'pending':
                    continue
                target = base / 'facts' / (fact_key(value, row) + '.json')
                if target.exists():
                    result = facts(base, value, row)
                    admit_cached(result, row, blob(base, row['sourceSha256']))
                    value['reused'] += 1
                else:
                    data = blob(base, row['sourceSha256'])
                    try:
                        result = asdict(extract_structure(row['path'], data))
                        result['description'] = describe(row, data, result)
                    except (ValueError, RecursionError):
                        row.update(status='error', reason='extractor-rejected-source')
                        continue
                    result['schema_version'] = 'structure-extraction-2'
                    if len(canonical(result)) > MAX_PAGE_BYTES // 2:
                        row.update(status='error', reason='extraction-output-limit')
                        continue
                    atomic(target, {'schema':'structure-cached-facts-1','key':fact_key(value,row),
                                    'sha256':sha(canonical(result)),'result':result})
                row['extractionSha256'] = sha(canonical(result))
                row['module'], row['language'] = result['module'], result['language']
                row['status'] = 'parsed' if result['parsed'] else 'unsupported' if result['provider']=='file-only' else 'unparsed'
            value['position'] = stop
            if stop == len(value['files']):
                from .structure_triage import triage_captured
                value['triage']=triage_captured(value['files'],lambda row:blob(base,row['sourceSha256']))
                value['resultSha256']=sha(canonical({'files':value['files'],'triage':value['triage']}))
                value['state'] = 'complete'
        atomic(base / 'snapshots' / (value['snapshotId'] + '.json'), value)
        return summary(value)

def describe(row, data, extracted):
    from .structure_summary import describe_source
    return describe_source(row, data, extracted)

def summary(value):
    counts = Counter(r['status'] for r in value['files'])
    return {k:value[k] for k in ('schemaVersion','snapshotId','source','tree','baseTree','selection','profile','capturedAt','state','position','consistency')} | {
        'coverage': {'inventoryEntries':len(value['files']), 'inventoryComplete':value['inventoryComplete'], 'eligible':sum(r['eligible'] for r in value['files']),
                     'read':sum(r.get('readAttempted',False) for r in value['files']), 'capturedSources':sum('sourceSha256' in r for r in value['files']), 'bytesRead':value['bytesRead'], 'reused':value['reused'],
                     'statuses':dict(counts), 'reasons':dict(Counter(r['reason'] for r in value['files'] if r.get('reason'))),
                     'complete':value['state']=='complete' and value['inventoryComplete'] and not any(counts[k] for k in ('pending','omitted','unparsed','unsupported','error')),
                     'excludedDirectoryContents':'not enumerated in WORKTREE', 'inventoryBudgetIncludesDirectories':value['source']=='WORKTREE', 'limits':{'inventoryEntries':MAX_INVENTORY,'files':value['selection']['maxFiles'],'fileBytes':MAX_SOURCE_FILE_BYTES,'totalBytes':MAX_SOURCE_TOTAL_BYTES}},
        'authority':'OBSERVED', 'proof':'UNKNOWN', 'runtimeGraph':False,
        'triage':value.get('triage'), 'resultSha256':value.get('resultSha256')}

def page(root, sid=None, *, cursor=None, limit=50):
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE:
        raise ValueError('invalid page limit')
    base = storage(root)
    value = load(base, sid)
    if value['state'] != 'complete':
        raise ValueError('scan extraction incomplete; resume before paging')
    offset = 0
    if cursor:
        prefix, sep, number = cursor.rpartition(':')
        if prefix != value['snapshotId'] or not sep or not number.isascii() or not number.isdigit():
            raise ValueError('cursor does not belong to the snapshot')
        offset = int(number)
    if not 0 <= offset <= len(value['files']):
        raise ValueError('cursor outside snapshot')
    output, size = [], len(canonical(summary(value)))
    components = {r['path']:r['componentId'] for r in value['files'] if r.get('sourceSha256')}
    paths = {v:k for k,v in components.items()}
    modules = {}
    for r in value['files']:
        if r.get('module'):
            modules.setdefault((r['language'], r['module']), set()).add(r['componentId'])
    for row in value['files'][offset:offset+limit]:
        record = dict(row)
        if row['status'] in {'parsed','unparsed','unsupported'}:
            record['extraction'] = facts(base, value, row)
            if sha(canonical(record['extraction'])) != row['extractionSha256']:
                raise ValueError('cached extraction changed since snapshot publication')
            record['relations'] = []
            record['relationsOmitted'] = max(0, len(record['extraction']['imports'])-512)
            for imported in record['extraction']['imports'][:512]:
                target, resolution = resolve_import_reference(row['path'], row['language'], imported['target'], components, modules)
                reference = target or 'module:' + imported['target']
                record['relations'].append({'id':_id('dwedge', row['componentId'], 'imports', reference),
                    'predicate':'imports','from':row['path'],'to':paths.get(target), 'reference':imported['target'],
                    'line':imported['line'], 'authority':'INFERRED' if target else 'OBSERVED',
                    'resolution':resolution, 'meaning':'test-import-reference, not coverage' if row['role']=='test' else 'import-reference, not runtime execution'})
        length = len(canonical(record))
        # Even the first row must fit. Relations are advisory page enrichment;
        # retain the hash-verified extraction and report every omitted relation.
        while size + length > MAX_PAGE_BYTES - 4096 and record.get('relations'):
            record['relations'].pop()
            record['relationsOmitted'] += 1
            length = len(canonical(record))
        if output and size + length > MAX_PAGE_BYTES - 4096:
            break
        if size + length > MAX_PAGE_BYTES - 4096:
            raise ValueError('structural row exceeds page budget')
        output.append(record)
        size += length
    end = offset + len(output)
    return summary(value) | {'pageSchema':'structure-page-1', 'offset':offset, 'files':output, 'nextCursor':f"{value['snapshotId']}:{end}" if end < len(value['files']) else None}


def source_lines(root, sid, path, start=1, count=40):
    if type(start) is not int or start < 1 or type(count) is not int or not 1 <= count <= 100:
        raise ValueError('invalid source span')
    base = storage(root)
    value = load(base, sid)
    row = next((r for r in value['files'] if r['path'] == path), None)
    if row is None or not row.get('sourceSha256'):
        raise ValueError('path is outside captured readable scope')
    lines = blob(base, row['sourceSha256']).decode('utf-8').splitlines()
    excerpt = [{'line':i+1,'text':line[:2000],'truncated':len(line)>2000}
               for i,line in enumerate(lines) if start <= i+1 < start+count]
    return {'schema':'structure-source-1','snapshotId':value['snapshotId'],'path':path,
            'sourceSha256':row['sourceSha256'],'authority':'OBSERVED','lines':excerpt,'totalLines':len(lines)}

def cli(argv):
    p = argparse.ArgumentParser(prog='dw state structure')
    p.add_argument('action', choices=['start','step','status','cancel','resume','page','source'])
    p.add_argument('--repo', default='.')
    p.add_argument('--source', choices=['HEAD','WORKTREE'], default='HEAD')
    p.add_argument('--document', action='append', default=[])
    p.add_argument('--ci', action='store_true')
    p.add_argument('--max-files', type=int, default=MAX_FILES)
    p.add_argument('--snapshot')
    p.add_argument('--cursor')
    p.add_argument('--limit', type=int, default=50)
    p.add_argument('--batch', type=int, default=32)
    p.add_argument('--path')
    p.add_argument('--line', type=int, default=1)
    p.add_argument('--json', action='store_true', required=True)
    args = p.parse_args(argv)
    try:
        root = repo_root(args.repo)
        if args.action == 'start': result = capture(root, source=args.source, documents=args.document, ci=args.ci, max_files=args.max_files)
        elif args.action == 'page': result = page(root, args.snapshot, cursor=args.cursor, limit=args.limit)
        elif args.action == 'status': result = summary(load(storage(root), args.snapshot))
        elif args.action == 'source': result = source_lines(root, args.snapshot, args.path, args.line, args.limit)
        else: result = step(root, args.snapshot, batch=args.batch, action=args.action)
        print(json.dumps(result, ensure_ascii=False, separators=(',',':'), allow_nan=False))
        return 0
    except (OSError, ValueError, ContinuityError) as exc:
        print('Structure scan unavailable: ' + str(exc), file=sys.stderr)
        return 2
