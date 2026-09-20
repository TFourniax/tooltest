"""Bounded immutable-tree comparisons feeding the existing history journal."""
from __future__ import annotations

import collections
import hashlib
import time
from pathlib import Path

from .continuity_events import ContinuityError, continuity_paths, read_project_events
from .continuity_lineage_contract import (GIT_LINEAGE_PROFILE, LINEAGE_METHOD, MAX_LINEAGE_ENTRIES,
                                          MAX_LINEAGE_PAIRS, lineage_path, lineage_relations, lineage_subject)

MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_TREE_OBJECTS = 512
MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_PAGE_BLOB_BYTES = 8 * 1024 * 1024
MAX_TREE_DEPTH = 64


def lineage_limits() -> dict:
    return {'pairsPerCommit':MAX_LINEAGE_PAIRS, 'pageTreeEntries':MAX_LINEAGE_ENTRIES,
            'pageTreeObjects':MAX_TREE_OBJECTS, 'pageTreeBytes':MAX_TREE_BYTES,
            'treeDepth':MAX_TREE_DEPTH, 'blobBytes':MAX_BLOB_BYTES,
            'pageBlobBytes':MAX_PAGE_BLOB_BYTES, 'pageEventsWithMessages':300}


class LineageReader:
    """Invocation-local verified objects; no filesystem metadata trust shortcut."""
    def __init__(self, repo: Path, deadline: float):
        self.repo, self.deadline = repo, deadline
        self.trees, self.blobs = {}, {}
        self.tree_bytes = self.blob_bytes = self.entries = 0

    def check_time(self):
        if time.monotonic() >= self.deadline:
            raise ContinuityError('Git lineage collection exceeded its time budget; no page imported')

    def object(self, oid: str, kind: str, limit: int) -> bytes:
        from .continuity_git_history import _git
        self.check_time()
        size = int(_git(self.repo, 'cat-file', '-s', oid, limit=32, deadline=self.deadline))
        if not 0 <= size <= limit:
            raise ContinuityError('Git lineage object exceeds its byte budget; no page imported')
        raw = _git(self.repo, 'cat-file', kind, oid, limit=size, deadline=self.deadline)
        algorithm = 'sha1' if len(oid) == 40 else 'sha256'
        digest = hashlib.new(algorithm, kind.encode() + b' ' + str(size).encode() + b'\0' + raw).hexdigest()
        if len(raw) != size or digest != oid:
            raise ContinuityError('Git lineage object bytes do not match their identity; no page imported')
        return raw

    def tree(self, oid: str) -> list[tuple[bytes, bytes, str]]:
        if oid in self.trees:
            return self.trees[oid]
        if len(self.trees) >= MAX_TREE_OBJECTS:
            raise ContinuityError('Git lineage exceeds tree object budget; no page imported')
        raw = self.object(oid, 'tree', MAX_TREE_BYTES - self.tree_bytes)
        self.tree_bytes += len(raw)
        pos, result, previous, names = 0, [], None, set()
        oid_bytes = len(oid) // 2
        while pos < len(raw):
            separator = raw.find(b' ', pos)
            end = raw.find(b'\0', separator + 1) if separator >= 0 else -1
            if separator < 0 or end < 0 or end + 1 + oid_bytes > len(raw):
                raise ContinuityError('malformed Git lineage tree entry')
            mode, name = raw[pos:separator], raw[separator + 1:end]
            if (mode not in (b'40000', b'100644', b'100755', b'120000', b'160000')
                    or not name or b'/' in name or name in (b'.', b'..') or name in names):
                raise ContinuityError('invalid or duplicate Git lineage tree entry')
            key = name + (b'/' if mode == b'40000' else b'\0')
            if previous is not None and key <= previous:
                raise ContinuityError('noncanonical Git lineage tree order')
            child = raw[end + 1:end + 1 + oid_bytes].hex()
            names.add(name)
            result.append((mode, name, child))
            previous, pos = key, end + 1 + oid_bytes
            if len(result) > MAX_LINEAGE_ENTRIES:
                raise ContinuityError('Git lineage tree exceeds entry budget; no page imported')
        self.trees[oid] = result
        return result

    def inventory(self, oid: str | None) -> tuple[dict[str, tuple[str, str]], int, set[bytes], dict[bytes, tuple[str, str]]]:
        files, excluded, occupied, regular = {}, 0, set(), {}
        if oid is None:
            return files, excluded, occupied, regular
        stack = [(oid, b'', 0)]
        while stack:
            self.check_time()
            tree, prefix, depth = stack.pop()
            if depth > MAX_TREE_DEPTH:
                raise ContinuityError('Git lineage exceeds tree depth budget; no page imported')
            for mode, name, child in self.tree(tree):
                self.entries += 1
                if self.entries > MAX_LINEAGE_ENTRIES:
                    raise ContinuityError('Git lineage exceeds page entry budget; no page imported')
                raw_path = prefix + name
                occupied.add(raw_path)
                if mode == b'40000':
                    stack.append((child, raw_path + b'/', depth + 1))
                    continue
                if mode in (b'100644', b'100755'):
                    regular[raw_path] = mode.decode('ascii'), child
                try:
                    path = raw_path.decode('utf-8', errors='strict')
                except UnicodeError:
                    excluded += 1
                    continue
                if mode not in (b'100644', b'100755') or not lineage_path(path):
                    excluded += 1
                    continue
                files[path] = mode.decode('ascii'), child
        return files, excluded, occupied, regular

    def blob(self, oid: str) -> tuple[str, int]:
        if oid not in self.blobs:
            raw = self.object(oid, 'blob', min(MAX_BLOB_BYTES, MAX_PAGE_BLOB_BYTES - self.blob_bytes))
            self.blob_bytes += len(raw)
            self.blobs[oid] = hashlib.sha256(raw).hexdigest(), len(raw)
        return self.blobs[oid]

    def assessment(self, commit: dict) -> dict:
        from .continuity_git_history import _commit
        parent = commit['parents'][0] if commit['parents'] else None
        parent_tree = _commit(self.repo, parent, self.deadline)['tree'] if parent else None
        before, excluded_before, occupied_before, regular_before = self.inventory(parent_tree)
        after, excluded_after, occupied_after, regular_after = self.inventory(commit['tree'])
        removed = {path:value for path,value in before.items() if path.encode('utf-8') not in occupied_after}
        added = {path:value for path,value in after.items() if path.encode('utf-8') not in occupied_before}
        old, new = collections.defaultdict(list), collections.defaultdict(list)
        for path, value in regular_before.items():
            if path not in occupied_after:
                old[value].append(path)
        for path, value in regular_after.items():
            if path not in occupied_before:
                new[value].append(path)
        eligible_removed = {path.encode('utf-8') for path in removed}
        eligible_added = {path.encode('utf-8') for path in added}
        pairs, ambiguous_removed, ambiguous_added = [], 0, 0
        for key in sorted(old.keys() & new.keys()):
            if len(old[key]) != 1 or len(new[key]) != 1:
                ambiguous_removed += sum(path in eligible_removed for path in old[key])
                ambiguous_added += sum(path in eligible_added for path in new[key])
                continue
            if old[key][0] not in eligible_removed or new[key][0] not in eligible_added:
                continue
            if len(pairs) >= MAX_LINEAGE_PAIRS:
                raise ContinuityError('Git lineage exceeds pair budget; no page imported')
            digest, size = self.blob(key[1])
            pairs.append({'from':old[key][0].decode('utf-8'), 'to':new[key][0].decode('utf-8'), 'mode':key[0], 'blob':key[1],
                          'blob_sha256':digest, 'blob_bytes':size})
        pairs.sort(key=lambda pair:(pair['from'], pair['to']))
        payload = {'commit':commit['commit'], 'tree':commit['tree'], 'parent':parent, 'parent_tree':parent_tree,
                   'method':LINEAGE_METHOD, 'pairs':pairs, 'coverage':{
                       'before_files':len(before), 'after_files':len(after),
                       'excluded_before':excluded_before, 'excluded_after':excluded_after,
                       'removed':len(removed), 'added':len(added),
                       'ambiguous_removed':ambiguous_removed, 'ambiguous_added':ambiguous_added,
                       'unmatched_removed':len(removed) - ambiguous_removed - len(pairs),
                       'unmatched_added':len(added) - ambiguous_added - len(pairs),
                       'complete':excluded_before == excluded_after == 0}}
        self.check_time()
        return {'event_type':'lineage.inferred', 'subject':lineage_subject(commit['commit']),
                'epistemic_status':'INFERRED', 'payload':payload, 'relations':lineage_relations(payload),
                'actor':{'kind':'system', 'id':'diffwitness-git-lineage'},
                'provenance':{'producer':'diffwitness', 'source':'git-object', 'source_oid':commit['commit'],
                              'diffwitness_profile':GIT_LINEAGE_PROFILE},
                'dedupe_key':'git-lineage-v1:' + commit['commit']}


def file_lineage(repo: str | Path, path: str, *, limit: int = 50) -> dict:
    if not lineage_path(path) or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('lineage requires a safe relative path and limit between 1 and 100')
    items, matches, assessed = collections.deque(maxlen=limit), 0, 0
    for event in read_project_events(continuity_paths(repo).events):
        if event['provenance'].get('diffwitness_profile') != GIT_LINEAGE_PROFILE:
            continue
        assessed += 1
        payload = event['payload']
        for pair in payload['pairs']:
            if path not in (pair['from'], pair['to']):
                continue
            matches += 1
            items.append({**pair, 'event_id':event['event_id'], 'event_hash':event['event_hash'],
                          'commit':payload['commit'], 'parent':payload['parent'], 'tree':payload['tree'],
                          'epistemic_status':'INFERRED', 'method':payload['method'], 'coverage':payload['coverage']})
    return {'schema_version':'git-file-lineage-1', 'path':path, 'items':list(reversed(items)),
            'matches':matches, 'omitted':max(0, matches-limit), 'assessments':assessed,
            'scope':'imported exact-blob relocation hypotheses; no identity or authority transfer'}


def render_file_lineage(result: dict) -> str:
    from .language import tr
    lines = [tr("File lineage: ", "Filiation du fichier : ") + result['path']]
    if not result['items']:
        lines.append(tr("No imported relocation hypothesis for this path.",
                        "Aucune hypothèse de déplacement importée pour ce chemin."))
    for item in result['items']:
        lines.append(f"[INFERRED] {item['from']} → {item['to']} · {item['commit'][:12]}")
        if not item['coverage']['complete']:
            lines.append(tr("  Limited inventory: some names or file types were excluded.",
                            "  Inventaire limité : certains noms ou types de fichiers sont exclus."))
    if result['omitted']:
        lines.append(tr(f"{result['omitted']} other matches outside the result limit.",
                        f"{result['omitted']} autres correspondances au-delà de la limite de résultats."))
    lines.append(tr("Links inferred from identical content; applicability requires confirmation. Use --json for source references.",
                    "Liens déduits d’un contenu identique ; applicabilité à confirmer. Utiliser --json pour les références sources."))
    return '\n'.join(lines)
