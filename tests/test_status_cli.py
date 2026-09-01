from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.status_cli import build_project_status, render_project_status, status_cli


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


class ProjectStatusTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="dw-status-"))
        _git(root, "init")
        _git(root, "config", "user.email", "diffwitness@example.invalid")
        _git(root, "config", "user.name", "DiffWitness Tests")
        (root / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8"
        )
        (root / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
        (root / "test_app.py").write_text(
            "from app import answer\n\ndef test_answer():\n    assert answer() == 42\n",
            encoding="utf-8",
        )
        _git(root, "add", ".")
        _git(root, "commit", "-m", "initial")
        return root

    def test_clean_repo_produces_bounded_navigation_contract(self) -> None:
        repo = self.make_repo()
        value = build_project_status(repo)
        self.assertEqual(value["schema"], "diffwitness.project-status.v1")
        self.assertTrue(value["evidence"]["ready"])
        self.assertFalse(value["working_tree"]["dirty"])
        self.assertEqual(value["debt"]["open_obligations"], 0)
        self.assertEqual(value["debt"]["points"], 0)
        self.assertEqual(value["next_actions"][0]["kind"], "guard-next-change")
        self.assertFalse(value["privacy"]["source_code_included"])
        self.assertFalse(value["privacy"]["raw_diff_included"])
        self.assertIn("not a proof", value["non_claim"].lower())

    def test_dirty_repo_points_to_verification_without_embedding_source(self) -> None:
        repo = self.make_repo()
        (repo / "app.py").write_text("def answer():\n    return 43\n", encoding="utf-8")
        value = build_project_status(repo)
        self.assertTrue(value["working_tree"]["dirty"])
        self.assertEqual(value["working_tree"]["changed_file_count"], 1)
        self.assertEqual(value["working_tree"]["files"], ["app.py"])
        actions = [item["kind"] for item in value["next_actions"]]
        self.assertIn("verify-change", actions)
        encoded = json.dumps(value)
        self.assertNotIn("return 43", encoded)
        self.assertNotIn("return 42", encoded)

    def test_guided_and_technical_views_share_the_exact_same_status_model(self) -> None:
        repo = self.make_repo()
        (repo / "app.py").write_text("def answer():\n    return 43\n", encoding="utf-8")
        value = build_project_status(repo)
        guided = render_project_status(value, view="guided")
        technical = render_project_status(value, view="technical")
        self.assertIn("GUIDED VIEW", guided)
        self.assertIn("A change is waiting to be verified", guided)
        self.assertNotIn("Last change   ", guided)
        self.assertIn("TECHNICAL VIEW", technical)
        self.assertIn("Working tree  1 changed file(s)", technical)
        self.assertEqual(value["schema"], "diffwitness.project-status.v1")

    def test_json_cli_is_machine_readable_non_mutating_and_view_invariant(self) -> None:
        repo = self.make_repo()
        before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        outputs: list[dict[str, object]] = []
        for view in ("guided", "technical"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = status_cli(["--repo", str(repo), "--view", view, "--json"])
            self.assertEqual(rc, 0)
            outputs.append(json.loads(output.getvalue()))
        after = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(before, after)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0]["schema"], "diffwitness.project-status.v1")


if __name__ == "__main__":
    unittest.main()
