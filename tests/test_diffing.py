from __future__ import annotations

import unittest

from diffwitness.diffing import is_test_path, make_mutations, parse_file_patches


class DiffingTests(unittest.TestCase):
    def test_test_path_detection(self) -> None:
        self.assertTrue(is_test_path("tests/test_calc.py"))
        self.assertTrue(is_test_path("src/foo.spec.ts"))
        self.assertFalse(is_test_path("src/calculator.py"))
        self.assertTrue(is_test_path("checks/example.case", ["checks/*.case"]))

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
