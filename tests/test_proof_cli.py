from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from diffwitness.proof_cli import _policy_passes, main


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout


class ProofCliTests(unittest.TestCase):
    def test_balanced_and_strict_policies_are_distinct(self) -> None:
        report = {
            "candidate_run": {"classification": "stable-pass"},
            "contrast": "base-pass_candidate-pass",
            "summary": {
                "inconclusive": 0,
                "surplus_candidate_hunks": 0,
                "unwitnessed": 1,
            },
        }
        self.assertTrue(_policy_passes(report, "balanced")[0])
        self.assertFalse(_policy_passes(report, "strict")[0])
        self.assertTrue(_policy_passes(report, "observe")[0])

    def test_doctor_explains_default_detection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "tests").mkdir()
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["doctor", "--repo", str(repo)])
            self.assertEqual(rc, 0)
            text = out.getvalue()
            self.assertIn("python -m unittest discover -s tests -q", text)
            self.assertIn("<- default", text)

    def test_guard_captures_pre_agent_state_and_accepts_proven_fix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "guard@example.com", cwd=repo)
            git("config", "user.name", "Guard Test", cwd=repo)
            (repo / "calc.py").write_text(
                "def add(a, b):\n    return a - b\n", encoding="utf-8"
            )
            git("add", "calc.py", cwd=repo)
            git("commit", "-q", "-m", "buggy baseline", cwd=repo)

            agent_script = (
                "from pathlib import Path; "
                "Path('calc.py').write_text('def add(a, b):\\n    return a + b\\n', encoding='utf-8'); "
                "Path('tests').mkdir(exist_ok=True); "
                "Path('tests/test_calc.py').write_text("
                "\"import unittest\\nfrom calc import add\\n\\nclass T(unittest.TestCase):\\n    def test_add(self):\\n        self.assertEqual(add(2, 3), 5)\\n\", encoding='utf-8')"
            )
            test_command = f'"{sys.executable}" -m unittest discover -s tests -q'
            rc = main(
                [
                    "guard",
                    "--repo",
                    str(repo),
                    "--test",
                    test_command,
                    "--policy",
                    "strict",
                    "--stability-runs",
                    "1",
                    "--",
                    sys.executable,
                    "-c",
                    agent_script,
                ]
            )
            self.assertEqual(rc, 0)
            self.assertIn("return a + b", (repo / "calc.py").read_text(encoding="utf-8"))

    def test_guard_rejects_scope_creep_under_strict_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "guard@example.com", cwd=repo)
            git("config", "user.name", "Guard Test", cwd=repo)
            (repo / "calc.py").write_text(
                "def add(a, b):\n    return a - b\n\n\n\n\n\n\n\n\ndef label():\n    return 'calc'\n",
                encoding="utf-8",
            )
            git("add", "calc.py", cwd=repo)
            git("commit", "-q", "-m", "buggy baseline", cwd=repo)

            agent_script = (
                "from pathlib import Path; "
                "Path('calc.py').write_text("
                "\"def add(a, b):\\n    return a + b\\n\\n\\n\\n\\n\\n\\n\\n\\ndef label():\\n    return 'calculator'\\n\", encoding='utf-8'); "
                "Path('tests').mkdir(exist_ok=True); "
                "Path('tests/test_calc.py').write_text("
                "\"import unittest\\nfrom calc import add\\n\\nclass T(unittest.TestCase):\\n    def test_add(self):\\n        self.assertEqual(add(2, 3), 5)\\n\", encoding='utf-8')"
            )
            test_command = f'"{sys.executable}" -m unittest discover -s tests -q'
            rc = main(
                [
                    "guard",
                    "--repo",
                    str(repo),
                    "--test",
                    test_command,
                    "--policy",
                    "strict",
                    "--stability-runs",
                    "1",
                    "--",
                    sys.executable,
                    "-c",
                    agent_script,
                ]
            )
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
