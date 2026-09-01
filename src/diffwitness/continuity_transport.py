from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .continuity_events import (
    ContinuityError,
    _event_lock,
    continuity_paths,
    read_project_events,
    validate_project_events,
)
from .gitops import GitError, git, git_bytes, git_bytes_result, git_result, repo_root

DEFAULT_CONTINUITY_REF = "refs/diffwitness/project-events"
CONTINUITY_OBJECT_PATH = "events.jsonl"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _serialize(events: list[dict[str, Any]]) -> bytes:
    return "".join(_canonical(event) + "\n" for event in events).encode("utf-8")


def _parse(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContinuityError("ProjectEvent checkpoint is not valid UTF-8") from exc
    events: list[dict[str, Any]] = []
    try:
        for number, raw in enumerate(text.splitlines(), start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ContinuityError(f"ProjectEvent checkpoint line {number} is not an object")
            events.append(value)
    except json.JSONDecodeError as exc:
        raise ContinuityError(f"invalid ProjectEvent checkpoint JSON: {exc}") from exc
    validate_project_events(events)
    return events


def _ref_commit(repo: Path, ref: str) -> str | None:
    value = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False).strip()
    return value or None


def _decode_ascii(value: bytes) -> str:
    return value.decode("ascii", errors="strict").strip()


def _tracking_ref(remote: str, ref: str) -> str:
    digest = hashlib.sha256(f"continuity\0{remote}\0{ref}".encode("utf-8")).hexdigest()[:16]
    return f"refs/diffwitness/remotes/continuity-{digest}"


def _set_ref(repo: Path, ref: str, commit: str) -> None:
    git(repo, "update-ref", ref, commit)


def _checkpoint_blob(repo: Path, commit: str) -> bytes:
    result = git_bytes_result(repo, "show", f"{commit}:{CONTINUITY_OBJECT_PATH}")
    if result.returncode == 0:
        return result.stdout
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    raise GitError(
        f"command failed ({result.returncode}): git show {commit}:{CONTINUITY_OBJECT_PATH}\n{detail}"
    )


def read_checkpoint(
    *,
    repo: str | Path,
    ref: str = DEFAULT_CONTINUITY_REF,
) -> tuple[str, list[dict[str, Any]]] | None:
    root = repo_root(repo)
    commit = _ref_commit(root, ref)
    if not commit:
        return None
    return commit, _parse(_checkpoint_blob(root, commit))


def checkpoint_events(
    *,
    repo: str | Path,
    ref: str = DEFAULT_CONTINUITY_REF,
) -> str:
    """Snapshot the validated ProjectEvent chain on an isolated Git ref without touching HEAD."""
    root = repo_root(repo)
    events = read_project_events(continuity_paths(root).events)
    body = _serialize(events)
    blob = _decode_ascii(git_bytes(root, "hash-object", "-w", "--stdin", input_bytes=body))
    tree_record = f"100644 blob {blob}\t{CONTINUITY_OBJECT_PATH}".encode("utf-8") + b"\0"
    tree = _decode_ascii(git_bytes(root, "mktree", "-z", input_bytes=tree_record))
    parent = _ref_commit(root, ref)
    if parent:
        current = read_checkpoint(repo=root, ref=ref)
        if current is not None and current[1] == events:
            return parent

    args = [
        "-c",
        "user.name=DiffWitness",
        "-c",
        "user.email=diffwitness@localhost",
        "commit-tree",
        tree,
    ]
    if parent:
        args += ["-p", parent]
    head = events[-1]["event_hash"] if events else "none"
    message = (
        "DiffWitness ProjectEvent checkpoint\n\n"
        f"events: {len(events)}\n"
        f"event-head: {head}\n"
    ).encode("utf-8")
    commit = _decode_ascii(git_bytes(root, *args, input_bytes=message))
    if parent:
        git(root, "update-ref", ref, commit, parent)
    else:
        git(root, "update-ref", ref, commit)
    return commit


def _hashes(events: list[dict[str, Any]]) -> list[str]:
    return [str(event.get("event_hash") or "") for event in events]


def _atomic_fast_forward(root: Path, expected_local: list[dict[str, Any]], remote: list[dict[str, Any]]) -> None:
    paths = continuity_paths(root)
    validate_project_events(remote)
    expected_hashes = _hashes(expected_local)
    remote_hashes = _hashes(remote)
    if expected_hashes != remote_hashes[: len(expected_hashes)]:
        raise ContinuityError("ProjectEvent checkpoint is not a fast-forward of local history")

    with _event_lock(paths):
        current = read_project_events(paths.events)
        current_hashes = _hashes(current)
        if current_hashes != expected_hashes:
            raise ContinuityError("ProjectEvent history changed concurrently; retry checkpoint restore")
        if current_hashes == remote_hashes:
            return
        paths.root.mkdir(parents=True, exist_ok=True)
        temp = paths.root / f".events.restore-{os.getpid()}-{time.time_ns()}.tmp"
        fd: int | None = None
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(_serialize(remote))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, paths.events)
            try:
                directory_fd = os.open(paths.root, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
        finally:
            if fd is not None:
                os.close(fd)
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def restore_checkpoint(
    *,
    repo: str | Path,
    ref: str = DEFAULT_CONTINUITY_REF,
    missing_ok: bool = False,
) -> str:
    """Fast-forward local ProjectEvents from a local checkpoint; divergence fails closed."""
    root = repo_root(repo)
    checkpoint = read_checkpoint(repo=root, ref=ref)
    if checkpoint is None:
        if missing_ok:
            return "missing"
        raise ContinuityError(f"ProjectEvent checkpoint ref does not exist: {ref}")
    _, remote_events = checkpoint
    local_events = read_project_events(continuity_paths(root).events)
    local_hashes = _hashes(local_events)
    remote_hashes = _hashes(remote_events)
    if local_hashes == remote_hashes:
        return "equal"
    if local_hashes == remote_hashes[: len(local_hashes)]:
        _atomic_fast_forward(root, local_events, remote_events)
        return "restored"
    if remote_hashes == local_hashes[: len(remote_hashes)]:
        return "local-ahead"
    raise ContinuityError(
        "local and checkpoint ProjectEvent histories diverged; refusing to merge two hash chains automatically"
    )


def fetch_checkpoint(
    *,
    repo: str | Path,
    remote: str = "origin",
    ref: str = DEFAULT_CONTINUITY_REF,
    target_ref: str | None = None,
    missing_ok: bool = True,
) -> bool:
    root = repo_root(repo)
    target = target_ref or ref
    if target_ref is not None:
        git(root, "update-ref", "-d", target, check=False)
    probe = git_result(root, "ls-remote", "--exit-code", remote, ref)
    if probe.returncode == 2:
        if missing_ok:
            return False
        raise ContinuityError(f"ProjectEvent checkpoint {ref} does not exist on remote {remote}")
    if probe.returncode != 0:
        detail = probe.stderr.strip() or probe.stdout.strip() or "unknown Git transport error"
        raise ContinuityError(f"cannot query ProjectEvent checkpoint {ref} on {remote}: {detail}")
    fetched = git_result(root, "fetch", "--no-tags", remote, f"+{ref}:{target}")
    if fetched.returncode != 0:
        detail = fetched.stderr.strip() or fetched.stdout.strip() or "unknown Git transport error"
        raise ContinuityError(f"could not fetch ProjectEvent checkpoint {ref} from {remote}: {detail}")
    if _ref_commit(root, target):
        return True
    raise ContinuityError(f"Git reported a successful fetch but ProjectEvent checkpoint {ref} is unavailable")


def pull_checkpoint(
    *,
    repo: str | Path,
    remote: str = "origin",
    ref: str = DEFAULT_CONTINUITY_REF,
    missing_ok: bool = True,
) -> str:
    """Fetch a remote ProjectEvent ref and fast-forward local history without touching code refs."""
    root = repo_root(repo)
    tracking = _tracking_ref(remote, ref)
    if not fetch_checkpoint(
        repo=root,
        remote=remote,
        ref=ref,
        target_ref=tracking,
        missing_ok=missing_ok,
    ):
        return "missing"
    remote_commit = _ref_commit(root, tracking)
    if not remote_commit:
        if missing_ok:
            return "missing"
        raise ContinuityError(f"fetched ProjectEvent checkpoint has no commit: {ref}")

    status = restore_checkpoint(repo=root, ref=tracking, missing_ok=False)
    if status in {"equal", "restored"}:
        _set_ref(root, ref, remote_commit)
    elif status == "local-ahead":
        # Local events contain the full remote prefix. Re-parent a local checkpoint onto the remote
        # checkpoint so a later push remains a true Git fast-forward.
        _set_ref(root, ref, remote_commit)
        checkpoint_events(repo=root, ref=ref)
    return status


def push_checkpoint(
    *,
    repo: str | Path,
    remote: str = "origin",
    ref: str = DEFAULT_CONTINUITY_REF,
) -> str:
    """Checkpoint current ProjectEvents and push without force; concurrent remote updates fail."""
    root = repo_root(repo)
    commit = checkpoint_events(repo=root, ref=ref)
    output = git(root, "push", remote, f"{ref}:{ref}")
    return output.strip() or commit


__all__ = [
    "DEFAULT_CONTINUITY_REF",
    "checkpoint_events",
    "fetch_checkpoint",
    "pull_checkpoint",
    "push_checkpoint",
    "read_checkpoint",
    "restore_checkpoint",
]
