from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_events import continuity_paths, read_project_events
from diffwitness.continuity_state import ensure_state
from diffwitness.idleproof_sidecar import build_portal_snapshot


def run(args: list[str], *, cwd: Path, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
        env=os.environ.copy(),
    )


def git(repo: Path, *args: str) -> str:
    proc = run(["git", *args], cwd=repo)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def entrypoint(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).parent / f"{name}{suffix}"
    value = str(sibling) if sibling.is_file() else shutil.which(name)
    if not value:
        raise AssertionError(f"installed-product test requires {name}")
    return str(Path(value).resolve())


def hook(repo: Path, event: str) -> tuple[str, list[str] | None]:
    payload = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    for entry in payload.get("hooks", {}).get(event, []):
        for item in entry.get("hooks", []):
            command, args = item.get("command"), item.get("args")
            if not isinstance(command, str):
                continue
            if isinstance(args, list) and all(isinstance(value, str) for value in args):
                argv = [str(value) for value in args]
                if "ide-hook" in argv:
                    return command, argv
            if "ide-hook" in command:
                return command, None
    raise AssertionError(f"no DiffWitness hook for Codex {event}")


def run_hook(
    repo: Path,
    invocation: tuple[str, list[str] | None],
    payload: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    command, args = invocation
    common = dict(
        cwd=repo,
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    if args is not None:
        return subprocess.run([command, *args], shell=False, **common)
    return subprocess.run(command, shell=True, **common)


class GuardNativeReverificationTests(unittest.TestCase):
    def test_guard_then_codex_stop_same_tree_keeps_current_proof_coherent(self) -> None:
        dw, idleproof = entrypoint("dw"), entrypoint("idleproof")
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "continuity-reverify@example.test")
            git(repo, "config", "user.name", "Continuity Reverify")
            (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            tests = repo / "tests"
            tests.mkdir()
            (tests / "test_calc.py").write_text(
                "import unittest\nfrom calc import add\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            evidence = subprocess.list2cmdline(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]
            )
            (repo / ".diffwitness.toml").write_text(
                "[diffwitness]\n"
                f"test = {json.dumps(evidence)}\n"
                "stability_runs = 1\nmax_total_seconds = 120\n",
                encoding="utf-8",
            )
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "broken baseline")

            setup = run(
                [dw, "setup", "--agent", "codex", "--idleproof-command", idleproof],
                cwd=repo,
            )
            self.assertEqual(setup.returncode, 0, setup.stderr)

            session = "guard-native-same-tree"
            common: dict[str, object] = {
                "cwd": str(repo),
                "session_id": session,
                "model": "gpt-5.5",
                "permission_mode": "default",
                "transcript_path": str(repo / ".codex" / "transcript.jsonl"),
            }
            started = run_hook(
                repo,
                hook(repo, "SessionStart"),
                {**common, "hook_event_name": "SessionStart", "source": "startup"},
            )
            self.assertEqual(started.returncode, 0, started.stderr)

            prompted = run_hook(
                repo,
                hook(repo, "UserPromptSubmit"),
                {
                    **common,
                    "hook_event_name": "UserPromptSubmit",
                    "turn_id": "turn-1",
                    "prompt": "Fix add so the existing regression test passes",
                },
            )
            self.assertEqual(prompted.returncode, 0, prompted.stderr)

            script = "from pathlib import Path; Path('calc.py').write_text('def add(a, b):\\n    return a + b\\n', encoding='utf-8')"
            guarded = run(
                [
                    dw,
                    "guard",
                    "--repo",
                    str(repo),
                    "--test",
                    evidence,
                    "--policy",
                    "strict",
                    "--stability-runs",
                    "1",
                    "--",
                    sys.executable,
                    "-c",
                    script,
                ],
                cwd=repo,
            )
            self.assertEqual(guarded.returncode, 0, guarded.stderr)
            self.assertNotIn("continuity recording degraded", guarded.stderr.lower())

            envelope_path = repo / ".git" / "diffwitness" / "change-envelope.json"
            guarded_envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            guarded_change = guarded_envelope["change_id"]
            guarded_cert = guarded_envelope["proof"]["certificate_id"]

            stopped = run_hook(
                repo,
                hook(repo, "Stop"),
                {
                    **common,
                    "hook_event_name": "Stop",
                    "turn_id": "turn-1",
                    "stop_hook_active": False,
                    "last_assistant_message": "Implemented the minimal fix.",
                },
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            provider_result = json.loads(stopped.stdout)
            self.assertIn("Proof accepted", provider_result["systemMessage"])
            self.assertNotIn("Continuity DEGRADED", provider_result["systemMessage"])

            final_envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            final_cert = final_envelope["proof"]["certificate_id"]
            self.assertEqual(final_envelope["change_id"], guarded_change)
            self.assertNotEqual(final_cert, guarded_cert)

            events = read_project_events(continuity_paths(repo).events)
            self.assertEqual(sum(event["event_type"] == "change.observed" for event in events), 1)
            proof_ids = [
                event["subject"]["id"]
                for event in events
                if event["event_type"] == "proof.completed"
            ]
            self.assertEqual(proof_ids, [guarded_cert, final_cert])

            db = sqlite3.connect(ensure_state(repo))
            try:
                current = db.execute(
                    "select certificate_id from proofs where change_id=? order by "
                    "case epistemic_status when 'VERIFIED' then 4 when 'OBSERVED' then 3 when 'INFERRED' then 2 else 1 end desc, "
                    "updated_at desc, certificate_id desc limit 1",
                    (guarded_change,),
                ).fetchone()
            finally:
                db.close()
            self.assertIsNotNone(current)
            self.assertEqual(current[0], final_cert)

            snapshot = build_portal_snapshot(repo)
            self.assertEqual(snapshot["changeId"], guarded_change)
            self.assertEqual(snapshot["assurance"]["proof"]["certificateId"], final_cert)


if __name__ == "__main__":
    unittest.main()
