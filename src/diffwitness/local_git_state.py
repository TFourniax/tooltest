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
    semantics. The marker block is idempotently replaced while every user-owned rule outside it is
    preserved byte-for-byte apart from a final newline normalization.
    """

    repo = Path(repo).resolve()
    path = _git_exclude_path(repo)
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    except OSError as exc:
        raise LocalGitStateError(f"cannot read local Git excludes: {exc}") from exc

    block = _managed_block()
    begin = current.find(_BLOCK_BEGIN)
    end = current.find(_BLOCK_END, begin + len(_BLOCK_BEGIN)) if begin >= 0 else -1
    if begin >= 0 and end >= 0:
        end += len(_BLOCK_END)
        updated = current[:begin] + block + current[end:]
    elif _BLOCK_BEGIN in current or _BLOCK_END in current:
        # A manually damaged marker block must not cause us to delete surrounding user rules.
        updated = current.rstrip("\n") + ("\n" if current else "") + block + "\n"
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
