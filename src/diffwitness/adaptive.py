from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .analysis import AnalysisError, _apply_many, _run_variant_repeated
from .diffing import FilePatch, test_overlay
from .gitops import apply_patch, detached_worktree, git, hard_reset
from .models import Mutation, RepeatedCommandResult


@dataclass(slots=True)
class AdaptiveAttempt:
    kept_ids: list[str]
    classification: str
    apply_error: str | None = None


@dataclass(slots=True)
class AdaptiveCoreResult:
    candidate: RepeatedCommandResult
    baseline: RepeatedCommandResult
    base_tree: str
    candidate_tree: str
    original_mutation_ids: list[str]
    core_mutation_ids: list[str]
    removable_mutation_ids: list[str]
    attempts: int
    budget: int
    budget_exhausted: bool
    one_minimal: bool
    attempts_log: list[AdaptiveAttempt] = field(default_factory=list)

    @property
    def contrast(self) -> bool:
        return self.baseline.failed and self.candidate.passed

    @property
    def reduction_ratio(self) -> float:
        total = len(self.original_mutation_ids)
        return (len(self.removable_mutation_ids) / total) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": "adaptive-core",
            "candidate": self.candidate.to_dict(),
            "baseline_with_candidate_tests": self.baseline.to_dict(),
            "base_tree": self.base_tree,
            "candidate_tree": self.candidate_tree,
            "contrast": self.contrast,
            "original_mutation_ids": self.original_mutation_ids,
            "core_mutation_ids": self.core_mutation_ids,
            "removable_mutation_ids": self.removable_mutation_ids,
            "reduction_ratio": self.reduction_ratio,
            "attempts": self.attempts,
            "budget": self.budget,
            "budget_exhausted": self.budget_exhausted,
            "one_minimal": self.one_minimal,
            "attempts_log": [asdict(attempt) for attempt in self.attempts_log],
            "filesystem_isolation": "reset-before-each-run",
            "claim": (
                "The returned core is 1-minimal under the selected stable, bug-discriminating evidence: "
                "removing any one retained mutation loses the observed stable pass."
                if self.one_minimal
                else "The returned core is a budgeted reduction only; 1-minimality was not established."
            ),
            "non_claim": "Adaptive Core does not claim a globally minimum patch unless a future exhaustive mode explicitly proves one.",
        }


def _partition(items: list[Mutation], count: int) -> list[list[Mutation]]:
    count = max(1, min(count, len(items)))
    q, r = divmod(len(items), count)
    chunks: list[list[Mutation]] = []
    start = 0
    for index in range(count):
        size = q + (1 if index < r else 0)
        chunks.append(items[start : start + size])
        start += size
    return [chunk for chunk in chunks if chunk]


def find_adaptive_core(
    *,
    source_repo: Path,
    base_sha: str,
    candidate_sha: str,
    files: list[FilePatch],
    mutations: list[Mutation],
    test_command: str,
    timeout: float = 300.0,
    prepare_command: str | None = None,
    shared_paths: list[str] | None = None,
    overlay_candidate_tests: bool = True,
    stability_runs: int = 1,
    budget: int = 40,
) -> AdaptiveCoreResult:
    """Find a small, 1-minimal passing subset of the real production patch.

    This is a budgeted delta-debugging style search, restricted to bug-discriminating evidence.
    It is deliberately not advertised as a globally minimum subset. Its sound claim is narrower:
    every removed group was observed to be unnecessary for at least one stable-passing candidate
    subset, and `one_minimal` is true only when no single retained mutation can be removed while
    preserving the selected stable pass.
    """
    if stability_runs < 1:
        raise AnalysisError("stability_runs must be >= 1")
    if budget < 1:
        raise AnalysisError("adaptive budget must be >= 1")

    shared = shared_paths or []
    test_files = {file.path for file in files if file.is_test}
    production = [mutation for mutation in mutations if mutation.path not in test_files]
    overlay = test_overlay(files) if overlay_candidate_tests else ""

    if not production:
        raise AnalysisError("adaptive core search requires at least one production mutation")

    base_tree = git(source_repo, "rev-parse", "--verify", f"{base_sha}^{{tree}}").strip()
    candidate_tree = git(
        source_repo, "rev-parse", "--verify", f"{candidate_sha}^{{tree}}"
    ).strip()

    with detached_worktree(source_repo, candidate_sha, "adaptive-candidate") as candidate_wt:
        candidate_runs = _run_variant_repeated(
            test_command,
            source_repo=source_repo,
            sandbox=candidate_wt,
            timeout=timeout,
            repetitions=stability_runs,
            prepare_command=prepare_command,
            shared_paths=shared,
        )
        if not candidate_runs.passed:
            raise AnalysisError(
                "candidate is not stably green; adaptive causal-core search cannot start"
            )

        with detached_worktree(source_repo, base_sha, "adaptive-base") as base_wt:
            if overlay:
                ok, error = apply_patch(base_wt, overlay, reverse=False)
                if not ok:
                    raise AnalysisError(f"candidate tests could not be overlaid onto base: {error}")
            baseline_runs = _run_variant_repeated(
                test_command,
                source_repo=source_repo,
                sandbox=base_wt,
                timeout=timeout,
                repetitions=stability_runs,
                prepare_command=prepare_command,
                shared_paths=shared,
            )
            if not baseline_runs.failed:
                raise AnalysisError(
                    "adaptive causal-core search requires stable bug-discriminating contrast: "
                    f"base+candidate-tests classified {baseline_runs.classification}, not stable-fail"
                )

            attempts = 0
            log: list[AdaptiveAttempt] = []

            def evaluate(kept: list[Mutation]) -> RepeatedCommandResult | None:
                nonlocal attempts
                if attempts >= budget:
                    return None
                attempts += 1
                hard_reset(base_wt, base_sha, clean_ignored=True)
                if overlay:
                    ok, error = apply_patch(base_wt, overlay, reverse=False)
                    if not ok:
                        raise AnalysisError(f"test overlay stopped applying: {error}")
                ok, error = _apply_many(base_wt, kept, reverse=False)
                if not ok:
                    log.append(
                        AdaptiveAttempt(
                            kept_ids=[mutation.id for mutation in kept],
                            classification="apply-error",
                            apply_error=error,
                        )
                    )
                    return None
                runs = _run_variant_repeated(
                    test_command,
                    source_repo=source_repo,
                    sandbox=base_wt,
                    timeout=timeout,
                    repetitions=stability_runs,
                    prepare_command=prepare_command,
                    shared_paths=shared,
                )
                log.append(
                    AdaptiveAttempt(
                        kept_ids=[mutation.id for mutation in kept],
                        classification=runs.classification,
                    )
                )
                return runs

            rebuilt = evaluate(list(production))
            if rebuilt is None or not rebuilt.passed:
                raise AnalysisError(
                    "the full production mutation set could not reproduce a stable pass from base; "
                    "hunk dependencies or non-production changes prevent adaptive reduction"
                )

            core = list(production)
            granularity = 2

            while len(core) >= 2 and attempts < budget:
                chunks = _partition(core, granularity)
                reduced = False
                for chunk in chunks:
                    chunk_ids = {mutation.id for mutation in chunk}
                    complement = [mutation for mutation in core if mutation.id not in chunk_ids]
                    if not complement:
                        continue
                    runs = evaluate(complement)
                    if runs is not None and runs.passed:
                        core = complement
                        granularity = max(2, granularity - 1)
                        reduced = True
                        break
                    if attempts >= budget:
                        break
                if reduced:
                    continue
                if granularity >= len(core):
                    break
                granularity = min(len(core), granularity * 2)

            one_minimal = False
            changed = True
            while changed and core and attempts < budget:
                changed = False
                checked_all = True
                for mutation in list(core):
                    trial = [item for item in core if item.id != mutation.id]
                    if not trial:
                        continue
                    runs = evaluate(trial)
                    if runs is None:
                        checked_all = False
                        if attempts >= budget:
                            break
                        continue
                    if runs.passed:
                        core = trial
                        changed = True
                        checked_all = False
                        break
                    if not runs.failed:
                        checked_all = False
                if not changed and checked_all:
                    one_minimal = True
                    break

            core_ids = [mutation.id for mutation in core]
            core_set = set(core_ids)
            original_ids = [mutation.id for mutation in production]
            removable_ids = [mutation_id for mutation_id in original_ids if mutation_id not in core_set]
            return AdaptiveCoreResult(
                candidate=candidate_runs,
                baseline=baseline_runs,
                base_tree=base_tree,
                candidate_tree=candidate_tree,
                original_mutation_ids=original_ids,
                core_mutation_ids=core_ids,
                removable_mutation_ids=removable_ids,
                attempts=attempts,
                budget=budget,
                budget_exhausted=attempts >= budget and not one_minimal,
                one_minimal=one_minimal,
                attempts_log=log,
            )