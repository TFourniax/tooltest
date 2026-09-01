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


def module(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, "-m", "diffwitness.entry", *args], cwd=repo, check=check)


def main() -> int:
    """Exercise the installed public product through a real before/after repository journey.

    This intentionally uses only Python stdlib + Git so the same smoke can run on Linux, macOS and
    Windows after installing the wheel that would actually be distributed to users. The journey now
    covers the platform contract as well as proof: one exact change is proved, debt-accounted, and
    bound into a change-envelope using only the installed artifact. It also verifies fail-closed
    behavior when an otherwise well-formed evidence file is rebound to a different candidate tree.
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
        guard = module(
            repo,
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

        debt_json = root / "debt.json"
        debt = module(
            repo,
            "debt",
            "--repo",
            str(repo),
            "--base",
            "HEAD",
            "--candidate",
            "WORKTREE",
            "--certificate",
            str(certificate),
            "--json",
            str(debt_json),
            "--no-record",
            "--ignore-budget",
        )
        if not debt_json.exists():
            raise RuntimeError(f"debt command did not write its machine report:\n{debt.stdout}")
        debt_payload = json.loads(debt_json.read_text(encoding="utf-8"))
        debt_report = debt_payload.get("report") or {}
        if debt_report.get("schema_version") != "debt-report-1":
            raise RuntimeError(f"unexpected debt report schema: {debt_report.get('schema_version')!r}")

        envelope_path = root / "change-envelope.json"
        envelope_run = module(
            repo,
            "envelope",
            "--repo",
            str(repo),
            "--base",
            "HEAD",
            "--candidate",
            "WORKTREE",
            "--proof",
            str(certificate),
            "--debt",
            str(debt_json),
            "--out",
            str(envelope_path),
        )
        if not envelope_path.exists():
            raise RuntimeError(f"envelope command did not write its output:\n{envelope_run.stdout}")
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        if envelope.get("schema_version") != "change-envelope-1":
            raise RuntimeError(f"unexpected envelope schema: {envelope.get('schema_version')!r}")
        if not str(envelope.get("change_id") or "").startswith("dwchg_"):
            raise RuntimeError(f"invalid change id: {envelope.get('change_id')!r}")
        if (envelope.get("proof") or {}).get("certificate_id") != payload.get("certificate_id"):
            raise RuntimeError("change envelope lost or changed the exact proof certificate id")
        if (envelope.get("proof") or {}).get("accepted") is not True:
            raise RuntimeError(f"accepted Guard proof was not accepted in envelope: {envelope.get('proof')!r}")
        if (envelope.get("debt") or {}).get("points") != (debt_report.get("summary") or {}).get("points"):
            raise RuntimeError("change envelope debt points differ from the exact Debt Ledger report")
        if (envelope.get("base") or {}).get("tree") != (payload.get("base") or {}).get("tree"):
            raise RuntimeError("envelope base tree differs from proof base tree")
        if (envelope.get("candidate") or {}).get("tree") != (payload.get("candidate") or {}).get("tree"):
            raise RuntimeError("envelope candidate tree differs from proof candidate tree")
        if (envelope.get("privacy") or {}).get("code_uploaded") is not False:
            raise RuntimeError("local change envelope unexpectedly claims source upload")

        # A stale/rebound Debt report must never be silently correlated to the accepted proof.
        stale_debt = root / "stale-debt.json"
        stale_payload = json.loads(debt_json.read_text(encoding="utf-8"))
        stale_payload["report"]["candidate_tree"] = "0" * len(str(debt_report.get("candidate_tree") or "0" * 40))
        stale_debt.write_text(json.dumps(stale_payload), encoding="utf-8")
        rejected_debt = module(
            repo,
            "envelope",
            "--repo",
            str(repo),
            "--base",
            "HEAD",
            "--candidate",
            "WORKTREE",
            "--proof",
            str(certificate),
            "--debt",
            str(stale_debt),
            "--out",
            str(root / "must-not-exist.json"),
            check=False,
        )
        if rejected_debt.returncode != 2 or "candidate tree does not match" not in rejected_debt.stdout:
            raise RuntimeError(f"stale Debt report did not fail closed:\n{rejected_debt.stdout}")
        if (root / "must-not-exist.json").exists():
            raise RuntimeError("failed change-envelope validation still wrote an output artifact")

        # Integrity tampering must also be rejected before correlation.
        stale_proof = root / "tampered-proof.json"
        tampered = json.loads(certificate.read_text(encoding="utf-8"))
        tampered["summary"]["witnessed"] = int(tampered["summary"].get("witnessed", 0)) + 1
        stale_proof.write_text(json.dumps(tampered), encoding="utf-8")
        rejected_proof = module(
            repo,
            "envelope",
            "--repo",
            str(repo),
            "--base",
            "HEAD",
            "--candidate",
            "WORKTREE",
            "--proof",
            str(stale_proof),
            "--out",
            str(root / "must-not-exist-proof.json"),
            check=False,
        )
        if rejected_proof.returncode != 2 or "integrity mismatch" not in rejected_proof.stdout:
            raise RuntimeError(f"tampered proof certificate did not fail closed:\n{rejected_proof.stdout}")
        if (root / "must-not-exist-proof.json").exists():
            raise RuntimeError("failed proof integrity validation still wrote an envelope")

        run([sys.executable, "-m", "unittest", "-q"], cwd=repo)
        print(
            "alpha smoke passed:",
            payload.get("certificate_id"),
            envelope.get("change_id"),
            f"witnessed={summary.get('witnessed', 0)}",
            f"debt={envelope.get('debt', {}).get('points', 0)}",
            "stale-evidence=fail-closed",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
