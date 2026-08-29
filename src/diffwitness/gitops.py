from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator


class GitError(RuntimeError):
    pass


_TRANSIENT_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
}
_TRANSIENT_SUFFIXES = {".pyc", ".pyo"}
_TRANSIENT_FILES = {".coverage"}
_LOCAL_TOOL_UNTRACKED = {
    ".claude/settings.local.json",
    ".codex/hooks.json",
    ".cursor/hooks.json",
    ".cursor/rules/idleproof-continuity.mdc",
    ".diffwitness/soul.md",
}


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise GitError(f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr.strip()}")
    return proc


def _run_bytes(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Run Git with byte-exact stdin/stdout for object plumbing.

    Text-mode subprocess pipes translate newlines on Windows. That is harmless for ordinary Git
    commands, but corrupts protocols such as `mktree -z` and makes supposedly portable Git objects
    OS-dependent. Exact object/record callers must use this byte path instead.
    """
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_bytes,
        text=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"command failed ({proc.returncode}): {' '.join(args)}\n{stderr}")
    return proc


def git_result(repo: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run Git without raising so callers can distinguish expected absence from transport failure."""
    return _run(["git", *args], cwd=repo, check=False, input_text=input_text)


def git(repo: Path, *args: str, check: bool = True, input_text: str | None = None) -> str:
    return _run(["git", *args], cwd=repo, check=check, input_text=input_text).stdout


def git_bytes_result(
    repo: Path, *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run Git byte-exactly without raising."""
    return _run_bytes(["git", *args], cwd=repo, check=False, input_bytes=input_bytes)


def git_bytes(
    repo: Path,
    *args: str,
    check: bool = True,
    input_bytes: bytes | None = None,
) -> bytes:
    """Run Git byte-exactly for object plumbing and NUL-delimited protocols."""
    return _run_bytes(["git", *args], cwd=repo, env=None, check=check, input_bytes=input_bytes).stdout


def repo_root(path: str | Path = ".") -> Path:
    path = Path(path).resolve()
    proc = _run(["git", "rev-parse", "--show-toplevel"], cwd=path, check=False)
    if proc.returncode != 0:
        raise GitError(f"not a Git repository: {path}")
    return Path(proc.stdout.strip()).resolve()


def resolve_ref(repo: Path, ref: str) -> str:
    value = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    if not value:
        raise GitError(f"cannot resolve Git ref: {ref}")
    return value


def _is_local_tool_untracked(path: PurePosixPath) -> bool:
    """Return True for project-local IdleProof/agent plumbing at any monorepo depth."""
    normalized = path.as_posix().lstrip("./")
    parts = path.parts
    if ".idleproof" in parts:
        return True
    if len(parts) >= 2 and parts[-2:] == (".claude", "settings.local.json"):
        return True
    if len(parts) >= 2 and parts[-2:] == (".codex", "hooks.json"):
        return True
    if len(parts) >= 2 and parts[-2:] == (".cursor", "hooks.json"):
        return True
    if len(parts) >= 3 and parts[-3:] == (".cursor", "rules", "idleproof-continuity.mdc"):
        return True
    if len(parts) >= 2 and parts[-2:] == (".diffwitness", "soul.md"):
        return True
    return normalized in _LOCAL_TOOL_UNTRACKED


def _is_transient_untracked(path: str) -> bool:
    """Recognize local/runtime artifacts that must not become proof surface.

    This filter only applies to *untracked* files. If a repository deliberately tracks a matching
    path, DiffWitness preserves it exactly like any other tracked content. Besides interpreter/test
    caches, local IdleProof state and local Claude/Codex/Cursor hook plumbing are omitted even when
    the coding session runs from a nested package in a monorepo, so installing the understanding
    layer cannot change the software tree DiffWitness proves.
    """
    posix = PurePosixPath(path)
    if _is_local_tool_untracked(posix):
        return True
    if any(part in _TRANSIENT_DIRS for part in posix.parts):
        return True
    if posix.suffix.lower() in _TRANSIENT_SUFFIXES:
        return True
    return posix.name in _TRANSIENT_FILES


def _transient_untracked_paths(repo: Path) -> list[str]:
    raw = git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(path for path in raw.split("\0") if path and _is_transient_untracked(path))


def snapshot_worktree(repo: Path, *, exclude_paths: list[str] | None = None) -> str:
    """Create an unreachable commit representing meaningful worktree content.

    An alternate index is used, so the user's real staging area is untouched. Git-ignored files are
    not captured. Narrow, known *untracked* runtime/test/tool artifacts are also omitted because a
    preceding evidence run or local agent integration must not change the semantic candidate being
    proved. Deliberately tracked files are never auto-excluded, even if their names resemble those
    local artifacts.

    `exclude_paths` is reserved for caller-owned generated artifacts such as the certificate being
    verified. All exclusions affect only the ephemeral alternate index and never mutate the user's
    real staging area or working files.
    """
    head = resolve_ref(repo, "HEAD")
    fd, index_name = tempfile.mkstemp(prefix="diffwitness-index-")
    os.close(fd)
    index_path = Path(index_name)
    try:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index_path)
        _run(["git", "read-tree", head], cwd=repo, env=env)
        _run(["git", "add", "-A", "--", "."], cwd=repo, env=env)
        excluded = set(_transient_untracked_paths(repo))
        for value in exclude_paths or []:
            p = Path(value)
            try:
                rel = p.resolve().relative_to(repo.resolve()).as_posix()
            except (OSError, ValueError):
                continue
            excluded.add(rel)
        if excluded:
            # Reset excluded paths in the alternate index to HEAD. If they do not exist in HEAD,
            # remove them from the alternate index. Worktree/staging area are never touched.
            for rel in sorted(excluded):
                present = _run(["git", "cat-file", "-e", f"{head}:{rel}"], cwd=repo, check=False)
                if present.returncode == 0:
                    _run(["git", "reset", "-q", head, "--", rel], cwd=repo, env=env)
                else:
                    _run(["git", "rm", "--cached", "-q", "--ignore-unmatch", "--", rel], cwd=repo, env=env)
        tree = _run(["git", "write-tree"], cwd=repo, env=env).stdout.strip()
        commit = _run(
            ["git", "commit-tree", tree, "-p", head],
            cwd=repo,
            env=env,
            input_text="DiffWitness worktree snapshot\n",
        ).stdout.strip()
        return commit
    finally:
        index_path.unlink(missing_ok=True)


@contextmanager
def materialize(repo: Path, ref: str) -> Iterator[Path]:
    """Materialize a Git ref in an isolated temporary worktree."""
    resolved = resolve_ref(repo, ref)
    with tempfile.TemporaryDirectory(prefix="diffwitness-materialize-") as td:
        root = Path(td) / "checkout"
        _run(["git", "worktree", "add", "--detach", str(root), resolved], cwd=repo)
        try:
            yield root
        finally:
            _run(["git", "worktree", "remove", "--force", str(root)], cwd=repo, check=False)


def ensure_command(command: str) -> str:
    value = shutil.which(command)
    if value is None:
        raise GitError(f"required command not found: {command}")
    return value
