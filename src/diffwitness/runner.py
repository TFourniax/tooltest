from __future__ import annotations

import math
import os
import signal
import subprocess
import time
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

from .models import CommandResult, RunSet


TAIL_CHARS = 5000
_TERMINATE_GRACE_SECONDS = 0.75
_COMMUNICATE_GRACE_SECONDS = 2.0
_MIN_TIMEOUT_SECONDS = 0.001
_ACTIVE_DEADLINE: ContextVar[float | None] = ContextVar("diffwitness_deadline", default=None)
F = TypeVar("F", bound=Callable[..., object])


class WallClockBudgetExceeded(TimeoutError):
    """Raised before starting more evidence after the total proof budget has expired."""


def wall_clock_budgeted(func: F) -> F:
    """Apply `max_total_seconds` from a keyword-only proof API to every nested command.

    DiffWitness proof engines already centralize process execution in this module. A context-local
    deadline therefore gives exhaustive proof, Adaptive Core, preparation commands and repeated
    stability runs one shared wall-clock budget without threading a deadline parameter through every
    internal helper. Nested proof calls inherit the tighter deadline.
    """

    @wraps(func)
    def wrapped(*args, **kwargs):
        raw = kwargs.get("max_total_seconds")
        if raw is None:
            return func(*args, **kwargs)
        if isinstance(raw, bool):
            raise ValueError("max_total_seconds must be a finite number > 0")
        seconds = float(raw)
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("max_total_seconds must be a finite number > 0")
        deadline = time.monotonic() + seconds
        inherited = _ACTIVE_DEADLINE.get()
        if inherited is not None:
            deadline = min(deadline, inherited)
        token = _ACTIVE_DEADLINE.set(deadline)
        try:
            return func(*args, **kwargs)
        finally:
            _ACTIVE_DEADLINE.reset(token)

    return wrapped  # type: ignore[return-value]


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


def bounded_timeout(timeout: float, deadline: float | None = None) -> float:
    """Return the command timeout constrained by the active proof deadline when present."""
    if isinstance(timeout, bool):
        raise ValueError("timeout must be a finite number > 0")
    seconds = float(timeout)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout must be a finite number > 0")
    effective_deadline = deadline if deadline is not None else _ACTIVE_DEADLINE.get()
    if effective_deadline is None:
        return seconds
    if not math.isfinite(float(effective_deadline)):
        raise ValueError("deadline must be finite")
    remaining = effective_deadline - time.monotonic()
    if remaining <= 0:
        raise WallClockBudgetExceeded("DiffWitness wall-clock proof budget exhausted")
    return max(_MIN_TIMEOUT_SECONDS, min(seconds, remaining))


def _popen_group_kwargs() -> dict[str, object]:
    """Start every evidence command in a process group that DiffWitness owns.

    Evidence frequently starts test workers, language servers, browser processes or nested shell
    commands. A timeout that kills only the shell can otherwise leave those descendants running
    after a counterfactual variant has been abandoned.
    """
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _windows_job_for_process(proc: subprocess.Popen[str]) -> int | None:
    """Attach a Windows evidence process to a kill-on-close Job Object when possible.

    `taskkill /T` remains the fallback. A Job Object is stronger because descendants inherit job
    membership, so closing the job tears down the complete evidence tree even when the shell exits
    or a worker becomes re-parented while a timeout is being handled. This uses only stdlib ctypes.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _JobBasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _JobExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _JobBasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE
        set_job_info = kernel32.SetInformationJobObject
        set_job_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        set_job_info.restype = wintypes.BOOL
        assign_process = kernel32.AssignProcessToJobObject
        assign_process.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        assign_process.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        job = create_job(None, None)
        if not job:
            return None
        info = _JobExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not set_job_info(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            close_handle(job)
            return None

        process_handle = wintypes.HANDLE(int(proc._handle))  # type: ignore[attr-defined]
        if not assign_process(job, process_handle):
            close_handle(job)
            return None
        return int(job)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _close_windows_job(job_handle: int | None) -> None:
    if os.name != "nt" or job_handle is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(wintypes.HANDLE(job_handle))
    except (OSError, TypeError, ValueError):
        pass


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


def run_command(
    command: str,
    *,
    cwd: Path,
    source_repo: Path,
    timeout: float,
    deadline: float | None = None,
) -> CommandResult:
    started = time.monotonic()
    effective_timeout = bounded_timeout(timeout, deadline)
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
    windows_job = _windows_job_for_process(proc)
    try:
        stdout, stderr = proc.communicate(timeout=effective_timeout)
        return CommandResult(
            returncode=proc.returncode,
            duration_s=time.monotonic() - started,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
        )
    except subprocess.TimeoutExpired:
        if windows_job is not None:
            _close_windows_job(windows_job)
            windows_job = None
        else:
            _terminate_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=_COMMUNICATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
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
    finally:
        # Evidence commands must not leave background workers alive after a variant finishes.
        if windows_job is not None:
            _close_windows_job(windows_job)


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
    deadline: float | None = None,
) -> RunSet:
    """Run evidence repeatedly, optionally rebuilding an identical sandbox before every run.

    `before_each` is intentionally executed before *every* repetition, including the first. Proof
    callers use it to restore an immutable variant and rerun preparation so a test that mutates
    files, caches, fixtures, or ignored state cannot influence the next stability observation.

    The active wall-clock budget is checked before both preparation and command execution, so a
    proof never starts a fresh repetition after its global deadline has expired.
    """
    if repetitions < 1:
        raise ValueError("repetitions must be >= 1")
    runs: list[CommandResult] = []
    for _ in range(repetitions):
        bounded_timeout(timeout, deadline)
        if before_each is not None:
            before_each()
        runs.append(
            run_command(
                command,
                cwd=cwd,
                source_repo=source_repo,
                timeout=timeout,
                deadline=deadline,
            )
        )
    return RunSet(runs=runs, classification=classify_runs(runs))
