from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .analysis import _prepare_sandbox
from .gitops import detached_worktree
from .runner import run_repeated


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
) -> dict[str, Any]:
    with detached_worktree(source_repo, candidate_sha, "validation-only") as worktree:
        _prepare_sandbox(
            source_repo=source_repo,
            sandbox=worktree,
            prepare_command=prepare_command,
            timeout=timeout,
            shared_paths=shared_paths,
        )
        runs = run_repeated(
            test_command,
            cwd=worktree,
            source_repo=source_repo,
            timeout=timeout,
            repetitions=stability_runs,
        )

    stable = {
        "base_sha": base_sha,
        "candidate_sha": candidate_sha,
        "test_command": test_command,
        "test_files": sorted(test_files),
        "runs": runs.to_dict(),
        "prepare": prepare_command,
        "timeout": timeout,
        "stability_runs": stability_runs,
        "shared_paths": sorted(shared_paths),
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
        "base": {"sha": base_sha},
        "candidate": {"ref": candidate_ref, "sha": candidate_sha},
        "test_command": test_command,
        "changed_test_files": sorted(test_files),
        "candidate_run": runs.to_dict(),
        "execution": {
            "prepare": prepare_command,
            "timeout": timeout,
            "stability_runs": stability_runs,
            "share": sorted(shared_paths),
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
        f"**Candidate:** `{report['candidate']['sha']}`  \n"
        f"**Evidence:** `{report['test_command']}`  \n"
        f"**Classification:** `{run['classification']}`\n\n"
        "## Changed test files\n\n"
        f"{files}\n\n"
        "## Claim boundary\n\n"
        f"{report['claim']}\n\n{report['non_claim']}\n"
    )
