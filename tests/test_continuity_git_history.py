from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from diffwitness.continuity_events import ContinuityError, append_project_events, continuity_paths, read_project_events
from diffwitness.continuity_state import rebuild_state
from diffwitness.continuity_transport import _parse, _serialize
from diffwitness.continuity_git_history import bootstrap_git_history


class GitHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'synthetic-private@example.test')
        self.git('config', 'user.name', 'History Fixture')
        self.commits = [self.commit(f'file-{i}.py', f'PRIVATE_MESSAGE_{i} refund intent') for i in range(3)]
        self.events = continuity_paths(self.repo).events

    def git(self, *args, input=None):
        return subprocess.check_output(['git', *args], cwd=self.repo, input=input, text=True, encoding='utf-8').strip()

    def commit(self, name, message):
        (self.repo / name).write_text('x = 1\n', encoding='utf-8')
        self.git('add', '--', name)
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def test_page_resumption_is_idempotent_and_excludes_dirty_bytes_and_private_headers(self):
        (self.repo / 'file-0.py').write_text('DIRTY_PRIVATE_CODE', encoding='utf-8')
        (self.repo / 'untracked.py').write_text('UNTRACKED_PRIVATE_CODE', encoding='utf-8')
        before = self.git('status', '--porcelain')
        page = bootstrap_git_history(self.repo, max_commits=2)
        self.assertEqual(page['tip'], self.commits[-1])
        self.assertEqual(page['next_ref'], self.commits[0])
        self.assertEqual(page['created'], 2)
        first = self.events.read_bytes()
        self.assertEqual(bootstrap_git_history(self.repo, max_commits=2)['created'], 0)
        self.assertEqual(self.events.read_bytes(), first)
        last = bootstrap_git_history(self.repo, ref=page['next_ref'], max_commits=2)
        self.assertTrue(last['complete'])
        self.assertIsNone(last['next_ref'])
        events = read_project_events(self.events)
        self.assertEqual(len(events), 3)
        self.assertEqual({e['payload']['commit'] for e in events}, set(self.commits))
        self.assertTrue(all(e['epistemic_status'] == 'OBSERVED' for e in events))
        raw = self.events.read_bytes()
        for private in (b'PRIVATE_MESSAGE', b'synthetic-private@', b'DIRTY_PRIVATE_CODE', b'UNTRACKED_PRIVATE_CODE'):
            self.assertNotIn(private, raw)
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertEqual(_parse(_serialize(events)), events)
        with contextlib.closing(sqlite3.connect(rebuild_state(self.repo, include_structure=False))) as conn:
            self.assertEqual(conn.execute('select count(*) from proofs').fetchone()[0], 0)
            self.assertEqual(conn.execute('select count(*) from entities where kind="git-commit"').fetchone()[0], 3)

    def test_messages_are_separate_declared_opt_in_and_do_not_replace_commit_authority(self):
        bootstrap_git_history(self.repo)
        result = bootstrap_git_history(self.repo, include_messages=True)
        self.assertEqual(result['created'], 3)
        events = read_project_events(self.events)
        messages = [e for e in events if e['event_type'] == 'commit.message']
        self.assertEqual(len(messages), 3)
        for event in messages:
            self.assertEqual(event['epistemic_status'], 'DECLARED')
            self.assertIn('PRIVATE_MESSAGE', event['payload']['text'])
            self.assertEqual(event['relations'][0]['epistemic_status'], 'DECLARED')
        first = self.events.read_bytes()
        self.assertEqual(bootstrap_git_history(self.repo, include_messages=True)['created'], 0)
        self.assertEqual(self.events.read_bytes(), first)

    def test_cli_rejects_bad_limit_and_imports_unicode_paths(self):
        sha = self.commit('créer facture.py', 'Unicode é')
        proc = subprocess.run([sys.executable, '-m', 'diffwitness.entry', 'state', 'bootstrap-git',
            '--repo', str(self.repo), '--max-commits', '1', '--json'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['tip'], sha)
        event = read_project_events(self.events)[0]
        self.assertEqual(event['payload']['changed_files'], ['créer facture.py'])
        with self.assertRaises(ValueError):
            bootstrap_git_history(self.repo, max_commits=0)

    def test_profile_cannot_promote_messages_or_invent_unbound_paths(self):
        bootstrap_git_history(self.repo, include_messages=True)
        events = read_project_events(self.events)
        for field in ('epistemic_status', 'relations'):
            bad = copy.deepcopy(next(e for e in events if e['event_type'] == 'commit.message'))
            bad['dedupe_key'] = None
            if field == 'epistemic_status':
                bad[field] = 'OBSERVED'
            else:
                bad[field][0]['epistemic_status'] = 'VERIFIED'
            with self.assertRaises(ContinuityError):
                append_project_events(repo=self.repo, events=[bad])
        bad = copy.deepcopy(next(e for e in events if e['event_type'] == 'commit.observed'))
        bad['payload']['changed_files'].append('invented.py')
        with self.assertRaises(ContinuityError):
            append_project_events(repo=self.repo, events=[bad])
        bad = copy.deepcopy(next(e for e in events if e['event_type'] == 'commit.observed'))
        bad['payload']['text'] = 'A declaration cannot hide in an OBSERVED commit payload'
        with self.assertRaises(ContinuityError):
            append_project_events(repo=self.repo, events=[bad])
        bad = copy.deepcopy(next(e for e in events if e['event_type'] == 'commit.message'))
        bad['payload']['text'] += 'altered'
        with self.assertRaises(ContinuityError):
            append_project_events(repo=self.repo, events=[bad])

    def test_head_advance_and_replacement_objects_cannot_relabel_captured_commit(self):
        import diffwitness.continuity_git_history as history
        original = history._commit
        advanced = False
        def advance(repo, oid, deadline):
            nonlocal advanced
            result = original(repo, oid, deadline)
            if not advanced:
                advanced = True
                self.commit('later.py', 'later')
            return result
        with patch.object(history, '_commit', side_effect=advance):
            result = bootstrap_git_history(self.repo, max_commits=1)
        self.assertEqual(result['tip'], self.commits[-1])
        self.assertEqual(read_project_events(self.events)[0]['payload']['changed_files'], ['file-2.py'])
        self.git('replace', self.commits[-1], self.git('rev-parse', 'HEAD'))
        self.assertEqual(bootstrap_git_history(self.repo, ref=self.commits[-1], max_commits=1)['created'], 0)

    def test_preappend_interruption_leaves_page_retryable(self):
        with patch('diffwitness.continuity_git_history.append_project_events', side_effect=RuntimeError('interrupt')):
            with self.assertRaises(RuntimeError):
                bootstrap_git_history(self.repo)
        self.assertFalse(self.events.exists())
        self.assertEqual(bootstrap_git_history(self.repo)['created'], 3)

    def test_root_and_merge_observe_first_parent_diff_without_importing_side_branch(self):
        branch = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'side')
        side = self.commit('side.py', 'side')
        self.git('checkout', '-q', branch)
        self.commit('main.py', 'main')
        self.git('merge', '--no-ff', '-qm', 'merge declaration', 'side')
        tip = self.git('rev-parse', 'HEAD')
        self.assertTrue(bootstrap_git_history(self.repo)['complete'])
        events = read_project_events(self.events)
        self.assertNotIn(side, {e['payload']['commit'] for e in events})
        merged = next(e for e in events if e['payload']['commit'] == tip)
        self.assertEqual(len(merged['payload']['parents']), 2)
        self.assertEqual(merged['payload']['changed_files'], ['side.py'])
        root = next(e for e in events if e['payload']['commit'] == self.commits[0])
        self.assertEqual(root['payload']['changed_files'], ['file-0.py'])

    def test_shallow_boundary_is_explicit_and_resumes_after_deepening(self):
        shallow = self.base / 'shallow'
        subprocess.run(['git', 'clone', '-q', '--depth', '2', self.repo.as_uri(), str(shallow)], check=True)
        page = bootstrap_git_history(shallow)
        self.assertFalse(page['complete'])
        self.assertEqual(page['commits'], 1)
        self.assertEqual(page['next_ref'], self.commits[1])
        self.assertIn('unavailable', page['boundary'])
        subprocess.run(['git', '-C', str(shallow), 'fetch', '-q', '--unshallow'], check=True)
        self.assertTrue(bootstrap_git_history(shallow, ref=page['next_ref'])['complete'])
        self.assertEqual(len(read_project_events(continuity_paths(shallow).events)), 3)
        self.assertEqual(bootstrap_git_history(shallow)['created'], 0)

    def test_empty_and_sha256_repositories_are_supported(self):
        repo = self.base / 'sha256'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', '--object-format=sha256', str(repo)], check=True)
        self.assertTrue(bootstrap_git_history(repo)['complete'])
        self.assertFalse(continuity_paths(repo).events.exists())
        old = self.repo
        self.repo = repo
        try:
            self.git('config', 'user.name', 'Fixture')
            self.git('config', 'user.email', 'fixture@example.test')
            sha = self.commit('root.py', 'root')
        finally:
            self.repo = old
        self.assertEqual(len(sha), 64)
        self.assertEqual(bootstrap_git_history(repo)['created'], 1)
        self.assertEqual(read_project_events(continuity_paths(repo).events)[0]['payload']['commit'], sha)

    def test_message_truncation_and_path_omission_are_explicit(self):
        for i in range(70):
            (self.repo / f'added-{i}.py').write_text('x=0\n', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-q', '-F', '-', input='é' * 5000)
        result = bootstrap_git_history(self.repo, max_commits=1, include_messages=True)
        self.assertEqual(result['files_omitted'], 6)
        events = read_project_events(self.events)
        self.assertEqual(events[0]['payload']['files_omitted'], 6)
        self.assertEqual(len(events[0]['relations']), 64)
        self.assertTrue(events[1]['payload']['truncated'])
        self.assertEqual(events[1]['payload']['text'], 'é' * 4096)
        order = self.base / 'diff-order'
        order.write_text('\n'.join(f'added-{i}.py' for i in reversed(range(70))), encoding='utf-8')
        self.git('config', 'diff.orderFile', str(order))
        self.assertEqual(bootstrap_git_history(self.repo, max_commits=1, include_messages=True)['created'], 0)

    def test_corrupt_commit_and_bounded_git_output_fail_before_append(self):
        import diffwitness.continuity_git_history as history
        original = history._git
        def altered(repo, *args, **kwargs):
            raw = original(repo, *args, **kwargs)
            return raw[:-1] + b'X' if args[:2] == ('cat-file', 'commit') else raw
        with patch.object(history, '_git', side_effect=altered):
            with self.assertRaisesRegex(ContinuityError, 'object identity'):
                bootstrap_git_history(self.repo)
        self.assertFalse(self.events.exists())
        with self.assertRaisesRegex(ContinuityError, 'output budget'):
            history._git(self.repo, 'rev-parse', 'HEAD', limit=1, deadline=time.monotonic()+10)
        with self.assertRaisesRegex(ContinuityError, 'time budget'):
            history._git(self.repo, 'rev-parse', 'HEAD', limit=128, deadline=time.monotonic()-1)

    def test_oversized_object_and_invalid_ref_cannot_partially_import_a_page(self):
        tree = self.git('rev-parse', 'HEAD^{tree}')
        large = self.git('commit-tree', tree, '-p', self.commits[-1], input='x' * (256*1024))
        with self.assertRaisesRegex(ContinuityError, '256 KiB'):
            bootstrap_git_history(self.repo, ref=large)
        with self.assertRaises(ContinuityError):
            bootstrap_git_history(self.repo, ref='--all')
        self.assertFalse(self.events.exists())

    def test_non_utf8_message_retains_only_digest_and_explicit_coverage(self):
        raw = subprocess.check_output(['git', 'cat-file', 'commit', self.commits[-1]], cwd=self.repo)
        raw = raw.partition(b'\n\n')[0] + b'\n\nINVALID_SYNTHETIC_\xff\n'
        sha = subprocess.check_output(['git', 'hash-object', '-t', 'commit', '-w', '--stdin'], cwd=self.repo,
                                      input=raw).decode('ascii').strip()
        result = bootstrap_git_history(self.repo, ref=sha, max_commits=1, include_messages=True)
        self.assertEqual(result['messages_unreadable'], 1)
        self.assertEqual(result['events'], 1)
        self.assertNotIn(b'INVALID_SYNTHETIC_', self.events.read_bytes())

    def test_blocking_child_is_terminated_at_the_command_deadline(self):
        import diffwitness.continuity_git_history as history
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            with patch.object(history.subprocess, 'Popen', return_value=child):
                with self.assertRaisesRegex(ContinuityError, 'timed out'):
                    history._git(self.repo, 'rev-parse', 'HEAD', limit=128, deadline=time.monotonic()+0.2)
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()


if __name__ == '__main__':
    unittest.main()
