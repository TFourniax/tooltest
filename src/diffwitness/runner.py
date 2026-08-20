from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

from .models import CommandResult, RunSet


TAIL_CHARS = 5000
_TERMINATE_GRACE_SECONDS = 0.75
_COMMUNICATE_GRACE_SECONDS = 2.0


def _tail(value: str | None) -> str:
    if not value:
        return ""
    return value[-TAIL_CHARS:]


def command_env(source_repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    node_modules = source_repo / "node_modules"
    if node_modules.is_dir():
        bins = node_modules / ".bin"
        if bins.is_dir():
            env["PATH"] = str(bins) + os.pathsep + env.get("PATH", "")
        env["NODE_PATH"] = str(node_modules) + (
            os.pathsep + env["NODE_PATH"] if env.get("NODE_PATH") else ""
        )
    return env


def _popen_group_kwargs() -> dict[str, object]:
    """Start every evidence command in a process group that DiffWitness owns.

    Evidence frequently starts test workers, language servers, browser processes or nested shell
    commands. A timeout that kills only the shell can otherwise leave those descendants running
    after a counterfactual variant has been abandoned.
    """
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Best-effort terminate the complete evidence process tree without extra dependencies."""
    if proc.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            proc.terminate()
        except OSError:
            return

    try:
        proc.wait(timeout=_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def run_command(command: str, *, cwd: Path, source_repo: Path, timeout: float) -> CommandResult:
    started = time.monotonic()
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=command_env(source_repo),
        **_popen_group_kwargs(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return CommandResult(
            returncode=proc.returncode,
            duration_s=time.monotonic() - started,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
        )
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=_COMMUNICATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            # Defensive fallback for an unusual platform/process-tree failure. The direct child
            # must not survive even when the operating system could not terminate descendants.
            try:
                proc.kill()
            except OSError:
                pass
            stdout, stderr = proc.communicate()
        return CommandResult(
            returncode=None,
            duration_s=time.monotonic() - started,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            timed_out=True,
        )


def classify_runs(runs: list[CommandResult]) -> str:
    if any(run.timed_out for run in runs):
        return "timeout"
    passed = [run.passed for run in runs]
    if all(passed):
        return "stable-pass"
    if not any(passed):
        return "stable-fail"
    return "flaky"


def run_repeated(
    command: str,
    *,
    cwd: Path,
    source_repo: Path,
    timeout: float,
    repetitions: int,
    before_each: Callable[[], None] | None = None,
) -> RunSet:
    """Run evidence repeatedly, optionally rebuilding an identical sandbox before every run.

    `before_each` is intentionally executed before *every* repetition, including the first. Proof
    callers use it to restore an immutable variant and rerun preparation so a test that mutates
    files, caches, fixtures, or ignored state cannot influence the next stability observation.
    """
    if repetitions < 1:
        raise ValueError("repetitions must be >= 1")
    runs: list[CommandResult] = []
    for _ in range(repetitions):
        if before_each is not None:
            before_each()
        runs.append(run_command(command, cwd=cwd, source_repo=source_repo, timeout=timeout))
    return RunSet(runs=runs, classification=classify_runs(runs))
