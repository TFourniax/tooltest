from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from diffwitness.entry import main as dw_main


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
    ).stdout.strip()


def make_repair_repo(root: Path) -> tuple[Path, str, str]:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Local Engine Gate Test")
    git(repo, "config", "user.email", "local-engine-gate@localhost")
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_calc.py").write_text(
        "import unittest\nfrom calc import add\n\n"
        "class CalcTest(unittest.TestCase):\n"
        "    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "buggy base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    git(repo, "add", "calc.py")
    git(repo, "commit", "-qm", "fix add")
    candidate = git(repo, "rev-parse", "HEAD")
    return repo, base, candidate


def write_planner(root: Path) -> Path:
    script = root / "private_planner.py"
    script.write_text(textwrap.dedent("""
        import hashlib, json, sys

        CAPABILITIES = {
            "schema_version": "engine-capabilities-1",
            "engine": {"name": "private-gate-fixture", "version": "0.1.0a1"},
            "protocol": {"request": "engine-request-1", "plan": "engine-plan-1"},
            "limits": {"request_bytes": 2097152, "mutations": 5000},
            "privacy": {
                "accepts_embedded_source": False,
                "supports_metadata_only": True,
                "supports_local_candidate_object_reads": True,
            },
            "authority": {
                "advisory_only": True,
                "executes_evidence_commands": False,
                "writes_target_repository": False,
            },
        }

        if "--capabilities" in sys.argv:
            print(json.dumps(CAPABILITIES, sort_keys=True, separators=(",", ":")))
            raise SystemExit(0)

        request = json.load(sys.stdin)
        canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        ids = [item["id"] for item in request["mutations"]]
        print(json.dumps({
            "schema_version": "engine-plan-1",
            "request_id": request["request_id"],
            "request_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "engine": {"name": "private-gate-fixture", "version": "0.1.0a1"},
            "ordered_mutation_ids": ids,
            "partitions": [[item] for item in ids],
            "interaction_pairs": [],
            "diagnostics": {"reason_codes": ["fixture-local-profile"]},
        }, sort_keys=True, separators=(",", ":")))
    """), encoding="utf-8")
    return script


class LocalEngineGateTests(unittest.TestCase):
    def test_real_gate_consumes_git_local_private_plan_but_public_runner_owns_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo, base, candidate = make_repair_repo(root)
            planner = write_planner(root)

            enable_out = io.StringIO()
            with contextlib.redirect_stdout(enable_out):
                rc = dw_main([
                    "engine", "--repo", str(repo), "enable",
                    "--command", sys.executable, "--arg", str(planner),
                ])
            self.assertEqual(rc, 0, enable_out.getvalue())
            self.assertEqual(git(repo, "status", "--porcelain=v1", "--untracked-files=all"), "")

            certificate = root / "proof.json"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = dw_main([
                    "gate", "--repo", str(repo),
                    "--base", base, "--candidate", candidate,
                    "--test", f'{sys.executable} -m unittest discover -s tests -q',
                    "--strategy", "adaptive", "--adaptive-budget", "10",
                    "--stability-runs", "1", "--no-github-actions",
                    "--certificate", str(certificate),
                ])
            text = out.getvalue()
            self.assertEqual(rc, 0, text)
            self.assertIn("DiffWitness advisory planner: private-gate-fixture 0.1.0a1", text)
            self.assertIn("DiffWitness Gate accepted", text)
            proof = json.loads(certificate.read_text(encoding="utf-8"))
            self.assertEqual(proof["planning"]["mode"], "advisory")
            self.assertEqual(proof["planning"]["engine"]["name"], "private-gate-fixture")
            self.assertEqual(proof["planning"]["authority"], "advisory-only")
            self.assertTrue(proof["one_minimal"])
            self.assertEqual(len(proof["core_mutation_ids"]), 1)
            self.assertEqual(git(repo, "status", "--porcelain=v1", "--untracked-files=all"), "")


if __name__ == "__main__":
    unittest.main()
