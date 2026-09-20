from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diffwitness.continuity_events import ContinuityError, append_project_events, continuity_paths, read_project_events
from diffwitness.continuity_git_history import bootstrap_git_history
from diffwitness.continuity_state import rebuild_state


class GitLineageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Generated lineage fixture')
        self.git('config', 'user.email', 'private@example.test')
        self.write('old.py', 'PRIVATE_SOURCE = 42\n')
        self.root = self.commit('PRIVATE_MESSAGE root')
        self.events = continuity_paths(self.repo).events

    def git(self, *args, data=None):
        return subprocess.check_output(['git', *args], cwd=self.repo, input=data).decode('utf-8').strip()

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    def commit(self, message='generated change'):
        self.git('add', '-A')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def move(self, source='old.py', target='new.py'):
        (self.repo / target).parent.mkdir(parents=True, exist_ok=True)
        self.git('mv', '--', source, target)
        return self.commit()

    def page(self, **options):
        return bootstrap_git_history(self.repo, include_lineage=True, **options)

    def assessments(self):
        return [e for e in read_project_events(self.events) if e['event_type'] == 'lineage.inferred']

    def test_opt_in_persists_inferred_relocation_with_exact_binding_and_no_proof_transfer(self):
        tip = self.move(target='nested/créer facture.py')
        self.write('nested/créer facture.py', 'DIRTY_PRIVATE = 77\n')
        self.write('untracked.py', 'UNTRACKED_PRIVATE = 12\n')
        before = (self.repo / '.git/index').read_bytes()
        bootstrap_git_history(self.repo)
        original = self.events.read_bytes()
        self.assertEqual(self.assessments(), [])
        result = self.page()
        self.assertEqual(result['created'], 2)
        assessment = next(e for e in self.assessments() if e['payload']['commit'] == tip)
        payload = assessment['payload']
        self.assertEqual(payload['parent'], self.root)
        self.assertEqual(payload['tree'], self.git('rev-parse', tip + '^{tree}'))
        self.assertEqual([(p['from'], p['to']) for p in payload['pairs']], [('old.py', 'nested/créer facture.py')])
        self.assertEqual(payload['pairs'][0]['blob'], self.git('rev-parse', tip + ':nested/créer facture.py'))
        self.assertTrue(payload['coverage']['complete'])
        self.assertEqual(assessment['epistemic_status'], 'INFERRED')
        self.assertTrue(all(r['epistemic_status'] == 'INFERRED' for r in assessment['relations']))
        self.assertTrue(self.events.read_bytes().startswith(original))
        for secret in (b'PRIVATE_SOURCE', b'PRIVATE_MESSAGE', b'private@example', b'DIRTY_PRIVATE', b'UNTRACKED_PRIVATE'):
            self.assertNotIn(secret, self.events.read_bytes())
        self.assertEqual((self.repo / '.git/index').read_bytes(), before)
        stable = self.events.read_bytes()
        self.assertEqual(self.page()['created'], 0)
        self.assertEqual(self.events.read_bytes(), stable)
        with contextlib.closing(sqlite3.connect(rebuild_state(self.repo, include_structure=False))) as conn:
            self.assertEqual(conn.execute('select count(*) from proofs').fetchone()[0], 0)

    def test_duplicate_content_copy_edit_and_mode_changes_are_not_silent_identity_merges(self):
        self.write('second.py', 'PRIVATE_SOURCE = 42\n')
        self.commit()
        self.git('mv', 'old.py', 'first-new.py')
        self.git('mv', 'second.py', 'second-new.py')
        ambiguous = self.commit()
        result = self.page(max_commits=1)
        a = self.assessments()[0]['payload']
        self.assertEqual(a['commit'], ambiguous)
        self.assertEqual(a['pairs'], [])
        self.assertEqual(a['coverage']['ambiguous_removed'], 2)
        self.assertEqual(a['coverage']['ambiguous_added'], 2)
        self.assertEqual(result['lineage_pairs'], 0)
        self.write('copy.py', (self.repo / 'first-new.py').read_text())
        self.commit()
        self.page(max_commits=1)
        self.assertEqual(self.assessments()[-1]['payload']['pairs'], [])
        self.git('mv', 'copy.py', 'edited.py')
        self.write('edited.py', 'PRIVATE_SOURCE = 43\n')
        self.commit()
        self.page(max_commits=1)
        self.assertEqual(self.assessments()[-1]['payload']['pairs'], [])
        self.git('mv', 'edited.py', 'executable.py')
        self.git('update-index', '--chmod=+x', 'executable.py')
        self.git('commit', '-qm', 'mode change')
        self.page(max_commits=1)
        self.assertEqual(self.assessments()[-1]['payload']['pairs'], [])

    def test_cursor_policy_is_compatible_and_forged_opt_in_cannot_skip_assessments(self):
        self.move()
        legacy = bootstrap_git_history(self.repo, all_branches=True, max_commits=1)
        decoded = json.loads(base64.urlsafe_b64decode(legacy['next_cursor']))
        self.assertEqual(decoded['schema_version'], 'git-history-cursor-1')
        raw = self.events.read_bytes()
        with self.assertRaises((ValueError, ContinuityError)):
            self.page(all_branches=True, cursor=legacy['next_cursor'])
        decoded.update(schema_version='git-history-cursor-2', include_lineage=True)
        decoded.pop('checksum')
        encode = lambda d: json.dumps(d, sort_keys=True, separators=(',', ':')).encode('ascii')
        decoded['checksum'] = hashlib.sha256(encode(decoded)).hexdigest()
        forged = base64.urlsafe_b64encode(encode(decoded)).decode('ascii')
        with self.assertRaises(ContinuityError):
            self.page(all_branches=True, cursor=forged)
        self.assertEqual(self.events.read_bytes(), raw)
        enriched = self.page(all_branches=True, max_commits=1)
        self.assertEqual(enriched['created'], 1)
        self.assertEqual(json.loads(base64.urlsafe_b64decode(enriched['next_cursor']))['schema_version'], 'git-history-cursor-2')
        self.assertTrue(self.page(all_branches=True, cursor=enriched['next_cursor'])['complete'])
        self.assertEqual(len(self.assessments()), 2)

    def test_profile_rejects_promoted_authority_unbound_paths_and_altered_relations(self):
        self.move()
        self.page(max_commits=1)
        original = self.assessments()[0]
        for mutation in ('authority', 'path', 'relation', 'tree', 'coverage'):
            bad = copy.deepcopy(original)
            bad['dedupe_key'] = None
            if mutation == 'authority':
                bad['epistemic_status'] = 'VERIFIED'
            elif mutation == 'path':
                bad['payload']['pairs'][0]['to'] = '../escape.py'
            elif mutation == 'relation':
                bad['relations'][0]['epistemic_status'] = 'VERIFIED'
            elif mutation == 'tree':
                bad['payload']['tree'] = 'bogus'
            else:
                bad['payload']['coverage']['removed'] = -1
            with self.subTest(mutation=mutation), self.assertRaises(ContinuityError):
                append_project_events(repo=self.repo, events=[bad])

    def test_rename_back_and_branch_divergence_retain_distinct_cited_observations(self):
        main = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'side')
        side = self.move(target='side.py')
        self.git('checkout', '-q', main)
        moved = self.move()
        back = self.move('new.py', 'old.py')
        self.page(all_branches=True)
        pairs = {e['payload']['commit']: [(p['from'], p['to']) for p in e['payload']['pairs']] for e in self.assessments()}
        self.assertEqual(pairs[side], [('old.py', 'side.py')])
        self.assertEqual(pairs[moved], [('old.py', 'new.py')])
        self.assertEqual(pairs[back], [('new.py', 'old.py')])
        for language in ('fr', 'en'):
            result = subprocess.run([sys.executable, '-m', 'diffwitness.entry', '--language', language, 'state', 'lineage', '--repo', str(self.repo),
                                     '--path', 'old.py', '--json'], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            view = json.loads(result.stdout)
            self.assertEqual(len(view['items']), 3)
            self.assertEqual({i['commit'] for i in view['items']}, {side, moved, back})
            self.assertTrue(all(i['event_id'] and i['epistemic_status'] == 'INFERRED' for i in view['items']))

    def test_nonregular_replacement_is_not_a_removed_path(self):
        blob = self.git('rev-parse', 'HEAD:old.py')
        target = self.git('hash-object', '-w', '--stdin', data=b'elsewhere.py')
        tree = self.git('mktree', '-z', data=(f'100644 blob {blob}\tnew.py\0' + f'120000 blob {target}\told.py\0').encode())
        commit = self.git('commit-tree', tree, '-p', self.root, data=b'generated replacement\n')
        self.git('update-ref', 'HEAD', commit)
        self.page(max_commits=1)
        payload = self.assessments()[0]['payload']
        self.assertEqual(payload['pairs'], [])
        self.assertEqual(payload['coverage']['excluded_after'], 1)
        self.assertFalse(payload['coverage']['complete'])

    def test_profile_validation_has_specific_causes_independent_of_dedupe(self):
        from diffwitness.continuity_lineage_contract import validate_git_lineage
        self.move()
        self.page(max_commits=1)
        original = self.assessments()[0]
        mutations = [
            ('inferred authority', lambda e:e.update(epistemic_status='VERIFIED')),
            ('pair paths', lambda e:e['payload']['pairs'][0].update(to='../escape')),
            ('endpoint relation', lambda e:e['relations'][0].update(epistemic_status='VERIFIED')),
            ('coverage counts', lambda e:e['payload']['coverage'].update(removed=-1)),
            ('matching coverage', lambda e:e['payload']['coverage'].update(unmatched_added=1)),
        ]
        for reason, mutate in mutations:
            bad = copy.deepcopy(original)
            mutate(bad)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                validate_git_lineage(bad)

    def test_corrupt_tree_and_blob_bytes_are_rechecked_after_successful_import(self):
        import zlib
        self.move()
        self.page(max_commits=1)
        journal = self.events.read_bytes()
        for object_ref in ('HEAD^{tree}', 'HEAD:new.py'):
            oid = self.git('rev-parse', object_ref)
            path = self.repo / '.git/objects' / oid[:2] / oid[2:]
            raw, stamp = path.read_bytes(), path.stat()
            decoded = zlib.decompress(raw)
            corrupted = decoded.replace(b'new.py', b'bad.py') if object_ref.endswith('tree}') else decoded.replace(b'42', b'43')
            self.assertNotEqual(corrupted, decoded)
            self.assertEqual(len(corrupted), len(decoded))
            path.chmod(0o600)
            path.write_bytes(zlib.compress(corrupted))
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            try:
                with self.subTest(object_ref=object_ref), self.assertRaisesRegex(ContinuityError, 'identity'):
                    self.page(max_commits=1)
                self.assertEqual(self.events.read_bytes(), journal)
            finally:
                path.write_bytes(raw)

    def test_valid_hash_does_not_admit_malformed_or_unsafe_tree_structure(self):
        import time
        from diffwitness.continuity_git_lineage import LineageReader
        blob = bytes.fromhex(self.git('rev-parse', 'HEAD:old.py'))
        for raw in (b'100644 a\0' + blob + b'100644 a\0' + blob,
                    b'100644 z\0' + blob + b'100644 a\0' + blob,
                    b'100644 ../escape\0' + blob, b'100600 a\0' + blob,
                    b'100644 a\0' + blob[:-1]):
            oid = self.git('hash-object', '-t', 'tree', '--literally', '-w', '--stdin', data=raw)
            with self.subTest(raw=raw[:18]), self.assertRaises(ContinuityError):
                LineageReader(self.repo, time.monotonic()+15).inventory(oid)
        raw = b'100644 .git\0' + blob + b'100644 bad\xff\0' + blob
        oid = self.git('hash-object', '-t', 'tree', '--literally', '-w', '--stdin', data=raw)
        files, excluded, _, _ = LineageReader(self.repo, time.monotonic()+15).inventory(oid)
        self.assertEqual(files, {})
        self.assertEqual(excluded, 2)
        self.assertFalse(self.events.exists())

    def test_limits_and_preappend_interruption_preserve_atomic_retry(self):
        import concurrent.futures
        import diffwitness.continuity_git_lineage as lineage
        self.move()
        for limit_name, value in (('MAX_LINEAGE_ENTRIES', 1), ('MAX_TREE_OBJECTS', 0), ('MAX_TREE_BYTES', 1),
                                  ('MAX_BLOB_BYTES', 1), ('MAX_PAGE_BLOB_BYTES', 1), ('MAX_LINEAGE_PAIRS', 0)):
            with self.subTest(limit=limit_name), patch.object(lineage, limit_name, value), self.assertRaises(ContinuityError):
                self.page(max_commits=1)
            self.assertFalse(self.events.exists())
        with patch('diffwitness.continuity_git_history.append_project_events', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                self.page()
        self.assertFalse(self.events.exists())
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _:self.page(), range(2)))
        self.assertEqual(sum(r['created'] for r in results), 4)
        self.assertEqual(len(read_project_events(self.events)), 4)

    def test_sha256_root_merge_and_shallow_boundary_preserve_original_meaning(self):
        main = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'side')
        side = self.move()
        self.git('checkout', '-q', main)
        self.write('unrelated.py', 'x = 10\n')
        self.commit()
        self.git('merge', '--no-ff', '-qm', 'generated merge', 'side')
        tip = self.git('rev-parse', 'HEAD')
        self.page(all_branches=True)
        by_commit = {e['payload']['commit']:e['payload'] for e in self.assessments()}
        self.assertEqual(by_commit[tip]['pairs'][0]['from'], 'old.py')
        self.assertEqual(by_commit[side]['pairs'][0]['from'], 'old.py')
        shallow = self.base / 'shallow'
        subprocess.run(['git', 'clone', '-q', '--depth', '1', self.repo.as_uri(), str(shallow)], check=True)
        result = bootstrap_git_history(shallow, all_branches=True, include_lineage=True)
        self.assertFalse(result['complete'])
        self.assertEqual(result['created'], 0)
        sha256 = self.base / 'sha256'
        sha256.mkdir()
        old = self.repo
        self.repo = sha256
        try:
            self.git('init', '-q', '--object-format=sha256')
            self.git('config', 'user.name', 'Generated fixture')
            self.git('config', 'user.email', 'generated@example.test')
            self.write('old.py', 'secret = 1\n')
            self.commit()
            tip = self.move()
            self.page()
            rows = read_project_events(continuity_paths(sha256).events)
            assessment = next(e['payload'] for e in rows if e['event_type'] == 'lineage.inferred' and e['payload']['commit'] == tip)
            self.assertEqual(len(assessment['pairs'][0]['blob']), 64)
        finally:
            self.repo = old

    def test_query_limits_exact_citations_and_journal_corruption(self):
        from diffwitness.continuity_git_lineage import file_lineage
        self.move()
        self.move('new.py', 'old.py')
        self.page()
        result = file_lineage(self.repo, 'old.py', limit=1)
        self.assertEqual((len(result['items']), result['matches'], result['omitted']), (1, 2, 1))
        source = next(e for e in self.assessments() if e['event_id'] == result['items'][0]['event_id'])
        self.assertEqual(result['items'][0]['event_hash'], source['event_hash'])
        self.assertEqual(result['items'][0]['commit'], source['payload']['commit'])
        for path in ('../escape', '/absolute', 'bad\\path', '\udcff'):
            with self.subTest(path=repr(path)), self.assertRaises(ValueError):
                file_lineage(self.repo, path)
        raw, stamp = self.events.read_bytes(), self.events.stat()
        changed = raw.replace(b'INFERRED', b'VERIFIED', 1)
        self.assertEqual(len(raw), len(changed))
        self.events.write_bytes(changed)
        os.utime(self.events, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaises(ContinuityError):
            file_lineage(self.repo, 'old.py')

    def test_excluded_regular_names_still_prevent_false_unique_matches(self):
        blob = self.git('rev-parse', 'HEAD:old.py')
        tree = self.git('mktree', '-z', data=(b'100644 blob ' + blob.encode() + b'\tbad\xff.py\0' +
                                              b'100644 blob ' + blob.encode() + b'\told.py\0'))
        parent = self.git('commit-tree', tree, data=b'generated duplicate-content parent\n')
        next_tree = self.git('mktree', '-z', data=f'100644 blob {blob}\tnew.py\0'.encode())
        tip = self.git('commit-tree', next_tree, '-p', parent, data=b'generated ambiguous change\n')
        self.git('update-ref', 'HEAD', tip)
        self.page(max_commits=1)
        assessment = self.assessments()[0]['payload']
        self.assertEqual(assessment['pairs'], [])
        self.assertEqual(assessment['coverage']['excluded_before'], 1)
        self.assertEqual(assessment['coverage']['ambiguous_removed'], 1)
        self.assertEqual(assessment['coverage']['ambiguous_added'], 1)
        self.assertFalse(assessment['coverage']['complete'])

    def test_existing_assertion_authority_stays_bound_to_its_original_entity(self):
        from diffwitness.continuity_git_contract import file_identity
        from diffwitness.structure_provider import component_id_for_path
        specs = [{'event_type':'fixture.observed', 'subject':{'id':identity('old.py'), 'kind':kind, 'label':'old assertion'},
                  'epistemic_status':'OBSERVED', 'payload':{'original':'unchanged'}, 'relations':[],
                  'actor':{'kind':'system'}, 'provenance':{'source':'generated-fixture'}}
                 for identity, kind in ((file_identity, 'file'), (component_id_for_path, 'component'))]
        original = append_project_events(repo=self.repo, events=specs)
        self.move()
        self.page()
        with contextlib.closing(sqlite3.connect(rebuild_state(self.repo, include_structure=False))) as conn:
            for event, _ in original:
                self.assertEqual(conn.execute('select epistemic_status,source_event_id from entities where entity_id=?',
                                 (event['subject']['id'],)).fetchone(), ('OBSERVED', event['event_id']))
            for identity in (file_identity, component_id_for_path):
                self.assertEqual(conn.execute('select count(*) from entities where entity_id=?', (identity('new.py'),)).fetchone()[0], 0)
            self.assertEqual(conn.execute('select count(*) from proofs').fetchone()[0], 0)

    def test_real_pair_budget_rejects_whole_page_and_deadline_rejects_without_append(self):
        import time
        import diffwitness.continuity_git_lineage as lineage
        for n in range(33):
            self.write(f'old-{n}.py', f'unique = {n}\n')
        self.commit()
        for n in range(33):
            self.git('mv', f'old-{n}.py', f'new-{n}.py')
        self.commit()
        with self.assertRaisesRegex(ContinuityError, 'pair budget'):
            self.page(max_commits=1)
        self.assertFalse(self.events.exists())
        with self.assertRaisesRegex(ContinuityError, 'time budget'):
            lineage.LineageReader(self.repo, time.monotonic()-1).inventory(self.git('rev-parse', 'HEAD^{tree}'))
        self.assertFalse(self.events.exists())
