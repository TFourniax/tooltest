from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from .models import CommandResult, RunSet


TAIL_CHARS = 5000


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


def run_command(command: str, *, cwd: Path, source_repo: Path, timeout: float) -> CommandResult:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=command_env(source_repo),
            timeout=timeout,
        )
        return CommandResult(
            returncode=proc.returncode,
            duration_s=time.monotonic() - started,
            stdout_tail=_tail(proc.stdout),
            stderr_tail=_tail(proc.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=None,
            duration_s=time.monotonic() - started,
            stdout_tail=_tail(exc.stdout if isinstance(exc.stdout, str) else ""),
            stderr_tail=_tail(exc.stderr if isinstance(exc.stderr, str) else ""),
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
