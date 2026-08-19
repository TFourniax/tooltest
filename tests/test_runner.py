from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.analysis import _run_variant_repeated
from diffwitness.gitops import detached_worktree
from diffwitness.models import CommandResult
from diffwitness.runner import classify_runs


def r(code: int | None, *, timeout: bool = False) -> CommandResult:
    return CommandResult(returncode=code, duration_s=0.01, timed_out=timeout)


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


class RunnerTests(unittest.TestCase):
    def test_classifies_stability(self) -> None:
        self.assertEqual(classify_runs([r(0), r(0)]), "stable-pass")
        self.assertEqual(classify_runs([r(1), r(2)]), "stable-fail")
        self.assertEqual(classify_runs([r(0), r(1)]), "flaky")
        self.assertEqual(classify_runs([r(None, timeout=True), r(0)]), "timeout")

    def test_proof_repetitions_remove_ignored_state_between_runs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "stability@example.com")
            git(repo, "config", "user.name", "Stability Test")
            (repo / ".gitignore").write_text("state.flag\n", encoding="utf-8")
            (repo / "check.py").write_text(
                "from pathlib import Path\n"
                "p = Path('state.flag')\n"
                "raise SystemExit(1 if p.exists() else (p.write_text('dirty', encoding='utf-8') and 0))\n",
                encoding="utf-8",
            )
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
            head = git(repo, "rev-parse", "HEAD")

            with detached_worktree(repo, head, "stability-state") as sandbox:
                runs = _run_variant_repeated(
                    f'"{sys.executable}" check.py',
                    source_repo=repo,
                    sandbox=sandbox,
                    timeout=30,
                    repetitions=2,
                    prepare_command=None,
                    shared_paths=[],
                )
            self.assertEqual(runs.classification, "stable-pass")
            self.assertEqual([run.returncode for run in runs.runs], [0, 0])

    def test_prepare_is_recreated_before_every_repetition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "prepare@example.com")
            git(repo, "config", "user.name", "Prepare Test")
            (repo / ".gitignore").write_text("prepared.flag\n", encoding="utf-8")
            (repo / "check.py").write_text(
                "from pathlib import Path\n"
                "p = Path('prepared.flag')\n"
                "ok = p.exists()\n"
                "if ok: p.unlink()\n"
                "raise SystemExit(0 if ok else 1)\n",
                encoding="utf-8",
            )
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "base")
            head = git(repo, "rev-parse", "HEAD")
            prepare = f'"{sys.executable}" -c "from pathlib import Path; Path(\'prepared.flag\').write_text(\'ready\', encoding=\'utf-8\')"'

            with detached_worktree(repo, head, "stability-prepare") as sandbox:
                runs = _run_variant_repeated(
                    f'"{sys.executable}" check.py',
                    source_repo=repo,
                    sandbox=sandbox,
                    timeout=30,
                    repetitions=2,
                    prepare_command=prepare,
                    shared_paths=[],
                )
            self.assertEqual(runs.classification, "stable-pass")
            self.assertEqual([run.returncode for run in runs.runs], [0, 0])


if __name__ == "__main__":
    unittest.main()