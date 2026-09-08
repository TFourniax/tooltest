from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.engine_protocol import EngineProtocolError, change_id, repository_fingerprint
from diffwitness.continuity_bridge import _validate_envelope
from diffwitness.continuity_events import ContinuityError
from diffwitness.gitops import GitError, empty_analysis_base, git, head_commit, resolve_analysis_base, resolve_ref, snapshot_worktree
from diffwitness.idleproof_sidecar import IdleProofSidecarError, build_portal_snapshot, portal_sync
from diffwitness.ide_plugin import session_start, session_stop
from diffwitness.setup import setup_install, setup_status
from diffwitness.status_cli import build_project_status, render_project_status


class UnbornRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q')

    def test_empty_base_is_deterministic_unreachable_and_not_an_ordinary_ref(self):
        head_file = (self.repo / '.git/HEAD').read_bytes()
        base = empty_analysis_base(self.repo)
        with mock.patch.dict(os.environ, {'GIT_AUTHOR_NAME': 'Different User', 'GIT_AUTHOR_DATE': '2026-01-01T00:00:00Z'}):
            self.assertEqual(empty_analysis_base(self.repo), base)
        self.assertEqual(git(self.repo, 'ls-tree', '-r', base), '')
        self.assertEqual(git(self.repo, 'rev-list', '--parents', '-n', '1', base).strip(), base)
        self.assertEqual(snapshot_worktree(self.repo), base)
        self.assertEqual(resolve_analysis_base(self.repo, 'HEAD'), base)
        self.assertIsNone(head_commit(self.repo))
        self.assertEqual((self.repo / '.git/HEAD').read_bytes(), head_file)
        self.assertEqual(git(self.repo, 'for-each-ref'), '')
        with self.assertRaises(GitError):
            resolve_ref(self.repo, 'HEAD')
        with self.assertRaises(GitError):
            resolve_analysis_base(self.repo, 'HEAD~1')

    def test_initial_snapshot_preserves_staging_and_excludes_only_owned_transients(self):
        (self.repo / 'app.py').write_text('VALUE = 1\n')
        git(self.repo, 'add', 'app.py')
        index = (self.repo / '.git/index').read_bytes()
        (self.repo / 'app.py').write_text('VALUE = 2\n')
        (self.repo / 'untracked.py').write_text('NEW = True\n')
        (self.repo / '.codex').mkdir()
        (self.repo / '.codex/hooks.json').write_text('{}')
        snapshot = snapshot_worktree(self.repo)
        self.assertEqual(git(self.repo, 'show', snapshot + ':app.py'), 'VALUE = 2\n')
        files = git(self.repo, 'ls-tree', '-r', '--name-only', snapshot).splitlines()
        self.assertEqual(files, ['app.py', 'untracked.py'])
        self.assertEqual((self.repo / '.git/index').read_bytes(), index)
        self.assertIsNone(head_commit(self.repo))
        excluded = snapshot_worktree(self.repo, exclude_paths=['untracked.py'])
        self.assertEqual(git(self.repo, 'ls-tree', '-r', '--name-only', excluded).splitlines(), ['app.py'])

    def test_corrupt_head_is_never_silently_replaced_by_empty_base(self):
        (self.repo / '.git/HEAD').write_text('1' * 40 + '\n')
        with self.assertRaisesRegex(GitError, 'not a valid unborn'):
            head_commit(self.repo)
        with self.assertRaises(GitError):
            snapshot_worktree(self.repo)
        self.assertEqual((self.repo / '.git/HEAD').read_text(), '1' * 40 + '\n')

    def test_provisional_identity_is_distinct_durable_and_becomes_normal_root_lineage(self):
        before = repository_fingerprint(self.repo)
        other = self.root / 'other'; other.mkdir(); git(other, 'init', '-q')
        self.assertNotEqual(repository_fingerprint(other), before)
        moved = self.root / 'moved'; self.repo.rename(moved); self.repo = moved
        self.assertEqual(repository_fingerprint(self.repo), before)
        identity = (self.repo / '.git/diffwitness/unborn-identity').read_bytes()
        git(self.repo, 'config', 'user.name', 'First User Commit')
        git(self.repo, 'config', 'user.email', 'first@example.invalid')
        git(self.repo, 'commit', '--allow-empty', '-qm', 'first real user commit')
        head = resolve_ref(self.repo, 'HEAD')
        expected = 'dwrepo_' + hashlib.sha256(head.encode()).hexdigest()[:24]
        self.assertEqual(repository_fingerprint(self.repo), expected)
        self.assertNotEqual(expected, before)
        self.assertEqual((self.repo / '.git/diffwitness/unborn-identity').read_bytes(), identity)
        self.assertEqual(resolve_analysis_base(self.repo, 'HEAD'), head)

    def test_concurrent_first_identity_callers_agree(self):
        code = 'from pathlib import Path; from diffwitness.engine_protocol import repository_fingerprint; import sys; print(repository_fingerprint(Path(sys.argv[1])))'
        processes = [subprocess.Popen([sys.executable, '-c', code, str(self.repo)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
        values = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr)
            values.append(stdout.strip())
        self.assertEqual(len(set(values)), 1)
        self.assertEqual(values[0], repository_fingerprint(self.repo))

    def test_corrupt_local_identity_is_preserved_and_rejected(self):
        repository_fingerprint(self.repo)
        path = self.repo / '.git/diffwitness/unborn-identity'
        path.write_text('corrupt')
        with self.assertRaises(EngineProtocolError):
            repository_fingerprint(self.repo)
        self.assertEqual(path.read_text(), 'corrupt')

    def test_setup_and_status_are_useful_without_commits_or_evidence(self):
        installed = setup_install(cwd=self.repo, agent='codex')
        self.assertTrue(installed['healthy'])
        self.assertFalse(installed['productReady'])
        status = setup_status(cwd=self.repo)
        value = build_project_status(self.repo)
        self.assertEqual(value['readiness'], status['readiness'])
        self.assertEqual(value['readiness']['repository']['state'], 'unborn')
        self.assertEqual(value['readiness']['repository']['identityScope'], 'local-provisional')
        self.assertFalse(value['readiness']['currentProof']['currentTreeVerified'])
        self.assertIn('unborn', render_project_status(value, view='technical'))
        self.assertIn('pas encore de commit', render_project_status(value, view='guided'))
        self.assertIsNone(head_commit(self.repo))
        self.assertEqual(git(self.repo, 'for-each-ref'), '')

    def test_portal_cannot_send_provisional_identity(self):
        with mock.patch('diffwitness.idleproof_sidecar._post_snapshot', side_effect=AssertionError('unexpected network')):
            with self.assertRaisesRegex(IdleProofSidecarError, 'first Git commit'):
                portal_sync(self.repo)

    def test_empty_native_session_does_not_manufacture_proof(self):
        payload = {'cwd': str(self.repo), 'session_id': 'empty', 'provider': 'codex'}
        session_start(payload)
        result = session_stop(payload)
        self.assertNotIn('decision', result)
        self.assertIn('no repository change', result['systemMessage'])
        status = build_project_status(self.repo)
        self.assertFalse(status['readiness']['currentProof']['currentTreeVerified'])
        self.assertIsNone(head_commit(self.repo))
        self.assertEqual(git(self.repo, 'for-each-ref'), '')

    def test_old_provisional_envelope_cannot_be_reingested_as_new_lineage(self):
        fingerprint = repository_fingerprint(self.repo)
        tree = git(self.repo, 'rev-parse', empty_analysis_base(self.repo) + '^{tree}').strip()
        envelope = {'schema_version': 'change-envelope-1',
                    'repository': {'fingerprint': fingerprint},
                    'base': {'tree': tree}, 'candidate': {'tree': tree},
                    'change_id': change_id(repository=fingerprint, base_tree=tree, candidate_tree=tree)}
        original = json.dumps(envelope, sort_keys=True)
        _validate_envelope(self.repo, envelope)
        path = self.repo / '.git/diffwitness/change-envelope.json'
        path.write_text(original, encoding='utf-8')
        git(self.repo, 'config', 'user.name', 'First Commit')
        git(self.repo, 'config', 'user.email', 'first@example.invalid')
        git(self.repo, 'commit', '--allow-empty', '-qm', 'first user commit')
        with self.assertRaisesRegex(ContinuityError, 'fingerprint does not match'):
            _validate_envelope(self.repo, envelope)
        with self.assertRaisesRegex(IdleProofSidecarError, 'Historical evidence'):
            build_portal_snapshot(self.repo)
        self.assertEqual(path.read_text(encoding='utf-8'), original)
        self.assertEqual(json.dumps(envelope, sort_keys=True), original)


if __name__ == '__main__':
    unittest.main()
