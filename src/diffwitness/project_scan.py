from __future__ import annotations

from pathlib import Path

from .debt_models import DebtReport
from .debt_scan import scan_project as _scan_project
from .gitops import detached_worktree, snapshot_worktree


def scan_project(
    *,
    repo: Path,
    duplicate_scan: bool = True,
    max_scan_files: int = 500,
    max_duplicate_signals: int = 20,
) -> DebtReport:
    """Scan an immutable snapshot of the current worktree.

    Debt health is frequently run before a commit exists. The low-level scanner reads files from
    the repository it is given and historically labelled those bytes with that repository's HEAD.
    On a dirty worktree this could make provenance claim HEAD while actually inspecting different
    content. Snapshot first, then scan a detached worktree of exactly that snapshot so every signal
    is bound to the tree that was really analysed.
    """
    candidate_sha = snapshot_worktree(repo)
    with detached_worktree(repo, candidate_sha, "debt-health-snapshot") as snapshot:
        report = _scan_project(
            repo=snapshot,
            duplicate_scan=duplicate_scan,
            max_scan_files=max_scan_files,
            max_duplicate_signals=max_duplicate_signals,
        )
    report.repo = str(repo)
    report.metadata = {
        **report.metadata,
        "scan_source": "worktree-snapshot",
        "snapshot_sha": candidate_sha,
    }
    return report
