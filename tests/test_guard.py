from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from diffwitness.continuity_events import continuity_paths, read_project_events
from diffwitness.entry import main


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


class PublicGuardTests(unittest.TestCase):
    def test_public_guard_delegates_proven_agent_patch_to_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "public-guard@example.com", cwd=repo)
            git("config", "user.name", "Public Guard Test", cwd=repo)
            (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            git("add", "calc.py", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)

            script = (
                "from pathlib import Path; "
                "Path('calc.py').write_text('def add(a, b):\\n    return a + b\\n', encoding='utf-8'); "
                "Path('tests').mkdir(exist_ok=True); "
                "Path('tests/test_calc.py').write_text("
                "\"import unittest\\nfrom calc import add\\n\\nclass T(unittest.TestCase):\\n    def test_add(self):\\n        self.assertEqual(add(2, 3), 5)\\n\", encoding='utf-8')"
            )
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                rc = main(
                    [
                        "guard",
                        "--repo",
                        str(repo),
                        "--test",
                        command,
                        "--policy",
                        "strict",
                        "--strategy",
                        "auto",
                        "--stability-runs",
                        "1",
                        "--",
                        sys.executable,
                        "-c",
                        script,
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertNotIn("Project continuity recording degraded", stderr.getvalue())

            events = read_project_events(continuity_paths(repo).events)
            self.assertEqual(sum(event["event_type"] == "change.observed" for event in events), 1)
            self.assertEqual(sum(event["event_type"] == "proof.completed" for event in events), 1)
            self.assertEqual(sum(event["event_type"] == "debt.snapshot" for event in events), 1)

    def test_public_guard_preserves_agent_failure_code_without_claiming_proof(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            git("init", "-q", cwd=repo)
            git("config", "user.email", "public-guard@example.com", cwd=repo)
            git("config", "user.name", "Public Guard Test", cwd=repo)
            (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "baseline", cwd=repo)

            rc = main(
                [
                    "guard",
                    "--repo",
                    str(repo),
                    "--test",
                    f'"{sys.executable}" -c "raise SystemExit(0)"',
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(7)",
                ]
            )
            self.assertEqual(rc, 7)


if __name__ == "__main__":
    unittest.main()
