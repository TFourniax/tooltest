from __future__ import annotations

import subprocess
from pathlib import Path


_BLOCK_BEGIN = "# >>> DiffWitness local integration >>>"
_BLOCK_END = "# <<< DiffWitness local integration <<<"
_LOCAL_PATTERNS = (
    ".idleproof/",
    ".claude/settings.local.json",
    ".codex/hooks.json",
    ".cursor/hooks.json",
    ".cursor/rules/idleproof-continuity.mdc",
)


class LocalGitStateError(RuntimeError):
    pass


def _git_exclude_path(repo: Path) -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise LocalGitStateError("cannot resolve the repository-local Git exclude file")
    path = Path(proc.stdout.strip())
    return path if path.is_absolute() else (repo / path).resolve()


def _managed_block() -> str:
    return "\n".join((_BLOCK_BEGIN, *_LOCAL_PATTERNS, _BLOCK_END))


def ensure_local_integration_excludes(repo: Path) -> Path:
    """Hide DiffWitness machine-local plumbing without editing the project's `.gitignore`.

    Git's `info/exclude` is repository-local metadata. It does not affect files that are already
    tracked, so a repository that intentionally versions a similarly named path keeps normal Git
    semantics. A single well-formed managed block is replaced idempotently and user-owned rules
    outside it are preserved. Damaged/duplicated markers fail closed instead of guessing.
    """

    repo = Path(repo).resolve()
    path = _git_exclude_path(repo)
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    except OSError as exc:
        raise LocalGitStateError(f"cannot read local Git excludes: {exc}") from exc

    begin_count = current.count(_BLOCK_BEGIN)
    end_count = current.count(_BLOCK_END)
    if (begin_count, end_count) not in {(0, 0), (1, 1)}:
        raise LocalGitStateError(
            "DiffWitness marker block in Git info/exclude is damaged or duplicated; repair the marker lines before retrying"
        )

    block = _managed_block()
    if begin_count == 1:
        begin = current.find(_BLOCK_BEGIN)
        end = current.find(_BLOCK_END)
        if begin < 0 or end < begin:
            raise LocalGitStateError(
                "DiffWitness marker block in Git info/exclude is malformed; repair the marker lines before retrying"
            )
        end += len(_BLOCK_END)
        updated = current[:begin] + block + current[end:]
    else:
        updated = current.rstrip("\n") + ("\n" if current else "") + block + "\n"

    if not updated.endswith("\n"):
        updated += "\n"
    if updated == current:
        return path

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        staged = path.with_name(path.name + ".diffwitness.tmp")
        staged.write_text(updated, encoding="utf-8", newline="\n")
        staged.replace(path)
    except OSError as exc:
        raise LocalGitStateError(f"cannot update local Git excludes: {exc}") from exc
    return path


__all__ = ["LocalGitStateError", "ensure_local_integration_excludes"]
