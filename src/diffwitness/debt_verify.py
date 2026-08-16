from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analysis import AnalysisError, _prepare_sandbox
from .debt_scan import scan_project
from .diffing import parse_file_patches, test_overlay
from .gitops import apply_patch, detached_worktree, diff_text, git, hard_reset, snapshot_worktree
from .ledger import LedgerItem
from .runner import run_repeated


@dataclass(slots=True)
class RecheckResult:
    debt_id: str
    status: str
    reason: str
    verification: dict[str, Any]

    @property
    def resolved(self) -> bool:
        return self.status == "resolved"

    def to_dict(self) -> dict[str, Any]:
        return {"debt_id": self.debt_id, "status": self.status, "reason": self.reason, "verification": self.verification}


def _commit_exists(repo: Path, sha: str) -> bool:
    return bool(git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}", check=False).strip())


def recheck_mutation_necessity(item: LedgerItem, *, repo: Path, current_sha: str, test_command: str,
                               stability_runs: int, timeout: float, prepare_command: str | None,
                               shared_paths: list[str]) -> RecheckResult:
    patch = item.verification.get("mutation_patch")
    if not isinstance(patch, str) or not patch.strip():
        return RecheckResult(item.debt_id, "inconclusive", "stored debt lineage has no mutation patch to replay", {"type": "mutation-necessity", "result": "missing-patch"})
    with detached_worktree(repo, current_sha, "debt-current") as worktree:
        _prepare_sandbox(source_repo=repo, sandbox=worktree, prepare_command=prepare_command, timeout=timeout, shared_paths=shared_paths)
        current_runs = run_repeated(test_command, cwd=worktree, source_repo=repo, timeout=timeout, repetitions=stability_runs)
        if not current_runs.passed:
            return RecheckResult(item.debt_id, "inconclusive", f"current candidate is {current_runs.classification}; necessity replay requires stable-pass", {"type": "mutation-necessity", "current": current_runs.to_dict()})
        reverse_ok, reverse_error = apply_patch(worktree, patch, reverse=True)
        if reverse_ok:
            _prepare_sandbox(source_repo=repo, sandbox=worktree, prepare_command=prepare_command, timeout=timeout, shared_paths=shared_paths)
            without_runs = run_repeated(test_command, cwd=worktree, source_repo=repo, timeout=timeout, repetitions=stability_runs)
            verification = {"type": "mutation-necessity", "result": "reverse-applied", "current": current_runs.to_dict(), "without_mutation": without_runs.to_dict()}
            if without_runs.failed:
                return RecheckResult(item.debt_id, "resolved", "the stored mutation is now behaviorally witnessed: removing it makes current evidence stably fail", verification)
            if without_runs.passed:
                return RecheckResult(item.debt_id, "open", "the stored mutation remains removable under current evidence", verification)
            return RecheckResult(item.debt_id, "inconclusive", f"evidence without the mutation is {without_runs.classification}", verification)
        hard_reset(worktree, current_sha)
        forward_ok, forward_error = apply_patch(worktree, patch, reverse=False)
        verification = {"type": "mutation-necessity", "result": "patch-shape-changed", "current": current_runs.to_dict(), "reverse_error": reverse_error, "forward_applies": forward_ok, "forward_error": forward_error}
        if forward_ok:
            return RecheckResult(item.debt_id, "resolved", "the original debt-carrying mutation is no longer present in the current stable-green candidate", verification)
        return RecheckResult(item.debt_id, "inconclusive", "current code diverged from both sides of the stored mutation patch; exact lineage replay is no longer possible", verification)


def _overlay_current_tests(repo: Path, source_sha: str, current_sha: str) -> str:
    return test_overlay(parse_file_patches(diff_text(repo, source_sha, current_sha)))


def recheck_discrimination(item: LedgerItem, *, repo: Path, current_sha: str, test_command: str,
                           stability_runs: int, timeout: float, prepare_command: str | None,
                           shared_paths: list[str]) -> RecheckResult:
    base_sha = str(item.verification.get("origin_base_sha") or "")
    candidate_sha = str(item.verification.get("origin_candidate_sha") or "")
    if not base_sha or not candidate_sha:
        return RecheckResult(item.debt_id, "inconclusive", "historical discrimination debt lacks introducing base/candidate SHAs", {"type": "historical-discrimination", "result": "missing-origin"})
    if not _commit_exists(repo, base_sha) or not _commit_exists(repo, candidate_sha):
        return RecheckResult(item.debt_id, "inconclusive", "historical base/candidate commits are unavailable in this clone", {"type": "historical-discrimination", "result": "origin-unavailable"})
    base_overlay = _overlay_current_tests(repo, base_sha, current_sha)
    candidate_overlay = _overlay_current_tests(repo, candidate_sha, current_sha)

    def run_historical(sha: str, overlay: str, label: str):
        with detached_worktree(repo, sha, label) as worktree:
            if overlay:
                ok, error = apply_patch(worktree, overlay, reverse=False)
                if not ok:
                    raise AnalysisError(f"current test surface could not be overlaid onto {label}: {error}")
            _prepare_sandbox(source_repo=repo, sandbox=worktree, prepare_command=prepare_command, timeout=timeout, shared_paths=shared_paths)
            return run_repeated(test_command, cwd=worktree, source_repo=repo, timeout=timeout, repetitions=stability_runs)
    try:
        base_runs = run_historical(base_sha, base_overlay, "debt-origin-base")
        candidate_runs = run_historical(candidate_sha, candidate_overlay, "debt-origin-candidate")
    except AnalysisError as exc:
        return RecheckResult(item.debt_id, "inconclusive", str(exc), {"type": "historical-discrimination", "result": "overlay-error"})
    verification = {"type": "historical-discrimination", "origin_base_sha": base_sha, "origin_candidate_sha": candidate_sha, "current_sha": current_sha,
                    "base_with_current_tests": base_runs.to_dict(), "candidate_with_current_tests": candidate_runs.to_dict()}
    if base_runs.failed and candidate_runs.passed:
        return RecheckResult(item.debt_id, "resolved", "current tests now discriminate the introducing candidate from its historical base", verification)
    if base_runs.passed and candidate_runs.passed:
        return RecheckResult(item.debt_id, "open", "current tests still pass on both the historical base and introducing candidate", verification)
    return RecheckResult(item.debt_id, "inconclusive", "historical replay did not produce stable base-fail/candidate-pass contrast", verification)


def recheck_project_rule(item: LedgerItem, *, repo: Path, duplicate_scan: bool, max_scan_files: int, max_duplicate_signals: int) -> RecheckResult:
    report = scan_project(repo=repo, duplicate_scan=duplicate_scan, max_scan_files=max_scan_files, max_duplicate_signals=max_duplicate_signals)
    active = {signal.debt_id: signal for signal in report.signals}
    if item.debt_id not in active:
        return RecheckResult(item.debt_id, "resolved", "the project rule no longer reproduces on current tracked source", {"type": "project-rule", "result": "absent", "current_sha": report.candidate_sha})
    return RecheckResult(item.debt_id, "open", "the project rule still reproduces", {"type": "project-rule", "result": "present", "signal": active[item.debt_id].to_dict()})


def recheck_item(item: LedgerItem, *, repo: Path, current_sha: str | None = None, test_command: str | None = None,
                 stability_runs: int = 2, timeout: float = 300.0, prepare_command: str | None = None,
                 shared_paths: list[str] | None = None, duplicate_scan: bool = True, max_scan_files: int = 500,
                 max_duplicate_signals: int = 20) -> RecheckResult:
    verification_type = str(item.verification.get("type") or "")
    current = current_sha or snapshot_worktree(repo)
    shared = list(shared_paths or [])
    if verification_type == "project-rule":
        return recheck_project_rule(item, repo=repo, duplicate_scan=duplicate_scan, max_scan_files=max_scan_files, max_duplicate_signals=max_duplicate_signals)
    if verification_type == "mutation-necessity":
        if not test_command:
            return RecheckResult(item.debt_id, "inconclusive", "mutation replay requires an evidence command", {"type": verification_type, "result": "missing-evidence-command"})
        return recheck_mutation_necessity(item, repo=repo, current_sha=current, test_command=test_command, stability_runs=stability_runs, timeout=timeout, prepare_command=prepare_command, shared_paths=shared)
    if verification_type == "historical-discrimination":
        if not test_command:
            return RecheckResult(item.debt_id, "inconclusive", "historical test replay requires an evidence command", {"type": verification_type, "result": "missing-evidence-command"})
        return recheck_discrimination(item, repo=repo, current_sha=current, test_command=test_command, stability_runs=stability_runs, timeout=timeout, prepare_command=prepare_command, shared_paths=shared)
    return RecheckResult(item.debt_id, "inconclusive", f"no automatic recheck adapter exists for verification type {verification_type!r}", {"type": verification_type or "unknown", "result": "unsupported"})
