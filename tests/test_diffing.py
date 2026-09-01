from __future__ import annotations

import unittest

from diffwitness.diffing import (
    is_documentation_path,
    is_test_path,
    make_mutations,
    parse_file_patches,
)


class DiffingTests(unittest.TestCase):
    def test_test_path_detection(self) -> None:
        self.assertTrue(is_test_path("tests/test_calc.py"))
        self.assertTrue(is_test_path("src/foo.spec.ts"))
        self.assertFalse(is_test_path("src/calculator.py"))
        self.assertTrue(is_test_path("checks/example.case", ["checks/*.case"]))

    def test_documentation_classifier_is_narrow(self) -> None:
        self.assertTrue(is_documentation_path("README.md"))
        self.assertTrue(is_documentation_path("docs/architecture.rst"))
        self.assertTrue(is_documentation_path("CHANGELOG"))
        self.assertFalse(is_documentation_path("pyproject.toml"))
        self.assertFalse(is_documentation_path("package.json"))
        self.assertFalse(is_documentation_path("migrations/001.sql"))

    def test_documentation_hunks_are_excluded_by_default_but_can_be_included(self) -> None:
        diff = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""
        files = parse_file_patches(diff)
        self.assertEqual(make_mutations(files), [])
        self.assertEqual(len(make_mutations(files, include_docs=True)), 1)

    def test_hunk_ranges_become_annotation_lines(self) -> None:
        diff = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -10,2 +10,3 @@ def f():
-old
+new
+more
 context
"""
        files = parse_file_patches(diff)
        mutations = make_mutations(files)
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0].line, 10)
        self.assertEqual(mutations[0].end_line, 12)
        self.assertEqual(mutations[0].additions, 2)
        self.assertEqual(mutations[0].deletions, 1)


if __name__ == "__main__":
    unittest.main()
