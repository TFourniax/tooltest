from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def run(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stdout}")
    return proc


def git(repo: Path, *args: str) -> str:
    return run(["git", *args], cwd=repo).stdout.strip()


def dw(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, "-m", "diffwitness.entry", *args], cwd=repo, check=check)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="diffwitness-engine-artifact-") as raw:
        root = Path(raw)
        repo = root / "consumer"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Engine Artifact Smoke")
        git(repo, "config", "user.email", "engine-artifact@localhost")
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
        git(repo, "commit", "-qm", "fix")
        candidate = git(repo, "rev-parse", "HEAD")

        planner = root / "planner.py"
        planner.write_text(textwrap.dedent("""
            import hashlib, json, sys
            caps={
              "schema_version":"engine-capabilities-1",
              "engine":{"name":"artifact-private-fixture","version":"0.1.0a1"},
              "protocol":{"request":"engine-request-1","plan":"engine-plan-1"},
              "limits":{"request_bytes":2097152,"mutations":5000},
              "privacy":{"accepts_embedded_source":False,"supports_metadata_only":True,"supports_local_candidate_object_reads":True},
              "authority":{"advisory_only":True,"executes_evidence_commands":False,"writes_target_repository":False},
            }
            if "--capabilities" in sys.argv:
                print(json.dumps(caps,sort_keys=True,separators=(",",":")))
                raise SystemExit(0)
            request=json.load(sys.stdin)
            canonical=json.dumps(request,sort_keys=True,separators=(",",":"),ensure_ascii=False)
            ids=[item["id"] for item in request["mutations"]]
            print(json.dumps({
              "schema_version":"engine-plan-1",
              "request_id":request["request_id"],
              "request_digest":hashlib.sha256(canonical.encode()).hexdigest(),
              "engine":{"name":"artifact-private-fixture","version":"0.1.0a1"},
              "ordered_mutation_ids":ids,
              "partitions":[[item] for item in ids],
              "interaction_pairs":[],
              "diagnostics":{"reason_codes":["artifact-smoke"]},
            },sort_keys=True,separators=(",",":")))
        """), encoding="utf-8")

        enabled = dw(repo, "engine", "--repo", str(repo), "enable", "--command", sys.executable, "--arg", str(planner))
        if "Activated artifact-private-fixture" not in enabled.stdout:
            raise RuntimeError(f"installed artifact did not activate local private engine:\n{enabled.stdout}")
        if git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("Git-local engine activation polluted the consumer worktree")

        status = json.loads(dw(repo, "engine", "--repo", str(repo), "status", "--json").stdout)
        if status.get("source") != "local" or (status.get("engine") or {}).get("name") != "artifact-private-fixture":
            raise RuntimeError(f"installed artifact did not resolve local engine profile: {status!r}")

        certificate = root / "proof.json"
        gate = dw(
            repo,
            "gate", "--repo", str(repo), "--base", base, "--candidate", candidate,
            "--test", f'{sys.executable} -m unittest discover -s tests -q',
            "--strategy", "adaptive", "--adaptive-budget", "10", "--stability-runs", "1",
            "--no-github-actions", "--certificate", str(certificate),
        )
        if "DiffWitness advisory planner: artifact-private-fixture 0.1.0a1" not in gate.stdout:
            raise RuntimeError(f"installed Gate did not consume the local private plan:\n{gate.stdout}")
        proof = json.loads(certificate.read_text(encoding="utf-8"))
        if (proof.get("planning") or {}).get("authority") != "advisory-only":
            raise RuntimeError(f"private planning authority boundary missing from installed proof: {proof.get('planning')!r}")
        if not proof.get("one_minimal"):
            raise RuntimeError("public evidence runner did not independently establish a 1-minimal proof")

        dw(repo, "engine", "--repo", str(repo), "disable")
        community = json.loads(dw(repo, "engine", "--repo", str(repo), "status", "--json").stdout)
        if community.get("source") != "community":
            raise RuntimeError(f"installed artifact did not return to Community planner: {community!r}")
        if git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("engine lifecycle changed tracked/untracked consumer software")

        print("private-engine artifact smoke passed: local activation -> adaptive Gate -> public proof -> Community disable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
