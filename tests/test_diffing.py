from __future__ import annotations

import unittest

from diffwitness.diffing import is_test_path, make_mutations, parse_file_patches


DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,4 @@ def calculate():
-    return a - b
+    return a + b
@@ -20,3 +20,4 @@ def helper():
     return 1
+\n
+UNRELATED = True
diff --git a/tests/test_app.py b/tests/test_app.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/tests/test_app.py
@@ -0,0 +1,2 @@
+def test_x():
+    assert True
"""


class DiffingTests(unittest.TestCase):
    def test_test_path_detection(self) -> None:
        self.assertTrue(is_test_path("tests/test_app.py"))
        self.assertTrue(is_test_path("src/foo.spec.ts"))
        self.assertTrue(is_test_path("conftest.py"))
        self.assertFalse(is_test_path("src/app.py"))

    def test_production_hunks_are_individual_mutations(self) -> None:
        files = parse_file_patches(DIFF)
        self.assertEqual(len(files), 2)
        mutations = make_mutations(files)
        self.assertEqual(len(mutations), 2)
        self.assertTrue(all(m.path == "src/app.py" for m in mutations))
        self.assertEqual(sum(m.additions for m in mutations), 3)

    def test_test_file_excluded_by_default(self) -> None:
        files = parse_file_patches(DIFF)
        mutations = make_mutations(files, include_tests=True)
        self.assertEqual(len(mutations), 3)
        self.assertEqual(mutations[-1].kind, "structural")


if __name__ == "__main__":
    unittest.main()
