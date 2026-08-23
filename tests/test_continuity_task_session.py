from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_task_session import (
    is_explicit_task_pivot,
    is_weak_followup,
    stable_task_id,
    task_context_query,
    task_session_path,
    update_task_session,
)


class ContinuityTaskSessionTests(unittest.TestCase):
    def test_task_id_has_frozen_cross_runtime_vector(self):
        self.assertEqual(
            stable_task_id("session-1", 1, "Implement partial refunds safely"),
            "dwtask_f347d504913fb4938155fabe",
        )

    def test_short_followup_keeps_anchor_and_task_identity(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            first = update_task_session(repo, "session-1", "Implement partial refunds safely", timestamp="2026-08-23T10:00:00Z")
            again = update_task_session(repo, "session-1", "yes, continue", timestamp="2026-08-23T10:01:00Z")
            self.assertEqual(first["task"]["id"], again["task"]["id"])
            self.assertEqual(again["task"]["anchor"], "Implement partial refunds safely")
            self.assertEqual(again["task"]["latest_focus"], "Implement partial refunds safely")
            self.assertEqual(again["boundary"], "continued")
            self.assertEqual(task_context_query(again["task"]), "Implement partial refunds safely")

    def test_substantive_focus_stays_inside_task_until_explicit_pivot(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            first = update_task_session(repo, "session-1", "Implement partial refunds safely")
            focused = update_task_session(repo, "session-1", "Make refund retries idempotent in payments")
            self.assertEqual(first["task"]["id"], focused["task"]["id"])
            self.assertIn("Primary task: Implement partial refunds safely", task_context_query(focused["task"]))
            self.assertIn("Current focus: Make refund retries idempotent in payments", task_context_query(focused["task"]))
            pivot = update_task_session(repo, "session-1", "New task: add CSV exports")
            self.assertNotEqual(focused["task"]["id"], pivot["task"]["id"])
            self.assertEqual(pivot["task"]["ordinal"], 2)
            self.assertEqual(pivot["boundary"], "pivoted")

    def test_classification_is_conservative_and_state_is_outside_project(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            result = update_task_session(repo, "session-1", "Implement partial refunds safely")
            self.assertTrue(is_weak_followup("oui"))
            self.assertTrue(is_weak_followup("corrige ça"))
            self.assertFalse(is_weak_followup("change the refund retry algorithm"))
            self.assertTrue(is_explicit_task_pivot("Passons à la page de facturation"))
            self.assertFalse(is_explicit_task_pivot("Continue with the refund tests"))
            self.assertFalse(str(result["path"]).startswith(str(repo)))
            self.assertEqual(result["path"], task_session_path(repo, "session-1"))


if __name__ == "__main__":
    unittest.main()
