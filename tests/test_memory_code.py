from __future__ import annotations

import subprocess
import unittest
import copy
import json
import sys
from unittest import mock

import test_memory_lifecycle as fixtures
from diffwitness.continuity_events import ContinuityError, append_project_events, read_project_events


class MemoryCodeTests(unittest.TestCase):
    setUp = fixtures.MemoryLifecycleTests.setUp
    declare = fixtures.MemoryLifecycleTests.declare
    cli = fixtures.MemoryLifecycleTests.cli
    def commit(self, message='edit'):
        subprocess.run(['git', 'add', 'payments'], cwd=self.repo, check=True)
        subprocess.run(['git', 'commit', '-qm', message], cwd=self.repo, check=True)

    def bind(self, identity='DEC-CODE'):
        self.declare(identity)
        return self.cli('decision', 'bind-code', identity, '--path', 'payments/refund.py',
                        '--dependency', 'payments/rules.py', '--reason', 'Review refund policy')

    def test_code_drift_revalidation_keeps_authorities_and_index(self):
        result = self.bind()
        event = result['binding']
        original = self.cli('decision', 'show', 'DEC-CODE')['assertion']
        self.assertEqual(event['epistemic_status'], 'DECLARED')
        unchanged = self.cli('decision', 'drift', 'DEC-CODE')
        self.assertEqual(unchanged['status'], 'unchanged')
        self.assertFalse(unchanged['worktree_checked'])
        (self.repo / 'payments/rules.py').write_text('MAX_REFUND = 10\n')
        self.commit()
        index = (self.repo / '.git/index').read_bytes()
        drift = self.cli('decision', 'drift', 'DEC-CODE')
        self.assertEqual(drift['status'], 'changed')
        self.assertEqual(drift['items'][1]['role'], 'dependency')
        self.assertEqual(drift['items'][1]['status'], 'changed')
        self.assertEqual(drift['binding_event_id'], event['event_id'])
        self.cli('decision', 'revalidate-code', 'DEC-CODE', '--reason', 'Reviewed the new dependency')
        self.assertEqual(self.cli('decision', 'drift', 'DEC-CODE')['status'], 'unchanged')
        shown = self.cli('decision', 'show', 'DEC-CODE')
        self.assertEqual(shown['assertion'], original)
        self.assertEqual(shown['lifecycle']['action'], 'unreviewed')
        self.assertEqual(len(shown['code_references']), 2)
        self.assertEqual((self.repo / '.git/index').read_bytes(), index)

    def test_deleted_and_explicitly_moved_reference(self):
        self.bind()
        (self.repo / 'payments/refund.py').rename(self.repo / 'payments/remboursement.py')
        self.commit()
        self.assertEqual(self.cli('decision', 'drift', 'DEC-CODE')['items'][0]['status'], 'missing')
        frozen = self.path.read_bytes()
        self.cli('decision', 'revalidate-code', 'DEC-CODE', '--reason', 'Missing path', expected=2)
        self.assertEqual(self.path.read_bytes(), frozen)
        self.cli('decision', 'revalidate-code', 'DEC-CODE', '--path', 'payments/remboursement.py',
                 '--reason', 'Explicit relocation review')
        result = self.cli('decision', 'drift', 'DEC-CODE')
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(result['items'][1]['role'], 'dependency')

    def test_deleted_role_can_be_explicitly_cleared_but_not_both_roles(self):
        self.bind()
        (self.repo / 'payments/rules.py').unlink()
        self.commit()
        frozen = self.path.read_bytes()
        self.cli('decision', 'revalidate-code', 'DEC-CODE', '--clear-dependencies',
                 '--dependency', 'payments/refund.py', '--reason', 'Conflicting selection', expected=2)
        self.cli('decision', 'revalidate-code', 'DEC-CODE', '--clear-code', '--clear-dependencies',
                 '--reason', 'No reference remains', expected=2)
        self.assertEqual(self.path.read_bytes(), frozen)
        result = self.cli('decision', 'revalidate-code', 'DEC-CODE', '--clear-dependencies',
                          '--reason', 'Dependency removed and policy reviewed')
        self.assertEqual([f['role'] for f in result['binding']['payload']['files']], ['code'])
        self.assertEqual(self.cli('decision', 'drift', 'DEC-CODE')['status'], 'unchanged')
        # Clearing code independently preserves the new explicit dependency.
        result = self.cli('decision', 'revalidate-code', 'DEC-CODE', '--clear-code',
                          '--dependency', 'payments/refund.py', '--reason', 'Dependency-only review')
        self.assertEqual([f['role'] for f in result['binding']['payload']['files']], ['dependency'])

    def test_stale_binding_and_memory_revision_fail_atomically(self):
        from diffwitness.continuity_memory_code import binding_spec
        self.bind()
        stale = binding_spec(self.repo, 'decision', 'DEC-CODE', 'revalidate-code', 'Earlier review')
        self.cli('decision', 'confirm', 'DEC-CODE', '--reason', 'New lifecycle revision')
        self.assertEqual(self.cli('decision', 'drift', 'DEC-CODE')['status'], 'stale-memory')
        frozen = self.path.read_bytes()
        with self.assertRaises(ContinuityError):
            append_project_events(repo=self.repo, events=[stale])
        self.assertEqual(self.path.read_bytes(), frozen)
        stale = binding_spec(self.repo, 'decision', 'DEC-CODE', 'revalidate-code', 'Earlier review')
        self.cli('decision', 'revalidate-code', 'DEC-CODE', '--reason', 'New binding')
        frozen = self.path.read_bytes()
        with self.assertRaises(ContinuityError):
            append_project_events(repo=self.repo, events=[stale])
        self.assertEqual(self.path.read_bytes(), frozen)

    def test_invalid_selections_and_inactive_memory_do_not_append(self):
        self.declare('DEC-CODE')
        frozen = self.path.read_bytes()
        for path in ('../outside', '/etc/passwd', 'payments/missing.py', '.git/config'):
            self.cli('decision', 'bind-code', 'DEC-CODE', '--path', path, '--reason', 'Invalid', expected=2)
        self.assertEqual(self.path.read_bytes(), frozen)
        self.cli('decision', 'retire', 'DEC-CODE', '--reason', 'Retired')
        self.cli('decision', 'bind-code', 'DEC-CODE', '--path', 'payments/refund.py', '--reason', 'Invalid', expected=2)

    def test_forged_source_reference_rejected_on_all_readers(self):
        from diffwitness.continuity_events import _event_id, _event_hash
        from diffwitness.continuity_transport import _parse, _serialize
        from diffwitness.continuity_state import rebuild_state
        self.bind()
        events = read_project_events(self.path)
        events[-1]['payload']['source_event_id'] = 'dwev_' + 'f' * 24
        events[-1]['event_id'] = _event_id(events[-1])
        events[-1]['event_hash'] = _event_hash(events[-1])
        raw = _serialize(events)
        self.path.write_bytes(raw)
        for reader in (lambda: read_project_events(self.path), lambda: _parse(raw), lambda: rebuild_state(self.repo)):
            with self.assertRaises(ContinuityError):
                reader()

    def test_forged_git_digest_cannot_be_reported_as_unchanged(self):
        from diffwitness.continuity_memory_code import binding_spec, memory_drift
        self.declare('DEC-CODE')
        spec = binding_spec(self.repo, 'decision', 'DEC-CODE', 'bind-code', 'Selected source',
                            paths=['payments/refund.py'])
        spec['payload']['files'][0]['sha256'] = 'f' * 64
        append_project_events(repo=self.repo, events=[spec])
        with self.assertRaisesRegex(ContinuityError, 'Git objects'):
            memory_drift(self.repo, 'decision', 'DEC-CODE')

    def test_schema_authority_and_subject_collision_rejected(self):
        from diffwitness.continuity_memory_code import binding_spec
        self.declare('DEC-CODE')
        spec = binding_spec(self.repo, 'decision', 'DEC-CODE', 'bind-code', 'Selected source',
                            paths=['payments/refund.py'])
        frozen = self.path.read_bytes()
        for mutate in (lambda e: e.update(epistemic_status='VERIFIED'),
                       lambda e: e['payload'].update(reason=True),
                       lambda e: e['payload']['files'][0].update(bytes=True),
                       lambda e: e['payload']['files'][0].update(extra='ignored'),
                       lambda e: e['payload']['files'].append(e['payload']['files'][0]),
                       lambda e: e['payload'].update(previous_binding_event_id='dwev_'+'a'*24),
                       lambda e: e.update(subject={'id': 'DEC-CODE', 'kind': 'decision'})):
            invalid = copy.deepcopy(spec)
            mutate(invalid)
            with self.assertRaises(ContinuityError):
                append_project_events(repo=self.repo, events=[invalid])
            self.assertEqual(self.path.read_bytes(), frozen)
        self.declare(spec['subject']['id'])
        frozen = self.path.read_bytes()
        with self.assertRaisesRegex(ContinuityError, 'collides'):
            append_project_events(repo=self.repo, events=[spec])
        self.assertEqual(self.path.read_bytes(), frozen)

    def test_types_and_budgets_fail_without_false_unchanged(self):
        from diffwitness.continuity_memory_code import memory_drift, binding_spec
        self.bind()
        frozen = self.path.read_bytes()
        with mock.patch('diffwitness.continuity_git_lineage.MAX_TREE_OBJECTS', 0):
            with self.assertRaises(ContinuityError):
                memory_drift(self.repo, 'decision', 'DEC-CODE')
        with mock.patch('diffwitness.continuity_git_lineage.MAX_BLOB_BYTES', 1):
            with self.assertRaises(ContinuityError):
                binding_spec(self.repo, 'decision', 'DEC-CODE', 'revalidate-code', 'Over limit')
        self.assertEqual(self.path.read_bytes(), frozen)
        (self.repo / 'payments/refund.py').unlink()
        (self.repo / 'payments/refund.py').mkdir()
        (self.repo / 'payments/refund.py/child').write_text('directory replacement')
        self.commit()
        self.assertEqual(memory_drift(self.repo, 'decision', 'DEC-CODE')['items'][0]['status'], 'unsupported')

    def test_missing_baseline_object_and_corrupt_bytes_fail_closed(self):
        from diffwitness.continuity_memory_code import memory_drift
        from diffwitness.continuity_git_history import _git
        bound = self.bind()['binding']['payload']
        (self.repo / 'payments/refund.py').write_text('new bytes\n')
        self.commit()
        frozen = self.path.read_bytes()
        blob = bound['files'][0]['blob']
        obj = self.repo / '.git/objects' / blob[:2] / blob[2:]
        obj.chmod(0o600)
        obj.unlink()
        with self.assertRaises(ContinuityError):
            memory_drift(self.repo, 'decision', 'DEC-CODE')
        self.assertEqual(self.path.read_bytes(), frozen)
        # A successful transport returning wrong object bytes is also rejected.
        def corrupt(repo, *args, **kwargs):
            raw = _git(repo, *args, **kwargs)
            if args[:2] == ('cat-file', 'tree'):
                return bytes([raw[0] ^ 1]) + raw[1:]
            return raw
        with mock.patch('diffwitness.continuity_git_history._git', side_effect=corrupt):
            with self.assertRaisesRegex(ContinuityError, 'identity'):
                memory_drift(self.repo, 'decision', 'DEC-CODE')

    def test_all_kinds_nonascii_and_fr_en_keep_same_citations(self):
        (self.repo / 'payments/règles.py').write_text('PRIVATE_CODE = 1\n', encoding='utf-8')
        self.commit()
        for kind in ('objective', 'decision', 'invariant', 'failed-approach'):
            identity = 'MEM-' + kind
            self.declare(identity, kind)
            self.cli(kind, 'bind-code', identity, '--path', 'payments/règles.py', '--reason', 'Revue explicite')
            results = []
            for language in ('fr', 'en'):
                args = [sys.executable, '-m', 'diffwitness.entry', '--language', language,
                        kind, 'drift', identity, '--repo', str(self.repo)]
                result = subprocess.run(args + ['--json'], capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 0, result.stderr)
                results.append(json.loads(result.stdout))
                result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('règles.py', result.stdout)
                self.assertIn(results[-1]['binding_event_id'], result.stdout)
            self.assertEqual(results[0], results[1])
        self.assertNotIn(b'PRIVATE_CODE', self.path.read_bytes())


if __name__ == '__main__':
    import unittest
    unittest.main()
