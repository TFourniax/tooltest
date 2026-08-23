from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_events import append_project_event, continuity_paths
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

    def run_hook(self, repo: Path, payload: dict) -> subprocess.CompletedProcess[str]:
        project_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PLUGIN_ROOT"] = str(project_root)
        return subprocess.run(
            [sys.executable, str(project_root / "integrations" / "plugin_hook.py"), "user-prompt-submit"],
            cwd=repo,
            env=env,
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
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


if __name__ == "__main__":
    unittest.main()
