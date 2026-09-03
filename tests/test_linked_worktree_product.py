from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_budget import ledger_path, merged_debt_config
from diffwitness.gitops import git_metadata_path
from diffwitness.ide_handoff import finalize_ide_session
from diffwitness.ide_plugin import session_start
from diffwitness.idleproof_explanation import load_current_explanation
from diffwitness.native_activation import native_activation_summary
from diffwitness.setup import _persist_setup_scope
from diffwitness.status_cli import build_project_status
from diffwitness.view_mode import get_view_mode, set_view_mode


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


class LinkedWorktreeProductTests(unittest.TestCase):
    def test_native_proof_debt_understand_and_status_use_real_worktree_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            main = root / "main"
            linked = root / "linked"
            main.mkdir()
            _git(main, "init", "-q")
            _git(main, "config", "user.email", "linked@example.test")
            _git(main, "config", "user.name", "Linked Worktree Test")
            (main / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            tests = main / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text(
                "import unittest\nfrom app import add\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            python = sys.executable.replace("\\", "\\\\")
            (main / ".diffwitness.toml").write_text(
                '[diffwitness]\n'
                f'test = "{python} -m unittest discover -s tests -q"\n'
                "stability_runs = 1\n"
                "max_total_seconds = 120\n",
                encoding="utf-8",
            )
            _git(main, "add", "-A")
            _git(main, "commit", "-qm", "buggy baseline")
            _git(main, "worktree", "add", "-q", "-b", "linked-product-test", str(linked))

            try:
                self.assertTrue((linked / ".git").is_file())
                self.assertEqual(set_view_mode(linked, "technical"), "technical")
                self.assertEqual(get_view_mode(linked), "technical")
                _persist_setup_scope(linked, ["codex"])

                session_id = "linked-native-codex"
                session_start(
                    {
                        "cwd": str(linked),
                        "session_id": session_id,
                        "source": "startup",
                        "provider": "codex",
                    }
                )
                activation = native_activation_summary(linked, ["codex"])
                self.assertEqual(activation["observedAdapters"], ["codex"])

                (linked / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
                result = finalize_ide_session(
                    {
                        "cwd": str(linked),
                        "session_id": session_id,
                        "source": "startup",
                        "provider": "codex",
                    }
                )
                self.assertNotIn("decision", result, result)
                self.assertIn("Proof accepted", result["systemMessage"])

                state = git_metadata_path(linked, "diffwitness")
                envelope_path = state / "change-envelope.json"
                self.assertTrue(envelope_path.is_file())
                envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
                self.assertTrue(envelope["proof"]["accepted"])
                self.assertEqual(
                    ledger_path(linked, merged_debt_config(None)),
                    state / "debt-ledger.jsonl",
                )

                status = build_project_status(linked)
                self.assertEqual(status["current_worktree_verification"]["status"], "accepted")
                self.assertEqual(status["setup"]["native_adapters"], ["codex"])
                explanation = load_current_explanation(linked)
                self.assertEqual(explanation["coverage"]["freshness"], "current")

                main_state = git_metadata_path(main, "diffwitness")
                self.assertFalse((main_state / "ui-preferences.json").exists())
                self.assertFalse((main_state / "change-envelope.json").exists())
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(linked)],
                    cwd=main,
                    text=True,
                    capture_output=True,
                    check=False,
                )


if __name__ == "__main__":
    unittest.main()
