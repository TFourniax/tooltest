from __future__ import annotations

import contextlib
import io
import unittest

from diffwitness.github_actions import emit_annotations


class GitHubActionTests(unittest.TestCase):
    def test_unwitnessed_hunk_becomes_file_warning(self) -> None:
        report = {
            "results": [
                {
                    "status": "unwitnessed",
                    "mutation": {"path": "src/a,b.py", "line": 7, "end_line": 9},
                }
            ]
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            emit_annotations(report)
        text = output.getvalue()
        self.assertIn("::warning ", text)
        self.assertIn("file=src/a%2Cb.py", text)
        self.assertIn("line=7", text)
        self.assertIn("endLine=9", text)


if __name__ == "__main__":
    unittest.main()
