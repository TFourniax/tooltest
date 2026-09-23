from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness import continuity_events as journal, continuity_state as state
from diffwitness.continuity_contract import DECLARATION_PROFILE, PROFILE_PROVENANCE_FIELD
from diffwitness.continuity_lifecycle import lifecycle_spec


def declaration(index):
    event_type, kind, prefix, payload, predicate, target_kind = (
        ('objective.declared', 'objective', 'OBJ', {'why': f'Fact {index}', 'priority':'normal'}, 'served_by', 'component'),
        ('decision.recorded', 'decision', 'DEC', {'why': f'Fact {index}', 'alternatives':['Prior option']}, 'motivated_by', 'objective'),
        ('invariant.declared', 'invariant', 'INV', {'why': f'Fact {index}', 'critical':bool(index % 3)}, 'constrains', 'component'),
        ('approach.failed', 'failed-approach', 'FAIL', {'reason':f'Failure {index}'}, 'informed', 'decision'),
    )[index % 4]
    return dict(event_type=event_type, subject=dict(id=f'{prefix}-{index % 7}', kind=kind,
                label=None if index % 5 == 0 else f'Mémoire {index}'),
                epistemic_status='DECLARED', payload=payload,
                relations=[dict(predicate=predicate, target=dict(id='TARGET-ONE', kind=target_kind),
                                epistemic_status='DECLARED', metadata={'revision':index})],
                provenance={'producer':'fixture', 'source':'batch-equivalence', PROFILE_PROVENANCE_FIELD:DECLARATION_PROFILE},
                actor={'kind':'human', 'id':'fixture'}, dedupe_key=f'batch:{index}')


def tables(conn):
    names = [row[0] for row in conn.execute("select name from sqlite_master where type='table' order by name")]
    return {name:sorted((tuple(row) for row in conn.execute('select * from "' + name + '"')), key=repr) for name in names}


class ProjectionBatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temp.name))
        self.paths = journal.continuity_paths(self.repo)

    def test_bounded_batches_equal_sequential_projection_across_updates_and_lifecycle(self):
        specs = [declaration(index) for index in range(2052)]
        for start in range(0, len(specs), 2048):
            journal.append_project_events(repo=self.repo, events=specs[start:start + 2048])
        journal.append_project_events(repo=self.repo, events=[
            lifecycle_spec(self.repo, 'objective', 'OBJ-0', 'retire', 'Historical'),
            dict(event_type='objective.declared', subject={'id':'OBJ-LEGACY','kind':'objective','label':'Legacy observed'},
                 epistemic_status='OBSERVED', payload={'why':'Older unprofiled input'}),
            {**declaration(2052), 'subject':{'id':'OBJ-LEGACY','kind':'objective','label':None}},
        ])
        events = journal.read_project_events(self.paths.events)
        before = self.paths.events.read_bytes()
        with contextlib.closing(sqlite3.connect(':memory:')) as sequential, \
             contextlib.closing(sqlite3.connect(':memory:')) as batched:
            for conn in (sequential, batched):
                conn.row_factory = sqlite3.Row
                state._schema(conn)
            for sequence, event in enumerate(events, 1):
                state._project_event(sequential, sequence, event)
            sizes = []
            project = state._project_declarations
            def observe(conn, entries):
                sizes.append(len(entries))
                return project(conn, entries)
            with patch.object(state, '_project_declarations', side_effect=observe):
                state._project_history(batched, events)
            self.assertEqual(sizes, [2048, 4, 1])
            self.assertEqual(tables(sequential), tables(batched))
            row = batched.execute("select label,epistemic_status,source_event_id from entities where entity_id='OBJ-LEGACY'").fetchone()
            self.assertEqual(tuple(row), ('Legacy observed', 'DECLARED', events[-1]['event_id']))
            self.assertEqual(batched.execute("select lifecycle from entities where entity_id='OBJ-0'").fetchone()[0], 'inactive')
        self.assertEqual(self.paths.events.read_bytes(), before)

    def test_batch_write_failure_preserves_existing_database_and_all_journal_bytes(self):
        journal.append_project_events(repo=self.repo, events=[declaration(1)])
        path = state.rebuild_state(self.repo)
        previous = path.read_bytes()
        journal.append_project_events(repo=self.repo, events=[declaration(2)])
        before = self.paths.events.read_bytes()
        project = state._project_declarations
        observed = []
        def fail(conn, entries):
            project(conn, entries)
            observed.append((conn.in_transaction, conn.execute('select count(*) from events').fetchone()[0]))
            raise RuntimeError('injected batch failure')
        with patch.object(state, '_project_declarations', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'injected batch'):
                state.rebuild_state(self.repo)
        self.assertEqual(observed, [(True, 2)])
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(self.paths.events.read_bytes(), before)
        self.assertEqual(list(self.paths.root.glob('state-*.db')), [])


if __name__ == '__main__':
    unittest.main()
