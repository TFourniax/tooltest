from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness import continuity_events as journal, continuity_state as state
from diffwitness.continuity_context import compile_context
from diffwitness.continuity_lifecycle import lifecycle_spec


def objective(identity, label=None):
    return dict(event_type='objective.declared', subject=dict(id=identity, kind='objective', label=label or identity),
                epistemic_status='DECLARED', payload={'why': 'refund safety'}, dedupe_key='objective:' + identity)


def rows(path):
    with contextlib.closing(sqlite3.connect(path)) as conn:
        tables = [x[0] for x in conn.execute("select name from sqlite_master where type='table' order by name")]
        return {table: sorted(conn.execute('select * from "' + table + '"').fetchall(), key=repr) for table in tables}


class IncrementalStateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temp.name))
        self.paths = journal.continuity_paths(self.repo)

    def append(self, *specs):
        return journal.append_project_events(repo=self.repo, events=list(specs))

    def test_append_checks_old_event_shape_once_and_batch_references_still_reject_atomically(self):
        self.append(objective('OBJ-ONE'))
        validate = journal._validate_event_shape
        seen = []
        def observe(event, **kwargs):
            if event.get('event_id'):
                seen.append(event['event_id'])
            return validate(event, **kwargs)
        with patch.object(journal, '_validate_event_shape', side_effect=observe):
            self.append(objective('OBJ-TWO'))
        self.assertEqual(len(seen), len(set(seen)), 'append must not revalidate the already validated prefix')
        original = self.paths.events.read_bytes()
        stale = lifecycle_spec(self.repo, 'objective', 'OBJ-ONE', 'retire', 'Obsolete')
        self.append(lifecycle_spec(self.repo, 'objective', 'OBJ-ONE', 'confirm', 'Reviewed'))
        before = self.paths.events.read_bytes()
        with self.assertRaisesRegex(journal.ContinuityError, 'revision'):
            self.append(objective('OBJ-THREE'), stale)
        self.assertEqual(self.paths.events.read_bytes(), before)
        self.assertTrue(before.startswith(original))

    def test_append_projects_only_suffix_with_one_validated_snapshot(self):
        self.append(objective('OBJ-ONE'))
        state.rebuild_state(self.repo)
        self.append(objective('OBJ-TWO'))
        projected = []
        project = state._upsert_entity
        def observe(conn, event):
            projected.append(event['subject']['id'])
            return project(conn, event)
        with patch.object(state, '_upsert_entity', side_effect=observe), \
             patch.object(state, 'read_project_event_snapshot', wraps=state.read_project_event_snapshot) as reads:
            path = state.ensure_state(self.repo)
        self.assertEqual(projected, ['OBJ-TWO'])
        self.assertEqual(reads.call_count, 1)
        incremental = rows(path)
        self.assertEqual(incremental, rows(state.rebuild_state(self.repo)))

    def test_suffix_failure_rolls_back_rows_head_digest_and_retry_converges(self):
        self.append(objective('OBJ-ONE'))
        path = state.rebuild_state(self.repo)
        before = path.read_bytes()
        self.append(objective('OBJ-TWO'), objective('OBJ-THREE'))
        project = state._upsert_entity
        def fail(conn, event):
            project(conn, event)
            if event['subject']['id'] == 'OBJ-THREE':
                raise RuntimeError('injected projection interruption')
        with patch.object(state, '_upsert_entity', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                state.ensure_state(self.repo)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.paths.root.glob('state-*.db')), [])
        self.assertEqual(rows(state.ensure_state(self.repo)), rows(state.rebuild_state(self.repo)))

    def test_same_size_same_mtime_prefix_corruption_is_rejected_and_preserves_state(self):
        self.append(objective('OBJ-ONE', 'Refunds A'))
        path = state.rebuild_state(self.repo)
        before = path.read_bytes()
        self.append(objective('OBJ-TWO'))
        stat = self.paths.events.stat()
        raw = self.paths.events.read_bytes()
        self.paths.events.write_bytes(raw.replace(b'Refunds A', b'Forged! A'))
        os.utime(self.paths.events, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(self.paths.events.stat().st_size, stat.st_size)
        for operation in (lambda: state.ensure_state(self.repo), lambda: self.append(objective('OBJ-THREE'))):
            with self.assertRaises(journal.ContinuityError):
                operation()
        self.assertEqual(path.read_bytes(), before)

    def test_truncation_divergence_missing_anchor_and_event_row_damage_reconstruct(self):
        self.append(objective('OBJ-ONE'), objective('OBJ-TWO'))
        original = self.paths.events.read_bytes()
        for case in ('truncated', 'diverged', 'missing-anchor', 'old-schema', 'missing-event', 'wrong-hash', 'not-a-database', 'deleted'):
            with self.subTest(case=case):
                self.paths.events.write_bytes(original)
                path = state.rebuild_state(self.repo)
                if case in ('truncated', 'diverged'):
                    self.paths.events.write_bytes(original.splitlines(keepends=True)[0])
                    if case == 'diverged':
                        self.append(objective('OBJ-OTHER'))
                elif case == 'not-a-database':
                    path.write_bytes(b'not a SQLite database')
                elif case == 'deleted':
                    path.unlink()
                else:
                    with contextlib.closing(sqlite3.connect(path)) as conn:
                        if case == 'missing-anchor':
                            conn.execute('delete from meta where key=?', (state.VALIDATED_EVENT_DIGEST_META,))
                        elif case == 'old-schema':
                            conn.execute("update meta set value='continuity-state-2' where key='schema'")
                        elif case == 'missing-event':
                            conn.execute('delete from events where sequence=1')
                        else:
                            conn.execute("update events set event_hash='broken' where sequence=1")
                        conn.commit()
                self.append(objective('OBJ-NEW'))
                actual = rows(state.ensure_state(self.repo))
                self.assertEqual(actual, rows(state.rebuild_state(self.repo)))

    def test_append_and_corruption_after_snapshot_never_stamp_unvalidated_bytes(self):
        for corruption in (False, True):
            with self.subTest(corruption=corruption):
                self.paths.events.unlink(missing_ok=True)
                self.append(objective('OBJ-ONE', 'Refunds A'))
                state.rebuild_state(self.repo)
                self.append(objective('OBJ-TWO'))
                raw = self.paths.events.read_bytes()
                read = state.read_project_event_snapshot
                def interleave(path):
                    result = read(path)
                    if corruption:
                        path.write_bytes(raw.replace(b'Refunds A', b'Forged! A'))
                    else:
                        self.append(objective('OBJ-THREE'))
                    return result
                with patch.object(state, 'read_project_event_snapshot', side_effect=interleave) as reads:
                    path = state.ensure_state(self.repo)
                self.assertEqual(reads.call_count, 1)
                self.assertEqual(state._meta(path)[state.VALIDATED_EVENT_DIGEST_META], hashlib.sha256(raw).hexdigest())
                if corruption:
                    with self.assertRaises(journal.ContinuityError):
                        compile_context(self.repo, 'refund', refresh_structure=False)
                else:
                    context = compile_context(self.repo, 'refund', refresh_structure=False)
                    self.assertIn('OBJ-THREE', {x['id'] for x in context['objectives']})

    def test_materializers_and_explicit_rebuild_serialize_before_reading_journal(self):
        for rebuild in (False, True):
            with self.subTest(rebuild=rebuild):
                self.paths.events.unlink(missing_ok=True)
                self.append(objective('OBJ-ONE'))
                state.rebuild_state(self.repo)
                self.append(objective('OBJ-TWO'))
                first_read, release, second_attempt, second_read = (threading.Event() for _ in range(4))
                original_read, original_lock = state.read_project_event_snapshot, state._event_lock
                names = threading.local()
                def read(path):
                    value = original_read(path)
                    if names.role == 'first':
                        first_read.set()
                        if not release.wait(5):
                            raise RuntimeError('test did not release first materializer')
                    else:
                        second_read.set()
                    return value
                @contextlib.contextmanager
                def lock(paths):
                    if names.role == 'second':
                        second_attempt.set()
                    with original_lock(paths):
                        yield
                def run(role):
                    names.role = role
                    return (state.rebuild_state if role == 'second' and rebuild else state.ensure_state)(self.repo)
                with patch.object(state, 'read_project_event_snapshot', side_effect=read), \
                     patch.object(state, '_event_lock', side_effect=lock), ThreadPoolExecutor(2) as pool:
                    first = pool.submit(run, 'first')
                    try:
                        self.assertTrue(first_read.wait(5))
                        second = pool.submit(run, 'second')
                        self.assertTrue(second_attempt.wait(5))
                        self.assertFalse(second_read.is_set(), 'waiting writer must not capture a stale snapshot')
                        self.append(objective('OBJ-THREE'))
                    finally:
                        release.set()
                    first.result(timeout=5)
                    second.result(timeout=5)
                self.assertTrue(second_read.is_set())
                actual = rows(self.paths.state)
                self.assertEqual(actual, rows(state.rebuild_state(self.repo)))
                self.assertEqual(state._meta(self.paths.state)['event_count'], '3')
                self.assertFalse((self.paths.root / 'state.lock').exists())

    def test_existing_reader_snapshot_remains_coherent_across_suffix_commit(self):
        self.append(objective('OBJ-ONE'))
        path = state.rebuild_state(self.repo)
        with contextlib.closing(sqlite3.connect(path)) as reader:
            reader.execute('pragma journal_mode=wal')
            reader.execute('begin')
            self.assertEqual(reader.execute('select count(*) from events').fetchone()[0], 1)
            old_digest = dict(reader.execute('select key,value from meta'))[state.VALIDATED_EVENT_DIGEST_META]
            self.append(objective('OBJ-TWO'))
            state.ensure_state(self.repo)
            self.assertEqual(reader.execute('select count(*) from entities').fetchone()[0], 1)
            self.assertEqual(dict(reader.execute('select key,value from meta'))[state.VALIDATED_EVENT_DIGEST_META], old_digest)
            reader.commit()
            self.assertEqual(reader.execute('select count(*) from entities').fetchone()[0], 2)
            self.assertNotEqual(dict(reader.execute('select key,value from meta'))[state.VALIDATED_EVENT_DIGEST_META], old_digest)

    def test_busy_sqlite_writer_is_not_replaced_or_silently_rebuilt(self):
        self.append(objective('OBJ-ONE'))
        path = state.rebuild_state(self.repo)
        before = path.read_bytes()
        self.append(objective('OBJ-TWO'))
        connect = state._connect
        def short_wait(path):
            conn = connect(path)
            conn.execute('pragma busy_timeout=1')  # Test wait only; product remains 5000ms.
            return conn
        with contextlib.closing(sqlite3.connect(path)) as writer:
            writer.execute('begin immediate')
            with patch.object(state, '_connect', side_effect=short_wait), \
                 patch.object(state, '_rebuild_snapshot', side_effect=AssertionError('busy state must not be replaced')):
                with self.assertRaisesRegex(sqlite3.OperationalError, 'locked'):
                    state.ensure_state(self.repo)
            writer.rollback()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(rows(state.ensure_state(self.repo)), rows(state.rebuild_state(self.repo)))

    def test_mixed_history_and_citations_match_rebuild_without_reprojecting_prefix(self):
        from diffwitness.continuity_bridge import record_change_envelope
        from diffwitness.continuity_tasks import _spec, _link_spec
        envelope, cid = fixtures.ContinuityKernelTests().envelope(self.repo)
        record_change_envelope(repo=self.repo, envelope=envelope)
        task_payload = dict(origin='explicit-declaration', anchor_sha256=None, anchor_chars=None,
                            session_sha256=None, ordinal=None, why='Refund work')
        task = self.append(_spec('task.recorded', 'TASK-ONE', task_payload, label='Refunds', dedupe='task:TASK-ONE'))[0][0]
        self.append(objective('OBJ-ONE'), objective('OBJ-TWO'))
        path = state.rebuild_state(self.repo, include_structure=True)
        before = rows(path)
        self.append(_spec('task.described', 'TASK-ONE', {**task_payload, 'why': 'Explicit updated intent',
                          'source_task_event_id': task['event_id']}, label='Safe refunds'))
        self.append(_link_spec('TASK-ONE', dict(task_event_id=task['event_id'], activation_event_id=None,
                          boundary_id=None, change_id=cid, why='Implements task'), native=False))
        self.append(lifecycle_spec(self.repo, 'objective', 'OBJ-ONE', 'supersede', 'Replaced', 'OBJ-TWO'))
        self.append(dict(event_type='debt.accepted', subject=dict(id='DW-0123456789AB', kind='debt'),
                         epistemic_status='DECLARED', payload={'reason': 'Explicit decision'}))
        state.ensure_state(self.repo, include_structure=True)
        incremental = rows(path)
        context = compile_context(self.repo, 'Refund', refresh_structure=False)
        for table in ('structure_components', 'structure_symbols', 'structure_edges'):
            self.assertEqual(incremental[table], before[table])
        rebuilt = rows(state.rebuild_state(self.repo, include_structure=True))
        # Rebuild legitimately regenerates only structure index timestamps.
        for value in (incremental, rebuilt):
            for table in ('structure_components', 'structure_symbols', 'structure_edges'):
                value[table] = sorted([row[:-1] for row in value[table]], key=repr)
            value['meta'] = [row for row in value['meta'] if row[0] != 'structure_indexed_at']
        self.assertEqual(incremental, rebuilt)
        again = compile_context(self.repo, 'Refund', refresh_structure=False)
        for field in ('objectives', 'decisions', 'invariants', 'tasks', 'relations'):
            self.assertEqual(context[field], again[field])

    def test_hash_valid_invalid_prefix_reference_rejects_update_and_append(self):
        self.append(objective('OBJ-ONE'))
        self.append(lifecycle_spec(self.repo, 'objective', 'OBJ-ONE', 'confirm', 'Reviewed'))
        path = state.rebuild_state(self.repo)
        before = path.read_bytes()
        events = journal.read_project_events(self.paths.events)
        events[-1]['payload']['previous_revision_event_id'] = 'dwev_' + 'f' * 24
        events[-1]['event_id'] = journal._event_id(events[-1])
        events[-1]['event_hash'] = journal._event_hash(events[-1])
        self.paths.events.write_bytes(b''.join((journal._canonical(e) + '\n').encode() for e in events))
        for operation in (lambda: state.ensure_state(self.repo), lambda: self.append(objective('OBJ-TWO'))):
            with self.assertRaisesRegex(journal.ContinuityError, 'revision'):
                operation()
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_framing_and_duplicate_conflicts_preserve_exact_bytes(self):
        for newline in (b'\n', b'\r\n', b'\r'):
            with self.subTest(newline=newline):
                self.paths.events.unlink(missing_ok=True)
                spec = objective('OBJ-UNICODE', 'Décision \u2028 sûre 🧭')
                self.append(spec)
                raw = newline + self.paths.events.read_bytes().replace(b'\n', newline)
                self.paths.events.write_bytes(raw)
                state.rebuild_state(self.repo)
                result = self.append(spec)
                self.assertFalse(result[0][1])
                self.assertEqual(self.paths.events.read_bytes(), raw)
                conflicting = copy.deepcopy(spec)
                conflicting['payload']['why'] = 'Different'
                with self.assertRaisesRegex(journal.ContinuityError, 'conflicting'):
                    self.append(objective('OBJ-NOT-WRITTEN'), conflicting)
                self.assertEqual(self.paths.events.read_bytes(), raw)
                self.append(objective('OBJ-TWO'))
                self.assertEqual(rows(state.ensure_state(self.repo)), rows(state.rebuild_state(self.repo)))


if __name__ == '__main__':
    unittest.main()
