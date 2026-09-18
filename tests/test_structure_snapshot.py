from __future__ import annotations
import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness.continuity_context_enriched import compile_context
from diffwitness.continuity_state import rebuild_state, ensure_state
from diffwitness import structure_provider as provider
from diffwitness import structure_sources as sources
from diffwitness.gitops import git_bytes


class StructureSnapshotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fixture = fixtures.ContinuityKernelTests()
        self.repo = self.fixture.repo(Path(temp.name))

    def rows(self, state):
        with contextlib.closing(sqlite3.connect(state)) as conn:
            return [row[0] for row in conn.execute("select qualified_name from structure_symbols")]

    def test_dirty_untracked_and_deleted_working_files_cannot_change_head_bound_facts(self):
        expected = self.rows(rebuild_state(self.repo, include_structure=True))
        original_tree = self.fixture.git(self.repo, "rev-parse", "HEAD^{tree}")
        (self.repo / "payments/refund.py").write_text("def PRIVATE_DIRTY_SYMBOL(): pass\n", encoding="utf-8")
        (self.repo / "untracked.py").write_text("def PRIVATE_UNTRACKED_SYMBOL(): pass\n", encoding="utf-8")
        (self.repo / "payments/rules.py").unlink()
        state = rebuild_state(self.repo, include_structure=True)
        self.assertEqual(self.rows(state), expected)
        with contextlib.closing(sqlite3.connect(state)) as conn:
            self.assertEqual(conn.execute("select distinct tree_sha from structure_components").fetchall(), [(original_tree,)])
            self.assertEqual(conn.execute("select path from structure_components order by path").fetchall(), [("payments/refund.py",), ("payments/rules.py",)])
        self.assertNotIn(b"PRIVATE_DIRTY", state.read_bytes())
        self.assertNotIn(b"PRIVATE_UNTRACKED", state.read_bytes())

    def test_head_advance_during_refresh_keeps_one_tree_and_next_refresh_updates(self):
        old_tree = self.fixture.git(self.repo, "rev-parse", "HEAD^{tree}")
        old_head = provider._head_tree
        def advance(repo):
            value = old_head(repo)
            (repo / "payments/refund.py").write_text("def replacement(): pass\n", encoding="utf-8")
            self.fixture.git(repo, "add", ".")
            self.fixture.git(repo, "commit", "-qm", "new version during refresh")
            return value
        with patch.object(provider, "_head_tree", side_effect=advance):
            state = rebuild_state(self.repo, include_structure=True)
        self.assertIn("payments.refund.refund", self.rows(state))
        self.assertNotIn("payments.refund.replacement", self.rows(state))
        with contextlib.closing(sqlite3.connect(state)) as conn:
            self.assertEqual(conn.execute("select value from meta where key='structure_tree'").fetchone()[0], old_tree)
            self.assertTrue(provider.structure_index_needs_refresh(self.repo, conn))
        self.assertIn("payments.refund.replacement", self.rows(ensure_state(self.repo, include_structure=True)))

    def test_git_symlink_mode_is_excluded_even_if_worktree_is_a_regular_python_file(self):
        target = git_bytes(self.repo, "hash-object", "-w", "--stdin", input_bytes=b"../private.py\n").decode().strip()
        self.fixture.git(self.repo, "update-index", "--add", "--cacheinfo", f"120000,{target},linked.py")
        self.fixture.git(self.repo, "commit", "-qm", "tracked symlink")
        (self.repo / "linked.py").write_text("def PRIVATE_TARGET(): pass\n", encoding="utf-8")
        state = rebuild_state(self.repo, include_structure=True)
        self.assertFalse(any("PRIVATE_TARGET" in name for name in self.rows(state)))
        with contextlib.closing(sqlite3.connect(state)) as conn:
            self.assertEqual(conn.execute("select count(*) from structure_components where path='linked.py'").fetchone()[0], 0)

    def test_bounded_coverage_and_parse_failures_are_visible_in_context(self):
        (self.repo / "huge.py").write_bytes(b"#" + b"x" * (1024 * 1024 + 1))
        (self.repo / "invalid.py").write_text("def broken(:\n", encoding="utf-8")
        self.fixture.git(self.repo, "add", ".")
        self.fixture.git(self.repo, "commit", "-qm", "bounded sources")
        context = compile_context(self.repo, "refund", refresh_structure=True)
        coverage = context["state"]["structureCoverage"]
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["oversized"], 1)
        self.assertEqual(coverage["unparsed"], 1)
        self.assertTrue(any("incomplete" in warning for warning in context["warnings"]))
        state = ensure_state(self.repo)
        with contextlib.closing(sqlite3.connect(state)) as conn:
            limited = provider.refresh_structure_index(self.repo, conn=conn, max_files=1)
            self.assertTrue(limited["truncated"])
            self.assertEqual(limited["files"], 1)
            with self.assertRaises(ValueError):
                provider.refresh_structure_index(self.repo, conn=conn, max_files=0)

    def test_old_tree_stamp_cannot_preserve_mutable_file_projection(self):
        state = rebuild_state(self.repo, include_structure=True)
        with contextlib.closing(sqlite3.connect(state)) as conn:
            conn.execute("update meta set value='continuity-state-4' where key='schema'")
            conn.execute("update structure_components set path='FORGED.py' where path='payments/refund.py'")
            conn.commit()
        context = compile_context(self.repo, "FORGED", refresh_structure=False)
        self.assertFalse(any(item["path"] == "FORGED.py" for item in context["components"]))

    def test_corrupt_blob_response_cannot_replace_existing_index(self):
        state = rebuild_state(self.repo, include_structure=True)
        expected = self.rows(state)
        original = sources.git_bytes
        def corrupt(repo, *args, **kwargs):
            value = original(repo, *args, **kwargs)
            return value.replace(b"def refund", b"def forged") if args[0] == "cat-file" else value
        with contextlib.closing(sqlite3.connect(state)) as conn, patch.object(sources, "git_bytes", side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, "object identity"):
                provider.refresh_structure_index(self.repo, conn=conn)
            conn.commit()
        self.assertEqual(self.rows(state), expected)

    def test_total_byte_budget_omits_whole_blobs_and_reports_partial_coverage(self):
        tree = self.fixture.git(self.repo, "rev-parse", "HEAD^{tree}")
        with patch.object(sources, "MAX_SOURCE_TOTAL_BYTES", 30):
            files, coverage = sources.tree_sources(self.repo, tree, suffixes=(".py",))
        self.assertLessEqual(sum(len(content) for _, content in files), 30)
        self.assertEqual([name for name, _ in files], ["payments/rules.py"])
        self.assertTrue(coverage["truncated"])
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["omittedByLimit"], 1)


if __name__ == "__main__":
    unittest.main()
