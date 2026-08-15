from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SRC = str(Path(__file__).resolve().parents[1] / "src")


def run(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr + "\n" + proc.stdout)
    return proc


class CliTests(unittest.TestCase):
    def test_prove_writes_v2_certificate_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            run(["git", "init", "-q"], cwd=repo)
            (repo / "mathy.py").write_text("def answer():\n    return 40\n", encoding="utf-8")
            run(["git", "add", "-A"], cwd=repo)
            run([
                "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "baseline"
            ], cwd=repo)
            base = run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
            (repo / "mathy.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
            (repo / "tests").mkdir()
            (repo / "tests" / "test_mathy.py").write_text(
                "import unittest\nfrom mathy import answer\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_answer(self):\n"
                "        self.assertEqual(answer(), 42)\n",
                encoding="utf-8",
            )
            cert = repo / "evidence.json"
            md = repo / "evidence.md"
            cmd = [
                sys.executable, "-m", "diffwitness", "prove",
                "--repo", str(repo),
                "--base", base,
                "--candidate", "WORKTREE",
                "--test", f'"{sys.executable}" -m unittest discover -s tests -q',
                "--stability-runs", "1",
                "--certificate", str(cert),
                "--report", str(md),
                "--require-contrast",
            ]
            proc = run(cmd, cwd=repo, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            report = json.loads(cert.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["summary"]["witnessed"], 1)
            self.assertTrue(report["certificate_id"].startswith("dw2_"))
            self.assertIn("DiffWitness evidence certificate", md.read_text(encoding="utf-8"))

    def test_init_creates_config_and_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            run(["git", "init", "-q"], cwd=repo)
            (repo / "README.md").write_text("x\n", encoding="utf-8")
            run(["git", "add", "-A"], cwd=repo)
            run([
                "git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-q", "-m", "initial"
            ], cwd=repo)
            proc = run([sys.executable, "-m", "diffwitness", "init", "--repo", str(repo), "--test", "pytest -q"], cwd=repo, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn('test = "pytest -q"', (repo / ".diffwitness.toml").read_text(encoding="utf-8"))
            workflow = (repo / ".github" / "workflows" / "diffwitness.yml").read_text(encoding="utf-8")
            self.assertIn("uses: TFourniax/tooltest@main", workflow)
            self.assertIn("strict: false", workflow)


if __name__ == "__main__":
    unittest.main()
