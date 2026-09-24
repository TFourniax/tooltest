from __future__ import annotations

import copy
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from test_continuity_incremental import objective
from diffwitness import continuity_events as journal
from diffwitness.continuity_lifecycle import lifecycle_spec


class AppendCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temp.name))
        self.path = journal.continuity_paths(self.repo).events

    def append(self, *specs):
        return journal.append_project_events(repo=self.repo, events=list(specs))

    def admitted(self, operation):
        seen = []
        original = journal._ProjectEventValidator.admit
        def observe(validator, event, **options):
            seen.append(event['subject']['id'])
            return original(validator, event, **options)
        with patch.object(journal._ProjectEventValidator, 'admit', observe):
            operation()
        return seen

    def test_repeated_append_validates_only_new_suffix_but_public_read_remains_complete(self):
        self.append(objective('OBJ-ONE'))
        self.assertEqual(self.admitted(lambda: self.append(objective('OBJ-TWO'))), ['OBJ-TWO'])
        self.assertEqual(self.admitted(lambda: journal.read_project_events(self.path)), ['OBJ-ONE', 'OBJ-TWO'])

    def test_same_size_timestamp_corruption_is_rejected_before_append(self):
        self.append(objective('OBJ-ONE', 'Original'))
        stamp = self.path.stat()
        damaged = self.path.read_bytes().replace(b'Original', b'Invented')
        self.path.write_bytes(damaged)
        os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertEqual(self.path.stat().st_size, stamp.st_size)
        with self.assertRaises(journal.ContinuityError):
            self.append(objective('OBJ-TWO'))
        self.assertEqual(self.path.read_bytes(), damaged)

    def test_external_suffix_is_validated_and_invalid_suffix_fails_closed(self):
        first = self.append(objective('OBJ-ONE'))[0][0]
        event = journal._candidate_from_spec(objective('OBJ-EXTERNAL'))
        event['prev_hash'] = first['event_hash']
        event['event_id'] = journal._event_id(event)
        event['event_hash'] = journal._event_hash(event)
        with self.path.open('ab') as handle:
            handle.write((journal._canonical(event) + '\n').encode())
        self.assertEqual(self.admitted(lambda: self.append(objective('OBJ-TWO'))), ['OBJ-EXTERNAL', 'OBJ-TWO'])
        with self.path.open('ab') as handle:
            handle.write(b'{"schema_version":"broken"}\n')
        before = self.path.read_bytes()
        with self.assertRaises(journal.ContinuityError):
            self.append(objective('OBJ-THREE'))
        self.assertEqual(before, self.path.read_bytes())

    def test_caller_inputs_and_results_cannot_mutate_cached_history(self):
        spec = objective('OBJ-ONE')
        spec['payload']['nested'] = {'list': ['original']}
        clean = copy.deepcopy(spec)
        event = self.append(spec)[0][0]
        spec['payload']['nested']['list'].append('input mutation')
        event['payload']['nested']['list'].append('result mutation')
        same, created = self.append(clean)[0]
        self.assertFalse(created)
        self.assertEqual(same['payload'], clean['payload'])
        same['subject']['kind'] = 'change'
        self.assertEqual(self.append(clean)[0][0]['subject']['kind'], 'objective')
        self.append(lifecycle_spec(self.repo, 'objective', 'OBJ-ONE', 'confirm', 'Still applies'))
        self.assertEqual(len(journal.read_project_events(self.path)), 2)

    def test_failed_batch_cannot_advance_cached_lifecycle_or_dedupe(self):
        self.append(objective('OBJ-ONE'))
        confirm = lifecycle_spec(self.repo, 'objective', 'OBJ-ONE', 'confirm', 'Review')
        stale = lifecycle_spec(self.repo, 'objective', 'OBJ-ONE', 'retire', 'Stale')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(journal.ContinuityError, 'revision'):
            self.append(objective('OBJ-TWO'), confirm, stale)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.append(objective('OBJ-TWO'), confirm)[0][1])
        self.assertEqual(len(journal.read_project_events(self.path)), 3)

    def test_partial_write_never_publishes_checkpoint(self):
        self.append(objective('OBJ-ONE'))
        before = self.path.read_bytes()
        def partial(paths, events):
            with paths.events.open('ab') as handle:
                handle.write(b'{"partial":')
            raise OSError('interrupted write')
        with patch.object(journal, '_durable_append', partial), self.assertRaises(OSError):
            self.append(objective('OBJ-TWO'))
        with self.assertRaises(journal.ContinuityError):
            self.append(objective('OBJ-THREE'))
        self.path.write_bytes(before)
        self.assertTrue(self.append(objective('OBJ-TWO'))[0][1])

    def test_valid_rewrite_truncation_and_crlf_unicode_keep_chain_truth(self):
        self.append(objective('OBJ-ONE', 'Remboursement \u2028\u2029 café'))
        prefix = self.path.read_bytes()
        self.append(objective('OBJ-TWO'))
        for ending in (b'\r', b'\r\n', b'\n'):
            with self.subTest(ending=ending):
                self.path.write_bytes(prefix.replace(b'\n', ending))
                self.append(objective('OBJ-OTHER'))
                self.assertEqual([e['subject']['id'] for e in journal.read_project_events(self.path)], ['OBJ-ONE', 'OBJ-OTHER'])

    def test_concurrent_calls_have_one_chain_and_dedupe(self):
        self.append(objective('OBJ-ONE'))
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda index: self.append(objective(f'OBJ-{index % 4}')), range(12)))
        self.assertEqual(sum(result[0][1] for result in results), 4)
        self.assertEqual(len(journal.read_project_events(self.path)), 5)

    def test_bounds_and_repository_eviction_force_complete_validation(self):
        self.append(objective('OBJ-ONE'))
        for setting in ('_APPEND_CACHE_MAX_BYTES', '_APPEND_CACHE_MAX_EVENTS'):
            with self.subTest(setting=setting), patch.object(journal, setting, 0):
                self.append(objective('OBJ-ONE'))  # Consume and decline to republish.
                self.assertEqual(self.admitted(lambda: self.append(objective('OBJ-ONE'))), ['OBJ-ONE'])
        self.append(objective('OBJ-ONE'))
        with tempfile.TemporaryDirectory() as td:
            other = fixtures.ContinuityKernelTests().repo(Path(td))
            journal.append_project_events(repo=other, events=[objective('OBJ-OTHER')])
            self.assertEqual(self.admitted(lambda: self.append(objective('OBJ-ONE'))), ['OBJ-ONE'])

    def test_unterminated_valid_record_gets_separator_without_changing_old_bytes(self):
        self.append(objective('OBJ-ONE'))
        prefix = self.path.read_bytes().rstrip(b'\r\n')
        self.path.write_bytes(prefix)
        self.append(objective('OBJ-TWO'))
        self.assertTrue(self.path.read_bytes().startswith(prefix + os.linesep.encode('ascii')))
        self.assertEqual(len(journal.read_project_events(self.path)), 2)

    def test_failed_task_reference_cannot_replace_cached_task_identity(self):
        from diffwitness.continuity_tasks import _spec
        payload = dict(origin='explicit-declaration', anchor_sha256=None, anchor_chars=None,
                       session_sha256=None, ordinal=None, why='Work')
        original = _spec('task.recorded', 'TASK-ONE', payload, label='Task', dedupe='task:TASK-ONE')
        task = self.append(original)[0][0]
        invalid = _spec('task.described', 'TASK-ONE', {**payload, 'source_task_event_id': 'dwev_' + '0' * 24}, label='Updated')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(journal.ContinuityError, 'reference'):
            self.append(objective('OBJ-ONE'), invalid)
        self.assertEqual(self.path.read_bytes(), before)
        invalid['payload']['source_task_event_id'] = task['event_id']
        self.append(invalid)
        self.assertEqual(len(journal.read_project_events(self.path)), 2)

    def test_hash_valid_invalid_profile_and_duplicate_json_external_suffix_fail_closed(self):
        first = self.append(objective('OBJ-ONE'))[0][0]
        before = self.path.read_bytes()
        event = journal._candidate_from_spec(objective('OBJ-TWO'))
        event['provenance']['diffwitness_profile'] = 'project-memory-declaration-1'
        event['payload']['why'] = []
        event['prev_hash'] = first['event_hash']
        event['event_id'] = journal._event_id(event)
        event['event_hash'] = journal._event_hash(event)
        for suffix in ((journal._canonical(event) + '\n').encode(), b'{"event_type":1,"event_type":2}\n'):
            self.path.write_bytes(before)
            self.append(objective('OBJ-ONE'))
            self.path.write_bytes(before + suffix)
            with self.assertRaises(journal.ContinuityError):
                self.append(objective('OBJ-THREE'))

    def test_crt_text_translation_cannot_make_cached_bytes_differ_from_disk(self):
        # Reproduce Windows CRT O_TEXT on every OS; actual Windows CI also runs
        # the ordinary append-count tests without this simulation.
        binary_flag = getattr(os, 'O_BINARY', 0x8000)
        original_open, original_write = os.open, os.write
        modes = {}
        def crt_open(path, flags, *args):
            fd = original_open(path, flags if os.name == 'nt' else flags & ~binary_flag, *args)
            modes[fd] = bool(flags & binary_flag)
            return fd
        def crt_write(fd, raw):
            if os.name != 'nt' and not modes.get(fd):
                original_write(fd, raw.replace(b'\n', b'\r\n'))
                return len(raw)
            return original_write(fd, raw)
        with patch.object(os, 'O_BINARY', binary_flag, create=True), \
             patch.object(os, 'open', crt_open), patch.object(os, 'write', crt_write), \
             patch.object(journal, '_record_separator', return_value=b'\r\n', create=True):
            self.append(objective('OBJ-ONE'))
            self.assertEqual(self.admitted(lambda: self.append(objective('OBJ-TWO'))), ['OBJ-TWO'])
        raw = self.path.read_bytes()
        self.assertEqual(raw.count(b'\r\n'), 2)
        self.assertNotIn(b'\r\r\n', raw)
        self.assertEqual(len(journal.read_project_events(self.path)), 2)


if __name__ == '__main__':
    unittest.main()
