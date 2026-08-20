from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stdout}"
        )
    return proc


def git(repo: Path, *args: str) -> str:
    return run(["git", *args], cwd=repo).stdout.strip()


def main() -> int:
    """Exercise the installed public product through a real before/after repository journey.

    This intentionally uses only Python stdlib + Git so the same smoke can run on Linux, macOS and
    Windows after installing the wheel that would actually be distributed to users.
    """
    with tempfile.TemporaryDirectory(prefix="diffwitness-alpha-smoke-") as raw:
        root = Path(raw)
        repo = root / "consumer"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "alpha-smoke@diffwitness.local")
        git(repo, "config", "user.name", "DiffWitness Alpha Smoke")

        (repo / "calc.py").write_text(
            "def add(a, b):\n    return 0\n",
            encoding="utf-8",
        )
        (repo / "test_calc.py").write_text(
            "import unittest\n"
            "from calc import add\n\n"
            "class CalcTest(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(1, 1), 2)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        git(repo, "add", "calc.py", "test_calc.py")
        git(repo, "commit", "-qm", "failing baseline")

        agent = root / "agent_fix.py"
        agent.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).write_text('def add(a, b):\\n    return a + b\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        certificate = root / "proof.json"
        evidence = f'"{sys.executable}" -m unittest -q'
        guard = run(
            [
                sys.executable,
                "-m",
                "diffwitness.entry",
                "guard",
                "--repo",
                str(repo),
                "--test",
                evidence,
                "--policy",
                "strict",
                "--stability-runs",
                "2",
                "--strategy",
                "exhaustive",
                "--certificate",
                str(certificate),
                "--",
                sys.executable,
                str(agent),
                str(repo / "calc.py"),
            ],
            cwd=repo,
        )
        if "PROOF ACCEPTED" not in guard.stdout:
            raise RuntimeError(f"guard did not report proof acceptance:\n{guard.stdout}")
        if not certificate.exists():
            raise RuntimeError("guard accepted the change without writing the requested certificate")
        payload = json.loads(certificate.read_text(encoding="utf-8"))
        if payload.get("contrast") != "base-fail_candidate-pass":
            raise RuntimeError(f"unexpected proof contrast: {payload.get('contrast')!r}")
        summary = payload.get("summary") or {}
        if summary.get("witnessed", 0) < 1 or summary.get("inconclusive", 0):
            raise RuntimeError(f"unexpected certificate summary: {summary!r}")

        # The candidate itself must still pass independently of the certificate-producing process.
        run([sys.executable, "-m", "unittest", "-q"], cwd=repo)
        print(
            "alpha smoke passed:",
            payload.get("certificate_id"),
            f"witnessed={summary.get('witnessed', 0)}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
