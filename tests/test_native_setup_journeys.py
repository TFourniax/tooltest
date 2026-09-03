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
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=env,
    )


def _git(repo: Path, *args: str) -> str:
    proc = _run(["git", *args], cwd=repo)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def _dw(repo: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    scripts = str(Path(sys.executable).parent)
    env["PATH"] = scripts + os.pathsep + env.get("PATH", "")
    entrypoint = _entrypoint("dw")
    if entrypoint is not None:
        env["DIFFWITNESS_BIN"] = entrypoint
    return _run(
        [sys.executable, "-m", "diffwitness.entry", *args],
        cwd=repo,
        input_text=input_text,
        env=env,
    )


def _entrypoint(name: str) -> str | None:
    suffix = ".exe" if os.name == "nt" else ""
    sibling = Path(sys.executable).parent / f"{name}{suffix}"
    if sibling.is_file():
        return str(sibling)
    return shutil.which(name)


def _hook_command(repo: Path, provider: str, event: str) -> str:
    path = (
        repo / ".claude" / "settings.local.json"
        if provider == "claude"
        else repo / ".codex" / "hooks.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    for entry in payload.get("hooks", {}).get(event, []):
        for hook in entry.get("hooks", []):
            command = hook.get("command")
            if isinstance(command, str) and "ide-hook" in command:
                return command
    raise AssertionError(f"no DiffWitness command installed for {provider} {event}")


def _run_hook(repo: Path, command: str, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    # Provider hook contracts define command handlers as shell commands. Exercising the persisted
    # string through the platform shell tests the same quoting/entrypoint boundary as the provider.
    return subprocess.run(
        command,
        cwd=repo,
        input=json.dumps(payload),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
        shell=True,
    )


class NativeSetupJourneyTests(unittest.TestCase):
    def _repo(self, root: Path, name: str) -> Path:
        repo = root / name
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "native-journey@example.test")
        _git(repo, "config", "user.name", "Native Journey")
        (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        tests = repo / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text(
            "import unittest\nfrom app import add\n\n"
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
            "stability_runs = 1\n"
            "max_total_seconds = 120\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "buggy baseline")
        return repo

    def test_generated_hooks_complete_all_guided_and_technical_provider_journeys(self) -> None:
        idleproof = _entrypoint("idleproof")
        dw = _entrypoint("dw")
        self.assertIsNotNone(idleproof, "installed-product tests require the idleproof entrypoint")
        self.assertIsNotNone(dw, "installed-product tests require the dw entrypoint")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for provider in ("claude", "codex"):
                for view in ("guided", "technical"):
                    with self.subTest(provider=provider, view=view):
                        repo = self._repo(root, f"{provider}-{view}")
                        selected = _dw(repo, "view", view)
                        self.assertEqual(selected.returncode, 0, selected.stderr)

                        setup = _dw(
                            repo,
                            "setup",
                            "--agent",
                            provider,
                            "--idleproof-command",
                            str(idleproof),
                        )
                        self.assertEqual(setup.returncode, 0, setup.stderr)
                        if view == "guided":
                            self.assertIn("configuré", setup.stdout)
                        else:
                            self.assertIn("Agent integration configured", setup.stdout)
                        if provider == "codex":
                            trust_marker = "/hooks" if view == "guided" else "trust"
                            self.assertIn(trust_marker, setup.stdout.lower())

                        session = f"native-{provider}-{view}"
                        common = {
                            "cwd": str(repo),
                            "session_id": session,
                            "source": "startup",
                        }
                        start_command = _hook_command(repo, provider, "SessionStart")
                        prompt_command = _hook_command(repo, provider, "UserPromptSubmit")
                        stop_command = _hook_command(repo, provider, "Stop")
                        for command in (start_command, prompt_command, stop_command):
                            self.assertIn(f"--provider {provider}", command)

                        started = _run_hook(
                            repo,
                            start_command,
                            {**common, "hook_event_name": "SessionStart"},
                        )
                        self.assertEqual(started.returncode, 0, started.stderr)

                        setup_status = _dw(
                            repo,
                            "setup",
                            "status",
                            "--idleproof-command",
                            str(idleproof),
                            "--json",
                        )
                        self.assertEqual(setup_status.returncode, 0, setup_status.stderr)
                        activation = json.loads(setup_status.stdout)["nativeActivation"]
                        self.assertEqual(activation["observedAdapters"], [provider])
                        self.assertEqual(activation["pendingObservationAdapters"], [])

                        prompted = _run_hook(
                            repo,
                            prompt_command,
                            {
                                **common,
                                "hook_event_name": "UserPromptSubmit",
                                "prompt": "Fix add so the existing regression test passes",
                            },
                        )
                        self.assertEqual(prompted.returncode, 0, prompted.stderr)
                        self.assertNotIn("change-proof: dw guard", prompted.stdout)
                        self.assertIn("Do not run `dw guard`", prompted.stdout)

                        (repo / "app.py").write_text(
                            "def add(a, b):\n    return a + b\n", encoding="utf-8"
                        )
                        stopped = _run_hook(
                            repo,
                            stop_command,
                            {**common, "hook_event_name": "Stop"},
                        )
                        self.assertEqual(stopped.returncode, 0, stopped.stderr)
                        result = json.loads(stopped.stdout.splitlines()[-1])
                        self.assertNotIn("decision", result, result)
                        self.assertIn("Proof accepted", result["systemMessage"])
                        self.assertIn("Continuity", result["systemMessage"])

                        status = _dw(repo, "status", "--view", view)
                        self.assertEqual(status.returncode, 0, status.stderr)
                        expected_header = "DIFFWITNESS · GUIDED" if view == "guided" else "TECHNICAL VIEW"
                        self.assertIn(expected_header, status.stdout)
                        self.assertNotIn("Verify the current change", status.stdout)

                        explained = _dw(repo, "explain", "--view", view)
                        self.assertEqual(explained.returncode, 0, explained.stderr)
                        coverage_marker = "version actuelle" if view == "guided" else "current"
                        self.assertIn(coverage_marker, explained.stdout.lower())


if __name__ == "__main__":
    unittest.main()
