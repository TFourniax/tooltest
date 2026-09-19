"""Windows lock contention must remain exclusive and bounded."""
from __future__ import annotations

import errno
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from diffwitness import continuity_events as journal
import test_continuity_kernel as fixtures
from test_continuity_incremental import objective


class EventLockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temp.name))
        self.paths = journal.continuity_paths(self.repo)

    def windows_os(self, opener):
        return SimpleNamespace(**{**vars(os), 'name': 'nt', 'open': opener})

    def test_transient_windows_create_denial_retries_exclusively_before_append(self):
        original_open = os.open
        calls = []
        def contended(path, flags, *args):
            if path == self.paths.lock:
                calls.append(flags)
                if len(calls) == 1:
                    raise PermissionError(errno.EACCES, 'delete pending', str(path))
            return original_open(path, flags, *args)
        with patch.object(journal, 'os', self.windows_os(contended)):
            result = journal.append_project_events(repo=self.repo, events=[objective('OBJ-ONE')])
        self.assertTrue(result[0][1])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(flags & os.O_EXCL and flags & os.O_CREAT for flags in calls))
        self.assertEqual(len(journal.read_project_events(self.paths.events)), 1)
        self.assertFalse(self.paths.lock.exists())

    def test_persistent_denial_cannot_enter_mutate_or_remove_foreign_lock(self):
        self.paths.root.mkdir(parents=True)
        self.paths.lock.write_text('foreign-owner', encoding='utf-8')
        denied = PermissionError(errno.EACCES, 'access denied', str(self.paths.lock))
        with patch.object(journal, 'os', self.windows_os(lambda *a: (_ for _ in ()).throw(denied))), \
             patch.object(journal.time, 'monotonic', side_effect=[0.0, 0.05, 0.11]), \
             patch.object(journal.time, 'sleep') as sleep:
            with self.assertRaises(journal.ContinuityError) as result:
                with journal._event_lock(self.paths, timeout=0.1):
                    self.fail('unacquired lock entered')
        self.assertIs(result.exception.__cause__, denied)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(self.paths.lock.read_text(), 'foreign-owner')
        self.assertFalse(self.paths.events.exists())

    def test_denial_followed_by_live_owner_does_not_authorize_entry(self):
        self.paths.root.mkdir(parents=True)
        self.paths.lock.write_text('foreign-owner', encoding='utf-8')
        calls = iter([PermissionError(errno.EACCES, 'delete pending'), FileExistsError(errno.EEXIST, 'busy')])
        def contended(*args):
            raise next(calls)
        with patch.object(journal, 'os', self.windows_os(contended)), \
             patch.object(journal.time, 'monotonic', side_effect=[0.0, 0.05, 0.11]), \
             patch.object(journal.time, 'sleep'):
            with self.assertRaises(journal.ContinuityError):
                with journal._event_lock(self.paths, timeout=0.1):
                    self.fail('foreign lock entered')
        self.assertEqual(self.paths.lock.read_text(), 'foreign-owner')

    def test_non_windows_permission_denial_is_not_retried(self):
        denied = PermissionError(errno.EACCES, 'permissions')
        fake_os = SimpleNamespace(**{**vars(os), 'name': 'posix', 'open': lambda *a: (_ for _ in ()).throw(denied)})
        with patch.object(journal, 'os', fake_os), patch.object(journal.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                with journal._event_lock(self.paths):
                    self.fail('unacquired lock entered')
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
