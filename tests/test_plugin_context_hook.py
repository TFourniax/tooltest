from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.continuity_events import append_project_event, continuity_paths
from diffwitness.ide_handoff import finalize_ide_session
from diffwitness.proof_cli import _state_path
from diffwitness.structure_provider import component_id_for_path


class PluginContextHookTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "hook@example.test")
        self.git(repo, "config", "user.name", "Hook Test")
        (repo / "payments.py").write_text("def refund(amount):\n    return amount\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        append_project_event(
            repo=repo,
            event_type="objective.declared",
            subject={"id": "OBJ-REFUND", "kind": "objective", "label": "Support safe partial refunds"},
            epistemic_status="DECLARED",
            payload={"priority": "high"},
            relations=[
                {
                    "predicate": "served_by",
                    "target": {"id": component_id_for_path("payments.py"), "kind": "component", "label": "payments.py"},
                    "epistemic_status": "DECLARED",
                    "metadata": {"path": "payments.py"},
                }
            ],
            provenance={"producer": "test", "source": "unit"},
            actor={"kind": "human", "id": "test"},
        )
        return repo

    def run_hook(self, repo: Path, payload: dict, command: str = "user-prompt-submit", timeout: float = 10) -> subprocess.CompletedProcess[str]:
        project_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PLUGIN_ROOT"] = str(project_root)
        return subprocess.run(
            [sys.executable, str(project_root / "integrations" / "plugin_hook.py"), command],
            cwd=repo,
            env=env,
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )

    def test_prompt_submit_injects_bounded_epistemic_context_without_persisting_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            prompt = "Implement partial refunds in payments while preserving idempotency"
            before = continuity_paths(repo).events.read_bytes()
            proc = self.run_hook(
                repo,
                {
                    "session_id": "session-1",
                    "cwd": str(repo),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": prompt,
                },
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            value = json.loads(proc.stdout)
            output = value["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "UserPromptSubmit")
            context = output["additionalContext"]
            self.assertLessEqual(len(context), 6500)
            self.assertIn("OBJ-REFUND", context)
            self.assertIn("DECLARED", context)
            self.assertIn("executed DiffWitness evidence remains authoritative", context)
            self.assertNotIn("change-proof: dw guard", context)
            self.assertEqual(continuity_paths(repo).events.read_bytes(), before)
            self.assertNotIn(prompt, continuity_paths(repo).events.read_text(encoding="utf-8"))

    def test_prompt_submit_fails_open_outside_git_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proc = self.run_hook(
                root,
                {
                    "session_id": "session-2",
                    "cwd": str(root),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Do something",
                },
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")

    def test_prompt_submit_without_text_is_noop(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            proc = self.run_hook(
                repo,
                {"session_id": "session-3", "cwd": str(repo), "hook_event_name": "UserPromptSubmit", "prompt": ""},
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")

    def test_native_session_stop_converges_on_proof_debt_envelope_and_continuity_without_guard_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "native-project"
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "native@example.test")
            self.git(repo, "config", "user.name", "Native IDE Test")
            (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            tests = repo / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text(
                "import unittest\nfrom app import add\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            (repo / ".diffwitness.toml").write_text(
                '[diffwitness]\n'
                f'test = "{sys.executable.replace(chr(92), chr(92) * 2)} -m unittest discover -s tests -q"\n'
                'stability_runs = 1\n'
                'max_total_seconds = 120\n',
                encoding="utf-8",
            )
            self.git(repo, "add", "-A")
            self.git(repo, "commit", "-qm", "buggy baseline")

            session_id = "native-session"
            started = self.run_hook(
                repo,
                {"session_id": session_id, "cwd": str(repo), "hook_event_name": "SessionStart"},
                command="session-start",
            )
            self.assertEqual(started.returncode, 0, started.stderr)

            (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            stopped = self.run_hook(
                repo,
                {"session_id": session_id, "cwd": str(repo), "hook_event_name": "Stop", "source": "claude-code"},
                command="session-stop",
                timeout=180,
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            result = json.loads(stopped.stdout.splitlines()[-1])
            self.assertNotIn("decision", result, result)
            self.assertIn("Proof accepted", result["systemMessage"])
            self.assertIn("Debt +", result["systemMessage"])
            self.assertIn("Continuity", result["systemMessage"])

            envelope_path = repo / ".git" / "diffwitness" / "change-envelope.json"
            self.assertTrue(envelope_path.is_file())
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            self.assertRegex(envelope["change_id"], r"^dwchg_[a-f0-9]{24}$")
            self.assertTrue(envelope["proof"]["accepted"])
            self.assertIsInstance(envelope["debt"]["points"], int)
            self.assertIsInstance(envelope["debt"]["open_lineages"], list)

            events = continuity_paths(repo).events.read_text(encoding="utf-8")
            self.assertIn('"event_type":"change.observed"', events)
            self.assertIn('"event_type":"proof.completed"', events)
            self.assertIn('"event_type":"debt.snapshot"', events)

    def test_native_handoff_blocks_an_intact_but_canonically_unaccepted_proof_before_debt_or_continuity(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "native-unaccepted"
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "native@example.test")
            self.git(repo, "config", "user.name", "Native IDE Test")
            (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            tests = repo / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text(
                "import unittest\nfrom app import add\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            (repo / ".diffwitness.toml").write_text(
                '[diffwitness]\n'
                f'test = "{sys.executable.replace(chr(92), chr(92) * 2)} -m unittest discover -s tests -q"\n'
                'stability_runs = 1\n',
                encoding="utf-8",
            )
            self.git(repo, "add", "-A")
            self.git(repo, "commit", "-qm", "green baseline")

            session_id = "native-unaccepted-session"
            base = self.git(repo, "rev-parse", "HEAD")
            state_path = _state_path(repo, session_id)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"base": base, "retries": 0}), encoding="utf-8")
            (repo / "app.py").write_text("def add(a, b):\n    return sum((a, b))\n", encoding="utf-8")

            report = {
                "schema_version": 2,
                "certificate_id": "dwcert_test",
                "contrast": "base-pass_candidate-pass",
                "candidate_run": {"classification": "stable-pass"},
                "summary": {"unwitnessed": 1, "inconclusive": 0, "surplus_candidate_hunks": 0},
            }
            with mock.patch("diffwitness.ide_handoff._run_proof", return_value=(0, report, "proof policy satisfied")), mock.patch(
                "diffwitness.ide_handoff._validate_generated_certificate", return_value=None
            ), mock.patch("diffwitness.ide_handoff.scan_change") as scan_change:
                result = finalize_ide_session(
                    {"session_id": session_id, "cwd": str(repo), "source": "claude-code"},
                    repo=repo,
                )

            self.assertEqual(result["decision"], "block", result)
            self.assertIn("not accepted", result["systemMessage"])
            scan_change.assert_not_called()
            self.assertFalse((repo / ".git" / "diffwitness" / "change-envelope.json").exists())
            self.assertFalse(continuity_paths(repo).events.exists())


if __name__ == "__main__":
    unittest.main()
