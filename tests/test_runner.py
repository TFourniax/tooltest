from __future__ import annotations

import unittest

from diffwitness.models import CommandResult
from diffwitness.runner import classify_runs


def r(code: int | None, *, timeout: bool = False) -> CommandResult:
    return CommandResult(returncode=code, duration_s=0.01, timed_out=timeout)


class RunnerTests(unittest.TestCase):
    def test_classifies_stability(self) -> None:
        self.assertEqual(classify_runs([r(0), r(0)]), "stable-pass")
        self.assertEqual(classify_runs([r(1), r(2)]), "stable-fail")
        self.assertEqual(classify_runs([r(0), r(1)]), "flaky")
        self.assertEqual(classify_runs([r(None, timeout=True), r(0)]), "timeout")


if __name__ == "__main__":
    unittest.main()
