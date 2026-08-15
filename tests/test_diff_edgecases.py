from __future__ import annotations

import unittest

from diffwitness.diffing import make_mutations, parse_file_patches


class DiffEdgeCaseTests(unittest.TestCase):
    def test_path_with_spaces_remains_one_hunk_mutation(self) -> None:
        diff = '''diff --git "a/src/my file.py" "b/src/my file.py"
index 1111111..2222222 100644
--- "a/src/my file.py"
+++ "b/src/my file.py"
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
'''
        files = parse_file_patches(diff)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].path, "src/my file.py")
        mutations = make_mutations(files)
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0].path, "src/my file.py")

    def test_new_production_file_is_conservative_structural_mutation(self) -> None:
        diff = '''diff --git a/src/new.py b/src/new.py
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+def value():
+    return 42
'''
        files = parse_file_patches(diff)
        self.assertTrue(files[0].structural)
        mutations = make_mutations(files)
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0].kind, "structural")
        self.assertEqual(mutations[0].additions, 2)

    def test_rename_is_file_level_even_with_text_hunk(self) -> None:
        diff = '''diff --git a/src/old.py b/src/new.py
similarity index 80%
rename from src/old.py
rename to src/new.py
index 1111111..2222222 100644
--- a/src/old.py
+++ b/src/new.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
'''
        files = parse_file_patches(diff)
        self.assertTrue(files[0].structural)
        mutations = make_mutations(files)
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0].kind, "structural")

    def test_binary_change_is_never_misrepresented_as_line_hunk(self) -> None:
        diff = '''diff --git a/assets/model.bin b/assets/model.bin
index 1111111..2222222 100644
Binary files a/assets/model.bin and b/assets/model.bin differ
'''
        files = parse_file_patches(diff)
        self.assertTrue(files[0].binary)
        mutations = make_mutations(files)
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0].kind, "binary")

    def test_documentation_new_file_does_not_enter_executable_causal_surface(self) -> None:
        diff = '''diff --git a/docs/design.md b/docs/design.md
new file mode 100644
index 0000000..2222222
--- /dev/null
+++ b/docs/design.md
@@ -0,0 +1 @@
+# Design
'''
        files = parse_file_patches(diff)
        self.assertEqual(make_mutations(files), [])
        self.assertEqual(len(make_mutations(files, include_docs=True)), 1)


if __name__ == "__main__":
    unittest.main()
