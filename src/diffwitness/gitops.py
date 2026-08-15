from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class GitError(RuntimeError):
    pass


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
        raise GitError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr.strip()}"
        )
    return proc


def git(repo: Path, *args: str, check: bool = True, input_text: str | None = None) -> str:
    return _run(["git", *args], cwd=repo, check=check, input_text=input_text).stdout


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


def snapshot_worktree(repo: Path) -> str:
    """Create an unreachable commit representing the full non-ignored worktree.

    Uses an alternate index, so the user's real index/staging area is never changed.
    Untracked (non-ignored) files are included, which is important for newly-written tests.
    """
    head = resolve_ref(repo, "HEAD")
    fd, index_name = tempfile.mkstemp(prefix="diffwitness-index-")
    os.close(fd)
    os.unlink(index_name)
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = index_name
    try:
        _run(["git", "read-tree", head], cwd=repo, env=env)
        _run(["git", "add", "-A", "--", "."], cwd=repo, env=env)
        tree = _run(["git", "write-tree"], cwd=repo, env=env).stdout.strip()
        commit = _run(
            ["git", "commit-tree", tree, "-p", head],
            cwd=repo,
            input_text="DiffWitness ephemeral worktree snapshot\n",
        ).stdout.strip()
        return commit
    finally:
        try:
            os.unlink(index_name)
        except FileNotFoundError:
            pass


def diff_text(repo: Path, base: str, candidate: str) -> str:
    return git(
        repo,
        "-c",
        "core.quotePath=false",
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--find-renames",
        "--binary",
        "--unified=3",
        base,
        candidate,
        "--",
    )


@contextmanager
def detached_worktree(repo: Path, commit: str, label: str) -> Iterator[Path]:
    parent = Path(tempfile.mkdtemp(prefix=f"diffwitness-{label}-"))
    worktree = parent / "repo"
    try:
        git(repo, "worktree", "add", "--detach", "--quiet", str(worktree), commit)
        yield worktree
    finally:
        if worktree.exists():
            git(repo, "worktree", "remove", "--force", str(worktree), check=False)
        shutil.rmtree(parent, ignore_errors=True)


def hard_reset(worktree: Path, commit: str) -> None:
    git(worktree, "reset", "--hard", "--quiet", commit)
    # Remove ordinary untracked test output, but preserve ignored dependency caches.
    git(worktree, "clean", "-fd", "--quiet", check=False)


def apply_patch(worktree: Path, patch: str, *, reverse: bool = False) -> tuple[bool, str]:
    args = ["apply", "--whitespace=nowarn"]
    if reverse:
        args.append("-R")
    proc = _run(
        ["git", *args, "-"],
        cwd=worktree,
        input_text=patch,
        check=False,
    )
    return proc.returncode == 0, proc.stderr.strip()


def candidate_delta(worktree: Path, candidate: str) -> str:
    return git(
        worktree,
        "-c",
        "core.quotePath=false",
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--binary",
        candidate,
        "--",
    )
