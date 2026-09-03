from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.proof_cli import _state_path, _stop_payload, main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


class LegacyStopContractTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "legacy-stop@example.test")
        _git(repo, "config", "user.name", "Legacy Stop")
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        tests = repo / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text(
            "import unittest\nimport app\n"
            "class T(unittest.TestCase):\n"
            "    def test_value(self): self.assertGreater(app.VALUE, 0)\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "base")
        return repo

    def _event(
        self,
        repo: Path,
        command: str,
        session_id: str,
        **extra: object,
    ) -> dict[str, object]:
        output = io.StringIO()
        payload = json.dumps({"cwd": str(repo), "session_id": session_id, **extra})
        with mock.patch("sys.stdin", io.StringIO(payload)), contextlib.redirect_stdout(output):
            self.assertEqual(main([command, "--repo", str(repo), "--session-id", session_id]), 0)
        rendered = output.getvalue().strip()
        return json.loads(rendered) if rendered else {}

    def test_payload_contract_reserves_decision_for_blocks(self) -> None:
        self.assertNotIn("decision", _stop_payload("accepted"))
        blocked = _stop_payload("failed", block=True)
        self.assertEqual(blocked["decision"], "block")
        self.assertEqual(blocked["reason"], "failed")
        terminal = _stop_payload("unverified", terminal=True)
        self.assertNotIn("decision", terminal)
        self.assertIs(terminal["continue"], False)
        self.assertEqual(terminal["stopReason"], "unverified")
        with self.assertRaises(ValueError):
            _stop_payload("invalid", block=True, terminal=True)

    def test_missing_or_invalid_start_state_terminates_unverified_without_a_loop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            missing = self._event(
                repo,
                "session-stop",
                "missing",
                stop_hook_active=True,
            )
            self.assertNotIn("decision", missing)
            self.assertIs(missing["continue"], False)
            self.assertIn("not armed", str(missing["stopReason"]))

            invalid_path = _state_path(repo, "invalid")
            invalid_path.write_text("{}", encoding="utf-8")
            invalid = self._event(
                repo,
                "session-stop",
                "invalid",
                stop_hook_active=True,
            )
            self.assertNotIn("decision", invalid)
            self.assertIs(invalid["continue"], False)
            self.assertIn("state is invalid", str(invalid["stopReason"]))

    def test_no_change_success_omits_decision(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            self.assertEqual(self._event(repo, "session-start", "noop"), {})
            stopped = self._event(repo, "session-stop", "noop")
            self.assertNotIn("decision", stopped)
            self.assertIn("no repository change", stopped["systemMessage"])

    def test_exhausted_failed_proof_terminates_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            path = _state_path(repo, "exhausted")
            path.write_text(json.dumps({"base": base, "retries": 3}), encoding="utf-8")
            (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            with mock.patch(
                "diffwitness.proof_cli._run_proof",
                return_value=(1, None, "evidence still fails"),
            ):
                stopped = self._event(repo, "session-stop", "exhausted")
            self.assertNotIn("decision", stopped)
            self.assertIs(stopped["continue"], False)
            self.assertIn("human intervention", str(stopped["stopReason"]))


if __name__ == "__main__":
    unittest.main()
