from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .analysis import _run_variant_repeated
from .gitops import detached_worktree, git
from .runner import wall_clock_budgeted


@wall_clock_budgeted
def build_validation_only(
    *,
    source_repo: Path,
    base_sha: str,
    candidate_sha: str,
    candidate_ref: str,
    test_command: str,
    test_files: list[str],
    stability_runs: int,
    timeout: float,
    prepare_command: str | None,
    shared_paths: list[str],
    max_total_seconds: float | None = None,
) -> dict[str, Any]:
    base_tree = git(source_repo, "rev-parse", "--verify", f"{base_sha}^{{tree}}").strip()
    candidate_tree = git(
        source_repo, "rev-parse", "--verify", f"{candidate_sha}^{{tree}}"
    ).strip()

    with detached_worktree(source_repo, candidate_sha, "validation-only") as worktree:
        runs = _run_variant_repeated(
            test_command,
            source_repo=source_repo,
            sandbox=worktree,
            timeout=timeout,
            repetitions=stability_runs,
            prepare_command=prepare_command,
            shared_paths=shared_paths,
        )

    stable = {
        "base_sha": base_sha,
        "base_tree": base_tree,
        "candidate_sha": candidate_sha,
        "candidate_tree": candidate_tree,
        "test_command": test_command,
        "test_files": sorted(test_files),
        "runs": runs.to_dict(),
        "prepare": prepare_command,
        "timeout": timeout,
        "max_total_seconds": max_total_seconds,
        "stability_runs": stability_runs,
        "shared_paths": sorted(shared_paths),
        "filesystem_isolation": "reset-before-each-run",
    }
    encoded = json.dumps(
        stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    certificate_id = "dwv1_" + hashlib.sha256(encoded).hexdigest()[:20]
    return {
        "schema_version": "validation-1",
        "tool": "diffwitness",
        "certificate_id": certificate_id,
        "outcome": "validation-only",
        "base": {"sha": base_sha, "tree": base_tree},
        "candidate": {"ref": candidate_ref, "sha": candidate_sha, "tree": candidate_tree},
        "test_command": test_command,
        "changed_test_files": sorted(test_files),
        "candidate_run": runs.to_dict(),
        "execution": {
            "prepare": prepare_command,
            "timeout": timeout,
            "max_total_seconds": max_total_seconds,
            "stability_runs": stability_runs,
            "share": sorted(shared_paths),
            "filesystem_isolation": "reset-before-each-run",
        },
        "valid": runs.passed,
        "summary": {
            "mutations": 0,
            "witnessed": 0,
            "unwitnessed": 0,
            "inconclusive": 0 if runs.passed or runs.failed else 1,
            "surplus_candidate_hunks": 0,
        },
        "claim": (
            "The changed test surface is stably green on the candidate under the selected evidence command."
            if runs.passed
            else "The changed test surface is not stably green on the candidate under the selected evidence command."
        ),
        "non_claim": "No production-code causal attribution was made because the diff contains no analyzed production mutation.",
    }


def render_validation_markdown(report: dict[str, Any]) -> str:
    run = report["candidate_run"]
    files = "\n".join(f"- `{path}`" for path in report["changed_test_files"]) or "- none"
    return (
        "# DiffWitness validation-only certificate\n\n"
        f"**Certificate:** `{report['certificate_id']}`  \n"
        f"**Candidate tree:** `{report['candidate'].get('tree', 'unknown')}`  \n"
        f"**Evidence:** `{report['test_command']}`  \n"
        f"**Classification:** `{run['classification']}`\n\n"
        "## Changed test files\n\n"
        f"{files}\n\n"
        "## Claim boundary\n\n"
        f"{report['claim']}\n\n{report['non_claim']}\n"
    )