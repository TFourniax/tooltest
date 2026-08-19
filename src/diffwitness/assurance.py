from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .analysis import AnalysisError, _run_variant_repeated
from .diffing import FilePatch, test_overlay
from .gitops import apply_patch, detached_worktree, git


FILESYSTEM_ISOLATION = "reset-before-each-run"


def build_assurance(
    *,
    source_repo: Path,
    base_sha: str,
    candidate_sha: str,
    candidate_ref: str,
    files: list[FilePatch],
    test_command: str,
    stability_runs: int,
    timeout: float,
    prepare_command: str | None,
    shared_paths: list[str],
    overlay_candidate_tests: bool,
) -> dict[str, Any]:
    """Probe base/candidate behavior before choosing a causal proof strategy.

    This deliberately separates preservation assurance from causal repair evidence. When base and
    candidate both pass and tests did not change, the selected suite supports preservation but not
    necessity. When candidate tests changed yet base still passes after overlay, those tests are
    explicitly non-discriminating rather than silently treated as regression proof.
    """
    if stability_runs < 1:
        raise AnalysisError("stability_runs must be >= 1")

    base_tree = git(source_repo, "rev-parse", "--verify", f"{base_sha}^{{tree}}").strip()
    candidate_tree = git(
        source_repo, "rev-parse", "--verify", f"{candidate_sha}^{{tree}}"
    ).strip()
    overlay = test_overlay(files) if overlay_candidate_tests else ""
    test_files = sorted(file.path for file in files if file.is_test)

    with detached_worktree(source_repo, candidate_sha, "assurance-candidate") as candidate_wt:
        candidate_runs = _run_variant_repeated(
            test_command,
            source_repo=source_repo,
            sandbox=candidate_wt,
            timeout=timeout,
            repetitions=stability_runs,
            prepare_command=prepare_command,
            shared_paths=shared_paths,
        )

    with detached_worktree(source_repo, base_sha, "assurance-base") as base_wt:
        if overlay:
            ok, error = apply_patch(base_wt, overlay, reverse=False)
            if not ok:
                raise AnalysisError(
                    "candidate test changes could not be overlaid onto base during assurance probe: "
                    + error
                )
        baseline_runs = _run_variant_repeated(
            test_command,
            source_repo=source_repo,
            sandbox=base_wt,
            timeout=timeout,
            repetitions=stability_runs,
            prepare_command=prepare_command,
            shared_paths=shared_paths,
        )

    if candidate_runs.passed and baseline_runs.failed:
        classification = "causal-contrast"
        claim = "Base+candidate-tests stably fails while the candidate stably passes; causal patch analysis is applicable."
    elif candidate_runs.passed and baseline_runs.passed and not test_files:
        classification = "preservation-evidence"
        claim = "The selected evidence is stably green on both base and candidate with no changed test surface; it supports behavior preservation under that evidence, not hunk necessity."
    elif candidate_runs.passed and baseline_runs.passed and test_files:
        classification = "non-discriminating-change"
        claim = "Candidate tests are stably green on both base and candidate; they do not discriminate the production change."
    elif not candidate_runs.passed:
        classification = "candidate-not-stable-green"
        claim = "The candidate is not stably green under the selected evidence."
    else:
        classification = "assurance-inconclusive"
        claim = "The selected evidence is unstable or timed out on the base, so preservation or causal contrast cannot be established."

    stable = {
        "base_sha": base_sha,
        "base_tree": base_tree,
        "candidate_sha": candidate_sha,
        "candidate_tree": candidate_tree,
        "candidate_ref": candidate_ref,
        "test_command": test_command,
        "test_files": test_files,
        "candidate_run": candidate_runs.to_dict(),
        "baseline_run": baseline_runs.to_dict(),
        "classification": classification,
        "prepare": prepare_command,
        "timeout": timeout,
        "stability_runs": stability_runs,
        "shared_paths": sorted(shared_paths),
        "test_overlay": overlay_candidate_tests,
        "filesystem_isolation": FILESYSTEM_ISOLATION,
    }
    encoded = json.dumps(
        stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    certificate_id = "dwa1_" + hashlib.sha256(encoded).hexdigest()[:20]
    return {
        "schema_version": "assurance-1",
        "tool": "diffwitness",
        "certificate_id": certificate_id,
        "outcome": "assurance",
        "classification": classification,
        "base": {"sha": base_sha, "tree": base_tree},
        "candidate": {"ref": candidate_ref, "sha": candidate_sha, "tree": candidate_tree},
        "test_command": test_command,
        "changed_test_files": test_files,
        "candidate_run": candidate_runs.to_dict(),
        "baseline_with_candidate_tests_run": baseline_runs.to_dict(),
        "execution": {
            "prepare": prepare_command,
            "timeout": timeout,
            "stability_runs": stability_runs,
            "share": sorted(shared_paths),
            "test_overlay": overlay_candidate_tests,
            "filesystem_isolation": FILESYSTEM_ISOLATION,
        },
        "claim": claim,
        "non_claim": "Assurance mode does not establish real-hunk necessity or global program correctness.",
        "summary": {
            "mutations": 0,
            "witnessed": 0,
            "unwitnessed": 0,
            "inconclusive": 0 if classification in {"causal-contrast", "preservation-evidence", "non-discriminating-change"} else 1,
            "surplus_candidate_hunks": 0,
        },
    }


def assurance_policy(report: dict[str, Any], policy: str) -> tuple[bool, str]:
    classification = report.get("classification")
    if policy == "observe":
        return True, "observe policy records assurance without blocking"
    if classification == "preservation-evidence":
        if policy == "strict":
            return False, "strict policy requires causal contrast; preservation assurance is intentionally weaker"
        return True, "balanced policy accepts stable preservation assurance"
    if classification == "non-discriminating-change":
        return False, "changed tests do not discriminate the production change from base"
    if classification == "candidate-not-stable-green":
        return False, "candidate is not stably green"
    if classification == "assurance-inconclusive":
        return False, "base evidence is unstable or timed out"
    if classification == "causal-contrast":
        return True, "causal analysis should continue"
    return False, f"unknown assurance classification: {classification}"


def render_assurance_markdown(report: dict[str, Any]) -> str:
    files = "\n".join(f"- `{path}`" for path in report.get("changed_test_files") or []) or "- none"
    return (
        "# DiffWitness assurance certificate\n\n"
        f"**Certificate:** `{report['certificate_id']}`  \n"
        f"**Classification:** `{report['classification']}`  \n"
        f"**Candidate:** `{report['candidate_run']['classification']}`  \n"
        f"**Base + candidate tests:** `{report['baseline_with_candidate_tests_run']['classification']}`\n\n"
        "## Changed test files\n\n"
        f"{files}\n\n"
        "## Claim boundary\n\n"
        f"{report['claim']}\n\n{report['non_claim']}\n"
    )