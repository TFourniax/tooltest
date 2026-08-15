from __future__ import annotations

import itertools
import math
from pathlib import Path

from .diffing import FilePatch, test_overlay
from .gitops import apply_patch, candidate_delta, detached_worktree, hard_reset
from .models import (
    AnalysisOutcome,
    CommandResult,
    Mutation,
    MutationResult,
    SearchSummary,
    SubsetResult,
)
from .runner import run_command, run_repeated


class AnalysisError(RuntimeError):
    pass


def _ensure_shared(source_repo: Path, sandbox: Path, shared_paths: list[str]) -> None:
    for raw in shared_paths:
        rel = Path(raw)
        if rel.is_absolute() or ".." in rel.parts:
            raise AnalysisError(f"--share must be a repo-relative path: {raw}")
        source = source_repo / rel
        target = sandbox / rel
        if not source.exists():
            raise AnalysisError(f"shared path does not exist in source repo: {raw}")
        if target.exists() or target.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.symlink_to(source, target_is_directory=source.is_dir())
        except OSError as exc:
            raise AnalysisError(f"could not link shared path {raw}: {exc}") from exc


def _prepare_sandbox(
    *,
    source_repo: Path,
    sandbox: Path,
    prepare_command: str | None,
    timeout: float,
    shared_paths: list[str],
) -> CommandResult | None:
    _ensure_shared(source_repo, sandbox, shared_paths)
    if not prepare_command:
        return None
    result = run_command(prepare_command, cwd=sandbox, source_repo=source_repo, timeout=timeout)
    if not result.passed:
        raise AnalysisError(
            "prepare command failed in isolated worktree\n"
            f"stderr tail:\n{result.stderr_tail}"
        )
    return result


def _reset_and_prepare(
    *,
    source_repo: Path,
    sandbox: Path,
    commit: str,
    prepare_command: str | None,
    timeout: float,
    shared_paths: list[str],
) -> None:
    hard_reset(sandbox, commit)
    _prepare_sandbox(
        source_repo=source_repo,
        sandbox=sandbox,
        prepare_command=prepare_command,
        timeout=timeout,
        shared_paths=shared_paths,
    )


def _status_from_runs(runs) -> str:
    if runs.failed:
        return "witnessed"
    if runs.passed:
        return "unwitnessed"
    return "inconclusive"


def _apply_many(worktree: Path, mutations: tuple[Mutation, ...] | list[Mutation], *, reverse: bool) -> tuple[bool, str]:
    for mutation in mutations:
        ok, error = apply_patch(worktree, mutation.patch, reverse=reverse)
        if not ok:
            return False, f"{mutation.id}: {error}"
    return True, ""


def run_analysis(
    *,
    source_repo: Path,
    base_sha: str,
    candidate_sha: str,
    files: list[FilePatch],
    mutations: list[Mutation],
    test_command: str,
    timeout: float,
    prepare_command: str | None,
    shared_paths: list[str],
    overlay_candidate_tests: bool,
    minimize: bool,
    stability_runs: int = 1,
    search_sufficient: bool = True,
    max_subset_order: int = 3,
    max_subset_runs: int = 32,
    search_interactions: bool = True,
    max_interaction_runs: int = 20,
) -> AnalysisOutcome:
    if stability_runs < 1:
        raise AnalysisError("--stability-runs must be >= 1")
    if max_subset_order < 1:
        raise AnalysisError("--max-subset-order must be >= 1")

    overlay = test_overlay(files) if overlay_candidate_tests else ""
    all_test_file_set = {file.path for file in files if file.is_test}
    test_files = sorted(all_test_file_set) if overlay_candidate_tests else []
    production_mutations = [m for m in mutations if m.path not in all_test_file_set]

    sufficient = SearchSummary(enabled=search_sufficient, budget=max_subset_runs)
    interactions = SearchSummary(enabled=search_interactions, budget=max_interaction_runs)

    with detached_worktree(source_repo, candidate_sha, "candidate") as candidate_wt:
        _prepare_sandbox(
            source_repo=source_repo,
            sandbox=candidate_wt,
            prepare_command=prepare_command,
            timeout=timeout,
            shared_paths=shared_paths,
        )
        candidate_runs = run_repeated(
            test_command,
            cwd=candidate_wt,
            source_repo=source_repo,
            timeout=timeout,
            repetitions=stability_runs,
        )
        if not candidate_runs.passed:
            raise AnalysisError(
                "candidate is not stably green under the selected test command; hunk evidence cannot be interpreted\n"
                f"classification: {candidate_runs.classification}"
            )

        with detached_worktree(source_repo, base_sha, "base") as base_wt:
            if overlay:
                ok, error = apply_patch(base_wt, overlay, reverse=False)
                if not ok:
                    raise AnalysisError(
                        "candidate test changes could not be overlaid onto the base. "
                        "Retry with --no-test-overlay if this project keeps tests inline with production code.\n"
                        f"git apply: {error}"
                    )
            _prepare_sandbox(
                source_repo=source_repo,
                sandbox=base_wt,
                prepare_command=prepare_command,
                timeout=timeout,
                shared_paths=shared_paths,
            )
            baseline_runs = run_repeated(
                test_command,
                cwd=base_wt,
                source_repo=source_repo,
                timeout=timeout,
                repetitions=stability_runs,
            )

            mutation_results: list[MutationResult] = []
            for mutation in mutations:
                _reset_and_prepare(
                    source_repo=source_repo,
                    sandbox=candidate_wt,
                    commit=candidate_sha,
                    prepare_command=prepare_command,
                    timeout=timeout,
                    shared_paths=shared_paths,
                )
                ok, error = apply_patch(candidate_wt, mutation.patch, reverse=True)
                if not ok:
                    mutation_results.append(
                        MutationResult(mutation=mutation, status="inconclusive", apply_error=error)
                    )
                    continue
                runs = run_repeated(
                    test_command,
                    cwd=candidate_wt,
                    source_repo=source_repo,
                    timeout=timeout,
                    repetitions=stability_runs,
                )
                mutation_results.append(
                    MutationResult(mutation=mutation, status=_status_from_runs(runs), runs=runs)
                )

            # Counterfactual sufficiency: start from base+candidate-tests, then add small
            # subsets of the real production hunks. The first cardinality that turns
            # the baseline stably green is a minimal-cardinality evidence core.
            if search_sufficient:
                if not baseline_runs.failed:
                    sufficient.note = (
                        "Skipped: sufficiency requires a stable-failing base with candidate tests overlaid."
                    )
                elif not production_mutations:
                    sufficient.note = "Skipped: no production mutations to search."
                else:
                    max_order = min(max_subset_order, len(production_mutations))
                    budget_exhausted = False
                    for order in range(1, max_order + 1):
                        combos = list(itertools.combinations(production_mutations, order))
                        completed_this_order = 0
                        found_this_order: list[SubsetResult] = []
                        for combo in combos:
                            if sufficient.attempted >= max_subset_runs:
                                budget_exhausted = True
                                break
                            sufficient.attempted += 1
                            completed_this_order += 1
                            hard_reset(base_wt, base_sha)
                            if overlay:
                                ok, error = apply_patch(base_wt, overlay, reverse=False)
                                if not ok:
                                    raise AnalysisError(f"test overlay stopped applying during subset search: {error}")
                            ok, error = _apply_many(base_wt, combo, reverse=False)
                            if not ok:
                                continue
                            _prepare_sandbox(
                                source_repo=source_repo,
                                sandbox=base_wt,
                                prepare_command=prepare_command,
                                timeout=timeout,
                                shared_paths=shared_paths,
                            )
                            runs = run_repeated(
                                test_command,
                                cwd=base_wt,
                                source_repo=source_repo,
                                timeout=timeout,
                                repetitions=stability_runs,
                            )
                            if runs.passed:
                                found_this_order.append(
                                    SubsetResult(
                                        mutation_ids=[m.id for m in combo],
                                        mutation_labels=[m.label for m in combo],
                                        status="sufficient",
                                        runs=runs,
                                    )
                                )
                            elif runs.inconclusive:
                                sufficient.results.append(
                                    SubsetResult(
                                        mutation_ids=[m.id for m in combo],
                                        mutation_labels=[m.label for m in combo],
                                        status="inconclusive",
                                        runs=runs,
                                    )
                                )
                        if found_this_order:
                            sufficient.found_order = order
                            sufficient.results.extend(found_this_order)
                            sufficient.exhaustive_at_found_order = completed_this_order == len(combos)
                            break
                        if budget_exhausted:
                            break
                    if sufficient.found_order is None:
                        total_within_order = sum(
                            math.comb(len(production_mutations), order)
                            for order in range(1, min(max_subset_order, len(production_mutations)) + 1)
                        )
                        if sufficient.attempted < min(total_within_order, max_subset_runs):
                            sufficient.note = "No applicable sufficient subset was found."
                        elif sufficient.attempted >= max_subset_runs and total_within_order > max_subset_runs:
                            sufficient.note = "No sufficient subset found before the search budget was exhausted."
                        else:
                            sufficient.note = "No sufficient subset found within the configured maximum order."

            # Hidden redundancy: A and B can each look unwitnessed alone, yet removing
            # both can break the evidence. Surface those mutual-backup pairs explicitly.
            if search_interactions:
                unwitnessed = [
                    result.mutation
                    for result in mutation_results
                    if result.status == "unwitnessed" and result.mutation in production_mutations
                ]
                if len(unwitnessed) < 2:
                    interactions.note = "No pair search needed: fewer than two unwitnessed production hunks."
                else:
                    pairs = list(itertools.combinations(unwitnessed, 2))
                    completed = 0
                    for pair in pairs:
                        if interactions.attempted >= max_interaction_runs:
                            break
                        interactions.attempted += 1
                        completed += 1
                        hard_reset(candidate_wt, candidate_sha)
                        ok, error = _apply_many(candidate_wt, pair, reverse=True)
                        if not ok:
                            continue
                        _prepare_sandbox(
                            source_repo=source_repo,
                            sandbox=candidate_wt,
                            prepare_command=prepare_command,
                            timeout=timeout,
                            shared_paths=shared_paths,
                        )
                        runs = run_repeated(
                            test_command,
                            cwd=candidate_wt,
                            source_repo=source_repo,
                            timeout=timeout,
                            repetitions=stability_runs,
                        )
                        if runs.failed:
                            interactions.results.append(
                                SubsetResult(
                                    mutation_ids=[m.id for m in pair],
                                    mutation_labels=[m.label for m in pair],
                                    status="mutual-backup",
                                    runs=runs,
                                )
                            )
                        elif runs.inconclusive:
                            interactions.results.append(
                                SubsetResult(
                                    mutation_ids=[m.id for m in pair],
                                    mutation_labels=[m.label for m in pair],
                                    status="inconclusive",
                                    runs=runs,
                                )
                            )
                    interactions.exhaustive_at_found_order = completed == len(pairs)
                    interactions.found_order = 2 if interactions.results else None
                    if not interactions.results:
                        interactions.note = (
                            "No mutual-backup pair found within the interaction search budget."
                        )

            removed_ids: list[str] | None = None
            reduction_patch: str | None = None
            if minimize:
                removed: list[Mutation] = []
                # Prefer hunks already shown to be individually unnecessary.
                status_by_id = {r.mutation.id: r.status for r in mutation_results}
                ordered = sorted(
                    production_mutations,
                    key=lambda m: {"unwitnessed": 0, "inconclusive": 1, "witnessed": 2}.get(
                        status_by_id.get(m.id, "inconclusive"), 1
                    ),
                )
                for mutation in ordered:
                    hard_reset(candidate_wt, candidate_sha)
                    ok, _ = _apply_many(candidate_wt, [*removed, mutation], reverse=True)
                    if not ok:
                        continue
                    _prepare_sandbox(
                        source_repo=source_repo,
                        sandbox=candidate_wt,
                        prepare_command=prepare_command,
                        timeout=timeout,
                        shared_paths=shared_paths,
                    )
                    runs = run_repeated(
                        test_command,
                        cwd=candidate_wt,
                        source_repo=source_repo,
                        timeout=timeout,
                        repetitions=stability_runs,
                    )
                    if runs.passed:
                        removed.append(mutation)

                hard_reset(candidate_wt, candidate_sha)
                applied_removed: list[Mutation] = []
                for mutation in removed:
                    ok, _ = apply_patch(candidate_wt, mutation.patch, reverse=True)
                    if ok:
                        applied_removed.append(mutation)
                removed_ids = [m.id for m in applied_removed]
                reduction_patch = candidate_delta(candidate_wt, candidate_sha) if applied_removed else ""

    return AnalysisOutcome(
        candidate=candidate_runs,
        baseline=baseline_runs,
        mutation_results=mutation_results,
        test_files=test_files,
        sufficient_search=sufficient,
        interaction_search=interactions,
        minimized_removed_ids=removed_ids,
        reduction_patch=reduction_patch,
    )
