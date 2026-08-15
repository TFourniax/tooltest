from __future__ import annotations

from pathlib import Path

from .diffing import FilePatch, make_mutations, test_overlay
from .gitops import apply_patch, candidate_delta, detached_worktree, hard_reset
from .models import CommandResult, Mutation, MutationResult
from .runner import run_command


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
) -> tuple[CommandResult, CommandResult, list[MutationResult], list[str], list[str] | None, str | None]:
    overlay = test_overlay(files) if overlay_candidate_tests else ""
    overlaid_test_files = [file.path for file in files if file.is_test] if overlay_candidate_tests else []

    with detached_worktree(source_repo, candidate_sha, "candidate") as candidate_wt:
        _prepare_sandbox(
            source_repo=source_repo,
            sandbox=candidate_wt,
            prepare_command=prepare_command,
            timeout=timeout,
            shared_paths=shared_paths,
        )
        candidate_result = run_command(
            test_command, cwd=candidate_wt, source_repo=source_repo, timeout=timeout
        )
        if not candidate_result.passed:
            raise AnalysisError(
                "candidate is not green under the selected test command; hunk necessity cannot be interpreted\n"
                f"return code: {candidate_result.returncode}\n"
                f"stderr tail:\n{candidate_result.stderr_tail}"
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
            baseline_result = run_command(
                test_command, cwd=base_wt, source_repo=source_repo, timeout=timeout
            )

        results: list[MutationResult] = []
        for mutation in mutations:
            hard_reset(candidate_wt, candidate_sha)
            _ensure_shared(source_repo, candidate_wt, shared_paths)
            ok, error = apply_patch(candidate_wt, mutation.patch, reverse=True)
            if not ok:
                results.append(
                    MutationResult(
                        mutation=mutation,
                        status="inconclusive",
                        apply_error=error,
                    )
                )
                continue
            result = run_command(
                test_command, cwd=candidate_wt, source_repo=source_repo, timeout=timeout
            )
            if result.timed_out:
                status = "inconclusive"
            elif result.passed:
                status = "unwitnessed"
            else:
                status = "witnessed"
            results.append(MutationResult(mutation=mutation, status=status, command=result))

        removed_ids: list[str] | None = None
        reduction_patch: str | None = None
        if minimize:
            removed: list[Mutation] = []
            for mutation in mutations:
                hard_reset(candidate_wt, candidate_sha)
                _ensure_shared(source_repo, candidate_wt, shared_paths)
                applicable = True
                for selected in [*removed, mutation]:
                    ok, _ = apply_patch(candidate_wt, selected.patch, reverse=True)
                    if not ok:
                        applicable = False
                        break
                if not applicable:
                    continue
                result = run_command(
                    test_command, cwd=candidate_wt, source_repo=source_repo, timeout=timeout
                )
                if result.passed:
                    removed.append(mutation)

            hard_reset(candidate_wt, candidate_sha)
            _ensure_shared(source_repo, candidate_wt, shared_paths)
            applied_removed: list[Mutation] = []
            for mutation in removed:
                ok, _ = apply_patch(candidate_wt, mutation.patch, reverse=True)
                if ok:
                    applied_removed.append(mutation)
            removed_ids = [m.id for m in applied_removed]
            reduction_patch = candidate_delta(candidate_wt, candidate_sha) if applied_removed else ""

    return candidate_result, baseline_result, results, overlaid_test_files, removed_ids, reduction_patch
