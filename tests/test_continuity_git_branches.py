from __future__ import annotations

import concurrent.futures
import base64
import hashlib
import json
import os
import sys
import contextlib
import sqlite3
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_git_history as fixtures
from diffwitness.continuity_events import ContinuityError, continuity_paths, read_project_events
from diffwitness.continuity_git_history import bootstrap_git_history
from diffwitness.continuity_state import rebuild_state


class GitBranchHistoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GitHistoryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repo = self.fixture.repo
        self.git = self.fixture.git
        self.main = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'side')
        self.side = self.fixture.commit('side.py', 'generated side')
        self.git('checkout', '-q', self.main)
        self.fixture.commit('main.py', 'generated main')
        self.git('merge', '--no-ff', '-qm', 'generated merge', 'side')
        self.tip = self.git('rev-parse', 'HEAD')
        self.git('checkout', '--orphan', 'unrelated')
        self.git('rm', '-rf', '.')
        self.other = self.fixture.commit('other.py', 'generated other root')
        self.git('checkout', '-q', self.main)
        self.expected = set(self.git('rev-list', '--branches').splitlines())
        self.events = continuity_paths(self.repo).events

    def page(self, **options):
        return bootstrap_git_history(self.repo, all_branches=True, **options)

    def finish(self, page):
        for _ in range(20):
            if page['complete']:
                return page
            self.assertIsInstance(page['next_cursor'], str)
            self.assertLessEqual(len(page['next_cursor']), 65536)
            page = self.page(max_commits=2, cursor=page['next_cursor'])
        self.fail('bounded fixture did not finish')

    def test_all_branches_include_merge_parents_and_disconnected_roots_without_proof(self):
        before = self.git('status', '--porcelain'), self.git('write-tree')
        page = self.page(max_commits=100)
        self.assertEqual(page['scope'], 'all-branches')
        self.assertTrue(page['complete'])
        self.assertIsNone(page['next_cursor'])
        events = read_project_events(self.events)
        self.assertEqual({e['payload']['commit'] for e in events}, self.expected)
        self.assertTrue(all(e['event_type'] == 'commit.observed' for e in events))
        merged = next(e for e in events if e['payload']['commit'] == self.tip)
        self.assertEqual(merged['payload']['changed_files'], ['side.py'])
        self.assertEqual(before, (self.git('status', '--porcelain'), self.git('write-tree')))
        with contextlib.closing(sqlite3.connect(rebuild_state(self.repo, include_structure=False))) as conn:
            self.assertEqual(conn.execute('select count(*) from proofs').fetchone()[0], 0)

    def test_small_pages_retry_idempotently_and_keep_the_captured_tips_after_ref_movement(self):
        first = self.page(max_commits=2)
        raw = self.events.read_bytes()
        self.assertEqual(self.page(max_commits=2)['created'], 0)
        self.assertEqual(self.events.read_bytes(), raw)
        later = self.fixture.commit('later.py', 'generated after capture')
        self.finish(first)
        self.assertEqual({e['payload']['commit'] for e in read_project_events(self.events)}, self.expected)
        self.assertEqual(self.page(max_commits=100)['created'], 1)
        self.assertIn(later, {e['payload']['commit'] for e in read_project_events(self.events)})

    def test_declared_messages_remain_opt_in_and_cannot_change_cursor_policy(self):
        first = self.page(max_commits=2, include_messages=True)
        raw = self.events.read_bytes()
        with self.assertRaises((ContinuityError, ValueError)):
            self.page(cursor=first['next_cursor'], include_messages=False)
        self.assertEqual(self.events.read_bytes(), raw)
        events = read_project_events(self.events)
        self.assertEqual(len(events), 4)
        self.assertTrue(all(e['epistemic_status'] == 'DECLARED' for e in events if e['event_type'] == 'commit.message'))

    def test_invalid_options_and_corrupted_cursor_fail_without_appending(self):
        for options in ({'all_branches': 1}, {'cursor': {}}, {'cursor': True}, {'cursor': 'x' * 65537},
                        {'cursor': 'not-a-cursor'}, {'ref': 'side'}):
            with self.subTest(options=str(options)[:80]), self.assertRaises((ValueError, ContinuityError)):
                bootstrap_git_history(self.repo, **{'all_branches': True, **options})
        self.assertFalse(self.events.exists())
        first = self.page(max_commits=1)
        raw = self.events.read_bytes()
        cursor = first['next_cursor']
        with self.assertRaises((ValueError, ContinuityError)):
            self.page(cursor=cursor[:-2] + '!!')
        with self.assertRaises((ValueError, ContinuityError)):
            bootstrap_git_history(self.repo, cursor=cursor)
        self.assertEqual(self.events.read_bytes(), raw)

    def test_interruption_and_concurrent_page_imports_retain_journal_integrity(self):
        with patch('diffwitness.continuity_git_history.append_project_events', side_effect=RuntimeError('interrupt')):
            with self.assertRaises(RuntimeError):
                self.page(max_commits=2)
        self.assertFalse(self.events.exists())
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.page(max_commits=2), range(2)))
        self.assertEqual(sum(r['created'] for r in results), 2)
        self.assertEqual(len(read_project_events(self.events)), 2)

    def test_shallow_and_grafted_parent_lists_never_claim_complete_history(self):
        shallow = self.fixture.base / 'shallow-branches'
        subprocess.run(['git', 'clone', '-q', '--depth', '2', self.repo.as_uri(), str(shallow)], check=True)
        result = bootstrap_git_history(shallow, all_branches=True)
        self.assertFalse(result['complete'])
        self.assertTrue(result['boundary'])
        subprocess.run(['git', '-C', str(shallow), 'fetch', '-q', '--unshallow'], check=True)
        try:
            resumed = bootstrap_git_history(shallow, all_branches=True, cursor=result['next_cursor'])
        except ContinuityError:
            resumed = bootstrap_git_history(shallow, all_branches=True)
        self.assertTrue(resumed['complete'])
        graft = self.repo / '.git/info/grafts'
        graft.write_text(self.tip + '\n')
        result = self.page(max_commits=100)
        self.assertFalse(result['complete'])
        self.assertTrue(result['boundary'])

    def test_missing_non_first_parent_and_excessive_branch_capture_fail_before_append(self):
        obj = self.repo / '.git/objects' / self.side[:2] / self.side[2:]
        raw = obj.read_bytes()
        # Git marks loose objects read-only on Windows. This fixture owns the
        # disposable object and must make it removable before simulating loss.
        obj.chmod(0o600)
        obj.unlink()
        with self.assertRaises(ContinuityError):
            self.page()
        self.assertFalse(self.events.exists())
        obj.write_bytes(raw)
        self.git('update-ref', '--stdin', input=''.join(f'update refs/heads/generated-{n} {self.tip}\n' for n in range(257)))
        with self.assertRaises(ContinuityError):
            self.page()
        self.assertFalse(self.events.exists())

    def forge_cursor(self, value):
        value = {key:item for key,item in value.items() if key != 'checksum'}
        canonical = lambda data: json.dumps(data, sort_keys=True, separators=(',', ':')).encode('ascii')
        value['checksum'] = hashlib.sha256(canonical(value)).hexdigest()
        return base64.urlsafe_b64encode(canonical(value)).decode('ascii')

    def test_consistent_cursor_cannot_skip_unimported_commits(self):
        first = self.page(max_commits=1)
        cursor = json.loads(base64.urlsafe_b64decode(first['next_cursor']))
        raw = subprocess.check_output(['git', '--no-replace-objects', 'rev-list', '--topo-order',
                                       '--parents', '--max-count=2', *cursor['tips'], '--'], cwd=self.repo)
        cursor.update(offset=2, prefix_sha256=hashlib.sha256(raw).hexdigest())
        before = self.events.read_bytes()
        with self.assertRaises(ContinuityError):
            self.page(cursor=self.forge_cursor(cursor))
        self.assertEqual(self.events.read_bytes(), before)

    def test_consistent_cursor_cannot_claim_unimported_messages(self):
        first = self.page(max_commits=1)
        cursor = json.loads(base64.urlsafe_b64decode(first['next_cursor']))
        cursor['include_messages'] = True
        before = self.events.read_bytes()
        with self.assertRaises(ContinuityError):
            self.page(cursor=self.forge_cursor(cursor), include_messages=True)
        self.assertEqual(self.events.read_bytes(), before)

    def test_cursor_prefix_rechecks_corrupt_journal_bytes_with_preserved_size_and_time(self):
        first = self.page(max_commits=1)
        before = self.events.read_bytes()
        stamp = self.events.stat()
        corrupt = before.replace(b'OBSERVED', b'INFERRED', 1)
        self.assertNotEqual(corrupt, before)
        self.assertEqual(len(corrupt), len(before))
        self.events.write_bytes(corrupt)
        os.utime(self.events, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        with self.assertRaises(ContinuityError):
            self.page(cursor=first['next_cursor'])
        self.assertEqual(self.events.read_bytes(), corrupt)

    def test_cursor_rejects_invalid_typed_fields_even_with_recomputed_checksum(self):
        first = self.page(max_commits=1)
        cursor = json.loads(base64.urlsafe_b64decode(first['next_cursor']))
        before = self.events.read_bytes()
        for change in ({'offset': True}, {'offset': -1}, {'offset': float('inf')},
                       {'tips': []}, {'tips': [cursor['tips'][0]] * 2}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises((ValueError, ContinuityError)):
                self.page(cursor=self.forge_cursor({**cursor, **change}))
        raw = base64.urlsafe_b64decode(first['next_cursor']).replace(b'"offset":1', b'"offset":1,"offset":1')
        with self.assertRaises(ContinuityError):
            self.page(cursor=base64.urlsafe_b64encode(raw).decode())
        self.assertEqual(self.events.read_bytes(), before)

    def test_remote_tracking_tips_are_included_but_tag_only_history_is_explicitly_outside_scope(self):
        self.git('checkout', '-qb', 'temporary')
        remote = self.fixture.commit('remote.py', 'generated remote-tracking tip')
        self.git('update-ref', 'refs/remotes/origin/generated', remote)
        tag_only = self.fixture.commit('tag-only.py', 'generated tag-only commit')
        self.git('tag', 'generated-tag', tag_only)
        self.git('checkout', '-q', self.main)
        self.git('branch', '-D', 'temporary')
        self.assertTrue(self.page(max_commits=100)['complete'])
        seen = {e['payload']['commit'] for e in read_project_events(self.events)}
        self.assertEqual(seen, self.expected | {remote})
        self.assertNotIn(tag_only, seen)

    def test_empty_sha256_and_localized_cli_preserve_compatible_modes(self):
        repo = self.fixture.base / 'sha256-branches'
        subprocess.run(['git', 'init', '-q', '--object-format=sha256', str(repo)], check=True)
        self.assertTrue(bootstrap_git_history(repo, all_branches=True)['complete'])
        self.assertFalse(continuity_paths(repo).events.exists())
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=repo).decode().strip()
        git('config', 'user.name', 'Generated fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        (repo / 'créer.py').write_text('VALUE=1\n')
        git('add', '.')
        git('commit', '-qm', 'generated unicode')
        tip = git('rev-parse', 'HEAD')
        self.assertEqual(len(tip), 64)
        for language in ('en', 'fr'):
            result = subprocess.run([sys.executable, '-m', 'diffwitness.entry', '--language', language,
                                     'state', 'bootstrap-git', '--repo', str(repo), '--all-branches', '--json'],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            page = json.loads(result.stdout)
            self.assertEqual(page['tips'], [tip])
            self.assertTrue(page['complete'])
        self.assertEqual(len(read_project_events(continuity_paths(repo).events)), 1)

    def test_cli_resumption_hint_keeps_explicit_message_policy(self):
        result = subprocess.run([sys.executable, '-m', 'diffwitness.entry', 'state', 'bootstrap-git',
                                 '--repo', str(self.repo), '--all-branches', '--include-messages', '--max-commits', '1'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--all-branches --include-messages --cursor ', result.stdout)


if __name__ == '__main__':
    unittest.main()
