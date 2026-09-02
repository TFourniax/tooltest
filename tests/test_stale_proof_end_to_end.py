from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.entry import main


class StaleProofEndToEndTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return proc.stdout.strip()

    def cli_json(self, args: list[str]) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main(args)
        return rc, json.loads(out.getvalue())

    def test_real_accepted_proof_becomes_historical_after_failing_worktree_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "stale-proof@example.test")
            self.git(repo, "config", "user.name", "Stale Proof E2E")
            (repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            (repo / "test_calculator.py").write_text(
                "import unittest\nfrom calculator import add\n\n"
                "class CalculatorTest(unittest.TestCase):\n"
                "    def test_add(self): self.assertEqual(add(2, 3), 5)\n\n"
                "if __name__ == '__main__': unittest.main()\n",
                encoding="utf-8",
            )
            test_command = f'"{sys.executable}" -m unittest -q'
            (repo / ".diffwitness.toml").write_text(
                "[diffwitness]\n"
                f"test = {json.dumps(test_command)}\n"
                "stability_runs = 1\n"
                "max_total_seconds = 120\n",
                encoding="utf-8",
            )
            self.git(repo, "add", "-A")
            self.git(repo, "commit", "-qm", "broken baseline")

            baseline = subprocess.run(
                [sys.executable, "-m", "unittest", "-q"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(baseline.returncode, 0)

            agent_script = (
                "from pathlib import Path; "
                "Path('calculator.py').write_text('def add(a, b):\\n    return a + b\\n', encoding='utf-8')"
            )
            guard_out = io.StringIO()
            with contextlib.redirect_stdout(guard_out):
                guard_rc = main(
                    [
                        "guard",
                        "--repo",
                        str(repo),
                        "--policy",
                        "strict",
                        "--strategy",
                        "auto",
                        "--stability-runs",
                        "1",
                        "--",
                        sys.executable,
                        "-c",
                        agent_script,
                    ]
                )
            self.assertEqual(guard_rc, 0, guard_out.getvalue())

            envelope = json.loads((repo / ".git" / "diffwitness" / "change-envelope.json").read_text(encoding="utf-8"))
            self.assertTrue(envelope["proof"]["accepted"])
            self.assertEqual(envelope["proof"]["claim"], "causal")
            proven_change_id = envelope["change_id"]

            self.git(repo, "add", "calculator.py")
            self.git(repo, "commit", "-qm", "fix: correct addition")
            current_rc, current = self.cli_json(["explain", "--repo", str(repo), "--json"])
            self.assertEqual(current_rc, 0, current)
            self.assertEqual(current["change_id"], proven_change_id)
            self.assertEqual(current["confidence"], "verified")
            self.assertEqual(current["coverage"]["freshness"], "current")
            self.assertTrue(current["coverage"]["current_worktree_covered"])

            # Reproduce the human P0 exactly: drift away from the proven tree into code whose tests fail.
            (repo / "calculator.py").write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")
            failing = subprocess.run(
                [sys.executable, "-m", "unittest", "-q"],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(failing.returncode, 0)

            stale_rc, stale = self.cli_json(["explain", "--repo", str(repo), "--json"])
            self.assertEqual(stale_rc, 0, stale)
            self.assertEqual(stale["change_id"], proven_change_id)
            self.assertTrue(stale["proof"]["accepted"], "historical certificate must remain historically valid")
            self.assertEqual(stale["proof"]["scope"], "historical")
            self.assertEqual(stale["confidence"], "historical")
            self.assertEqual(stale["coverage"]["scope"], "historical")
            self.assertEqual(stale["coverage"]["freshness"], "stale")
            self.assertFalse(stale["coverage"]["current_worktree_covered"])
            self.assertIn("NOT covered", stale["why_it_matters"][0])
            self.assertIn("Verify the current worktree", stale["verify_next"][0])

            session_rc, session = self.cli_json(
                ["explain", "--repo", str(repo), "--engine", "agent-session", "--json"]
            )
            self.assertEqual(session_rc, 0, session)
            facts = session["context"]["facts"]
            self.assertEqual(facts["confidence"], "historical")
            self.assertFalse(facts["coverage"]["current_worktree_covered"])
            self.assertIn("never describe a historical accepted Proof", session["context"]["role"])

            gate_out = io.StringIO()
            with contextlib.redirect_stdout(gate_out):
                gate_rc = main(
                    [
                        "gate",
                        "--repo",
                        str(repo),
                        "--candidate",
                        "WORKTREE",
                        "--stability-runs",
                        "1",
                    ]
                )
            self.assertNotEqual(gate_rc, 0, "Gate accepted a current worktree whose authoritative test fails")

            # Restoring the exact proven committed tree must make the same historical certificate current again.
            self.git(repo, "restore", "calculator.py")
            restored_rc, restored = self.cli_json(["explain", "--repo", str(repo), "--json"])
            self.assertEqual(restored_rc, 0, restored)
            self.assertEqual(restored["confidence"], "verified")
            self.assertEqual(restored["coverage"]["freshness"], "current")
            self.assertTrue(restored["coverage"]["current_worktree_covered"])


if __name__ == "__main__":
    unittest.main()
