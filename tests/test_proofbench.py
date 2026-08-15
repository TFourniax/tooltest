from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class ProofBenchTests(unittest.TestCase):
    def test_reference_semantics_all_hold(self) -> None:
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, str(root / "benchmarks" / "proofbench.py"), "--json"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        results = json.loads(proc.stdout)
        self.assertGreaterEqual(len(results), 4)
        self.assertTrue(all(result["passed"] for result in results))
        by_name = {result["scenario"]: result for result in results}
        self.assertEqual(
            by_name["new-tests-do-not-discriminate-change"]["classification"],
            "non-discriminating-change",
        )
        self.assertEqual(
            by_name["behavior-preserving-refactor"]["classification"],
            "preservation-evidence",
        )


if __name__ == "__main__":
    unittest.main()
