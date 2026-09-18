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
