from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness import continuity_state as state
from diffwitness.continuity_events import append_project_event, continuity_paths


class SchemaTransactionTests(unittest.TestCase):
    def test_v8_lexical_table_rebuild_preserves_terms_and_journal(self):
        with tempfile.TemporaryDirectory() as td:
            repo = fixtures.ContinuityKernelTests().repo(Path(td))
            append_project_event(repo=repo, event_type='objective.declared',
                                 subject={'id':'OBJ-ONE','kind':'objective','label':'Réinitialisation sûre'},
                                 epistemic_status='DECLARED', payload={'why':'Conserver les références'})
            path = state.rebuild_state(repo)
            paths = continuity_paths(repo)
            journal = paths.events.read_bytes()
            with contextlib.closing(sqlite3.connect(path)) as conn:
                terms = conn.execute('select * from entity_terms order by entity_id,term').fetchall()
                conn.execute('alter table entity_terms rename to previous_terms')
                conn.execute('create table entity_terms(entity_id text not null, term text not null, primary key(entity_id,term))')
                conn.execute('insert into entity_terms select * from previous_terms')
                conn.execute('drop table previous_terms')
                conn.execute('create index entity_terms_term_idx on entity_terms(term,entity_id)')
                conn.execute("update meta set value='continuity-state-8' where key='schema'")
                conn.commit()
                self.assertEqual(conn.execute('pragma index_info(entity_terms)').fetchall(), [])
            state.ensure_state(repo)
            with contextlib.closing(sqlite3.connect(path)) as conn:
                self.assertTrue(conn.execute('pragma index_info(entity_terms)').fetchall())
                self.assertEqual(conn.execute('select * from entity_terms order by entity_id,term').fetchall(), terms)
                self.assertEqual(conn.execute("select value from meta where key='schema'").fetchone()[0], state.STATE_SCHEMA)
                self.assertEqual(conn.execute('pragma integrity_check').fetchone(), ('ok',))
            self.assertEqual(paths.events.read_bytes(), journal)

    def test_deferred_indexes_keep_constraints_and_exact_final_schema(self):
        with contextlib.closing(sqlite3.connect(':memory:')) as eager, \
             contextlib.closing(sqlite3.connect(':memory:')) as deferred:
            state._schema(eager)
            state._schema(deferred, indexes=False)
            for conn in (eager, deferred):
                conn.execute("insert into entity_terms values('OBJ-ONE','refund')")
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("insert into entity_terms values('OBJ-ONE','refund')")
                self.assertTrue(conn.in_transaction)
            state._indexes(deferred)
            schema = "select type,name,tbl_name,sql from sqlite_master order by type,name"
            self.assertEqual(eager.execute(schema).fetchall(), deferred.execute(schema).fetchall())
            for conn in (eager, deferred):
                self.assertEqual(conn.execute('pragma integrity_check').fetchone(), ('ok',))
                self.assertEqual(conn.execute('select * from entity_terms').fetchall(), [('OBJ-ONE', 'refund')])
                conn.rollback()
                self.assertEqual(conn.execute('select name from sqlite_master').fetchall(), [])

    def test_late_index_failure_keeps_previous_projection_and_journal(self):
        with tempfile.TemporaryDirectory() as td:
            repo = fixtures.ContinuityKernelTests().repo(Path(td))
            append_project_event(repo=repo, event_type='objective.declared',
                                 subject={'id':'OBJ-ONE','kind':'objective','label':'Refund safely'},
                                 epistemic_status='DECLARED')
            path = state.rebuild_state(repo, include_structure=True)
            paths = continuity_paths(repo)
            before, journal = path.read_bytes(), paths.events.read_bytes()
            indexes = state._indexes
            observed = []
            def fail_after_indexes(conn):
                indexes(conn)
                observed.append((conn.in_transaction, conn.execute('select count(*) from events').fetchone()[0]))
                raise RuntimeError('injected late index failure')
            with patch.object(state, '_indexes', side_effect=fail_after_indexes):
                with self.assertRaisesRegex(RuntimeError, 'injected late index'):
                    state.rebuild_state(repo, include_structure=True)
            self.assertEqual(observed, [(True, 1)])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(paths.events.read_bytes(), journal)
            self.assertEqual(list(paths.root.glob('state-*.db')), [])
            self.assertTrue(state.state_status(repo)['state_current'])

    def test_schema_and_rows_can_be_rolled_back_together(self):
        with contextlib.closing(sqlite3.connect(':memory:')) as conn:
            state._schema(conn)
            self.assertTrue(conn.in_transaction, 'schema must not commit each DDL separately')
            conn.execute("insert into meta(key,value) values('probe','value')")
            conn.rollback()
            self.assertEqual(conn.execute("select name from sqlite_master where type='table'").fetchall(), [])

    def test_failed_rebuild_preserves_old_state_and_cleans_temporary_database(self):
        with tempfile.TemporaryDirectory() as td:
            repo = fixtures.ContinuityKernelTests().repo(Path(td))
            append_project_event(repo=repo, event_type='objective.declared',
                                 subject={'id':'OBJ-ONE','kind':'objective','label':'Refund safely'},
                                 epistemic_status='DECLARED')
            path = state.rebuild_state(repo, include_structure=True)
            before = path.read_bytes()
            observed = []
            project = state._upsert_entity
            def fail_after_projection(conn, event):
                observed.append(conn.in_transaction)
                project(conn, event)
                raise RuntimeError('injected materialization failure')
            with patch.object(state, '_upsert_entity', side_effect=fail_after_projection):
                with self.assertRaisesRegex(RuntimeError, 'injected materialization'):
                    state.rebuild_state(repo, include_structure=True)
            self.assertEqual(observed, [True])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(continuity_paths(repo).root.glob('state-*.db')), [])
            self.assertTrue(state.state_status(repo)['state_current'])


if __name__ == '__main__':
    unittest.main()
