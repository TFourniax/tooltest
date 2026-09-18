from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness.continuity_context import compile_context
from diffwitness import continuity_context as context
from diffwitness.continuity_events import ContinuityError, append_project_event, append_project_events, continuity_paths
from diffwitness.continuity_lifecycle import lifecycle_spec
from diffwitness.continuity_state import rebuild_state


class ContextSourceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temp.name))

    def record(self, label='Refund decision', status='DECLARED'):
        event, _ = append_project_event(repo=self.repo, event_type='decision.recorded',
            subject={'id':'DEC-CITED', 'kind':'decision', 'label':label}, epistemic_status=status,
            payload={'why':'Refund safety'}, provenance={'producer':'test', 'source':'human-cli',
                                                        'private_metadata':'PRIVATE_SOURCE_SENTINEL'})
        return event

    def item(self):
        return next(item for item in compile_context(self.repo, 'refund', refresh_structure=False)['decisions']
                    if item['id'] == 'DEC-CITED')

    def test_citation_tracks_the_exact_assertion_not_the_latest_journal_head(self):
        first = self.record()
        before = self.item()
        self.assertEqual(before['source'], {'kind':'project-event', 'eventId':first['event_id'], 'eventHash':first['event_hash']})
        append_project_event(repo=self.repo, event_type='objective.declared',
            subject={'id':'OBJ-OTHER', 'kind':'objective', 'label':'Other objective'}, epistemic_status='DECLARED')
        self.assertEqual(self.item()['source'], before['source'])
        second = self.record('Refund revised decision', 'INFERRED')
        after = self.item()
        self.assertEqual(after['source']['eventId'], second['event_id'])
        self.assertEqual(after['source']['eventHash'], second['event_hash'])
        self.assertEqual(after['epistemicStatus'], 'INFERRED')
        self.assertEqual(before['source']['eventHash'], first['event_hash'])
        self.assertNotIn('PRIVATE_SOURCE_SENTINEL', str(after))
        rebuild_state(self.repo, include_structure=False)
        self.assertEqual(self.item(), after)

    def test_missing_assertion_row_cannot_produce_a_fabricated_citation(self):
        self.record()
        self.item()  # Establish the existing validated journal/cache stamp.
        with contextlib.closing(sqlite3.connect(continuity_paths(self.repo).state)) as conn:
            conn.execute('delete from events')
            conn.commit()
        with self.assertRaises(ContinuityError):
            self.item()

    def test_confirmation_cites_its_review_separately_from_the_assertion(self):
        assertion = self.record(status='INFERRED')
        review = append_project_events(repo=self.repo, events=[
            lifecycle_spec(self.repo, 'decision', 'DEC-CITED', 'confirm', 'Reviewed applicability')])[0][0]
        item = self.item()
        self.assertEqual(item['source']['eventId'], assertion['event_id'])
        self.assertEqual(item['source']['eventHash'], assertion['event_hash'])
        self.assertEqual(item['epistemicStatus'], 'INFERRED')
        self.assertEqual(item['lifecycle']['sourceEventId'], review['event_id'])
        self.assertEqual(item['lifecycle']['epistemicStatus'], 'DECLARED')
        rebuild_state(self.repo, include_structure=False)
        self.assertEqual(self.item(), item)

    def test_inconsistent_assertion_status_or_details_cannot_be_cited(self):
        self.record()
        for column, value in (('epistemic_status', 'VERIFIED'), ('payload_json', '{"why":"altered"}')):
            with self.subTest(column=column):
                rebuild_state(self.repo, include_structure=False)
                with contextlib.closing(sqlite3.connect(continuity_paths(self.repo).state)) as conn:
                    conn.execute(f'update entities set {column}=?', (value,))
                    conn.commit()
                with self.assertRaises(ContinuityError):
                    self.item()

    def test_packet_anchor_and_citations_share_a_read_snapshot(self):
        assertion = self.record()
        self.item()
        state = continuity_paths(self.repo).state
        with contextlib.closing(sqlite3.connect(state)) as conn:
            conn.execute('pragma journal_mode=WAL')
        related = context._related_files

        def concurrent_cache_change(conn, *args, **kwargs):
            result = related(conn, *args, **kwargs)
            with contextlib.closing(sqlite3.connect(state)) as writer:
                writer.execute('delete from events')
                writer.execute("update meta set value='changed-after-read' where key='event_head'")
                writer.commit()
            return result

        with patch.object(context, '_related_files', side_effect=concurrent_cache_change):
            packet = compile_context(self.repo, 'refund', refresh_structure=False)
        self.assertEqual(packet['state']['eventHead'], assertion['event_hash'])
        self.assertEqual(packet['decisions'][0]['source']['eventHash'], assertion['event_hash'])
        with self.assertRaises(ContinuityError):
            self.item()


if __name__ == '__main__':
    unittest.main()
