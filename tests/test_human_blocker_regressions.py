from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _run(
    args: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    timeout: float = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )


def _git(repo: Path, *args: str) -> str:
    proc = _run(["git", *args], cwd=repo)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def _entrypoint(name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).parent / f"{name}{suffix}"
    if sibling.is_file():
        return str(sibling.resolve())
    value = shutil.which(name)
    if not value:
        raise AssertionError(f"installed-product regression test requires {name}")
    return str(Path(value).resolve())


def _repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "human-regression@example.test")
    _git(repo, "config", "user.name", "Human Regression")
    (repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "test_calculator.py").write_text(
        "import unittest\nfrom calculator import add\n\n"
        "class CalculatorTests(unittest.TestCase):\n"
        "    def test_adds_two_numbers(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    _git(repo, "add", "calculator.py", "test_calculator.py")
    _git(repo, "commit", "-qm", "broken baseline")
    return repo


def _hook(payload: dict[str, object], event: str) -> dict[str, object]:
    entries = payload.get("hooks", {}).get(event, [])  # type: ignore[union-attr]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks", []):
            if isinstance(hook, dict) and hook.get("type") == "command":
                return hook
    raise AssertionError(f"no command hook found for {event}")


class HumanBlockerRegressionTests(unittest.TestCase):
    def test_claude_hooks_use_exec_form_and_complete_native_change(self) -> None:
        dw = _entrypoint("dw")
        _entrypoint("idleproof")
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td), "claude-exec")
            setup = _run([dw, "setup", "--agent", "claude"], cwd=repo)
            self.assertEqual(setup.returncode, 0, setup.stderr)

            settings = json.loads((repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            expected = {
                "SessionStart": "session-start",
                "UserPromptSubmit": "user-prompt-submit",
                "Stop": "session-stop",
            }
            hooks: dict[str, dict[str, object]] = {}
            for event, action in expected.items():
                hook = _hook(settings, event)
                hooks[event] = hook
                self.assertEqual(Path(str(hook.get("command"))).resolve(), Path(dw).resolve())
                self.assertEqual(hook.get("args"), ["ide-hook", action, "--provider", "claude"])

            common = {
                "cwd": str(repo),
                "session_id": "real-shell-regression",
                "source": "startup",
            }
            for event, extra in (
                ("SessionStart", {}),
                ("UserPromptSubmit", {"prompt": "Fix the calculator regression"}),
            ):
                hook = hooks[event]
                proc = _run(
                    [str(hook["command"]), *[str(value) for value in hook["args"]]],  # type: ignore[index]
                    cwd=repo,
                    input_text=json.dumps({**common, "hook_event_name": event, **extra}),
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)

            (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            stop_hook = hooks["Stop"]
            stopped = _run(
                [str(stop_hook["command"]), *[str(value) for value in stop_hook["args"]]],  # type: ignore[index]
                cwd=repo,
                input_text=json.dumps({**common, "hook_event_name": "Stop"}),
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertIn("Proof accepted", stopped.stdout)
            self.assertTrue((repo / ".git" / "diffwitness" / "change-envelope.json").is_file())

    def test_manual_gate_persists_current_worktree_verification(self) -> None:
        dw = _entrypoint("dw")
        with tempfile.TemporaryDirectory() as td:
            repo = _repo(Path(td), "manual-gate")
            (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

            gated = _run([dw, "gate", "--base", "HEAD", "--candidate", "WORKTREE"], cwd=repo)
            self.assertEqual(gated.returncode, 0, gated.stderr)
            self.assertIn("DiffWitness Gate accepted", gated.stdout)

            envelope = repo / ".git" / "diffwitness" / "change-envelope.json"
            self.assertTrue(envelope.is_file(), gated.stdout)
            status = _run([dw, "status", "--json"], cwd=repo)
            self.assertEqual(status.returncode, 0, status.stderr)
            payload = json.loads(status.stdout)
            self.assertEqual(payload["current_worktree_verification"]["status"], "accepted")
            self.assertTrue(payload["latest_change_envelope"]["proof"]["accepted"])
            self.assertNotEqual(payload["latest_change_envelope"].get("change_id"), None)


if __name__ == "__main__":
    unittest.main()
