from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Sequence

from .gitops import git
from .models import Mutation
from .runner import _popen_group_kwargs, _terminate_process_tree


ENGINE_REQUEST_SCHEMA = "engine-request-1"
ENGINE_PLAN_SCHEMA = "engine-plan-1"
_MAX_ENGINE_OUTPUT_BYTES = 1024 * 1024


class EngineProtocolError(RuntimeError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str | bytes) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def repository_fingerprint(repo: Path) -> str:
    """Return a clone-stable repository-lineage fingerprint without exposing its remote URL.

    Only roots reachable from ``HEAD`` participate. Using every local ref would make identity drift
    when a user fetched an unrelated branch or when DiffWitness created its own ledger/checkpoint
    refs. Merged histories are still handled because all roots reachable from HEAD are included.
    """
    roots = sorted(
        line.strip()
        for line in git(repo, "rev-list", "--max-parents=0", "HEAD").splitlines()
        if line.strip()
    )
    if not roots:
        raise EngineProtocolError("cannot fingerprint repository without a Git root commit")
    return "dwrepo_" + _sha256("\n".join(roots))[:24]


def change_id(*, repository: str, base_tree: str, candidate_tree: str) -> str:
    stable = {
        "schema_version": "change-envelope-1",
        "repository": repository,
        "base_tree": base_tree,
        "candidate_tree": candidate_tree,
    }
    return "dwchg_" + _sha256(_canonical(stable))[:24]


def _mutation_metadata(mutation: Mutation) -> dict[str, Any]:
    return {
        "id": mutation.id,
        "path": mutation.path,
        "label": mutation.label[:512],
        "kind": mutation.kind,
        "additions": mutation.additions,
        "deletions": mutation.deletions,
        "line": mutation.line,
        "end_line": mutation.end_line,
    }


def build_engine_request(
    *,
    repo: Path,
    base_sha: str,
    base_tree: str,
    candidate_sha: str,
    candidate_tree: str,
    mutations: Sequence[Mutation],
    max_experiments: int,
    max_total_seconds: float,
    stability_runs: int,
    policy: str,
    strategy: str,
    test_command: str,
    changed_test_files: Sequence[str] = (),
) -> dict[str, Any]:
    if not mutations:
        raise EngineProtocolError("engine planning requires at least one mutation")
    if max_experiments < 1 or max_total_seconds <= 0 or stability_runs < 1:
        raise EngineProtocolError("invalid engine planning budget")

    repo_fingerprint = repository_fingerprint(repo)
    cid = change_id(
        repository=repo_fingerprint,
        base_tree=base_tree,
        candidate_tree=candidate_tree,
    )
    stable = {
        "schema_version": ENGINE_REQUEST_SCHEMA,
        "change_id": cid,
        "repository": {"fingerprint": repo_fingerprint},
        "base": {"sha": base_sha, "tree": base_tree},
        "candidate": {"sha": candidate_sha, "tree": candidate_tree},
        "mutations": [_mutation_metadata(item) for item in mutations],
        "budget": {
            "max_experiments": int(max_experiments),
            "max_total_seconds": float(max_total_seconds),
            "stability_runs": int(stability_runs),
        },
        "policy": {"mode": policy, "strategy": strategy},
        "evidence": {
            "command_sha256": _sha256(test_command),
            "changed_test_files": sorted(dict.fromkeys(changed_test_files)),
        },
        "privacy": {
            "source_embedded": False,
            "local_workspace_read_allowed": True,
        },
    }
    request_id = "dwerq_" + _sha256(_canonical(stable))[:24]
    return {**stable, "request_id": request_id}


def request_digest(request: dict[str, Any]) -> str:
    return _sha256(_canonical(request))


def _validate_exact_permutation(values: Any, expected: list[str], label: str) -> list[str]:
    if not isinstance(values, list) or not values or any(not isinstance(item, str) for item in values):
        raise EngineProtocolError(f"engine plan {label} must be a non-empty string array")
    if len(values) != len(set(values)):
        raise EngineProtocolError(f"engine plan {label} contains duplicate mutation ids")
    if set(values) != set(expected) or len(values) != len(expected):
        raise EngineProtocolError(f"engine plan {label} must contain every mutation id exactly once")
    return list(values)


def validate_engine_plan(request: dict[str, Any], plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise EngineProtocolError("engine response must be a JSON object")
    if plan.get("schema_version") != ENGINE_PLAN_SCHEMA:
        raise EngineProtocolError("unsupported engine response schema")
    if plan.get("request_id") != request.get("request_id"):
        raise EngineProtocolError("engine response request_id mismatch")
    expected_digest = request_digest(request)
    if plan.get("request_digest") != expected_digest:
        raise EngineProtocolError("engine response is not bound to the exact request")

    engine = plan.get("engine")
    if not isinstance(engine, dict):
        raise EngineProtocolError("engine response must identify engine name/version")
    if not isinstance(engine.get("name"), str) or not engine["name"].strip():
        raise EngineProtocolError("engine name is missing")
    if not isinstance(engine.get("version"), str) or not engine["version"].strip():
        raise EngineProtocolError("engine version is missing")

    expected_ids = [item["id"] for item in request.get("mutations") or []]
    ordered = _validate_exact_permutation(
        plan.get("ordered_mutation_ids"), expected_ids, "ordered_mutation_ids"
    )

    partitions = plan.get("partitions")
    if not isinstance(partitions, list) or not partitions:
        raise EngineProtocolError("engine plan partitions must be a non-empty array")
    flattened: list[str] = []
    normalized_partitions: list[list[str]] = []
    for index, group in enumerate(partitions):
        if not isinstance(group, list) or not group or any(not isinstance(item, str) for item in group):
            raise EngineProtocolError(f"engine plan partition {index} must be a non-empty string array")
        if len(group) != len(set(group)):
            raise EngineProtocolError(f"engine plan partition {index} contains duplicates")
        flattened.extend(group)
        normalized_partitions.append(list(group))
    _validate_exact_permutation(flattened, expected_ids, "partitions")

    pairs = plan.get("interaction_pairs")
    if not isinstance(pairs, list):
        raise EngineProtocolError("engine plan interaction_pairs must be an array")
    normalized_pairs: list[list[str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    allowed = set(expected_ids)
    for index, pair in enumerate(pairs):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(item, str) for item in pair)
        ):
            raise EngineProtocolError(f"engine interaction pair {index} must contain two ids")
        left, right = pair
        if left == right or left not in allowed or right not in allowed:
            raise EngineProtocolError(f"engine interaction pair {index} is invalid")
        canonical = tuple(sorted((left, right)))
        if canonical in seen_pairs:
            raise EngineProtocolError("engine interaction_pairs contains duplicates")
        seen_pairs.add(canonical)
        normalized_pairs.append([left, right])

    diagnostics = plan.get("diagnostics") or {}
    if not isinstance(diagnostics, dict):
        raise EngineProtocolError("engine diagnostics must be an object")

    return {
        "schema_version": ENGINE_PLAN_SCHEMA,
        "request_id": request["request_id"],
        "request_digest": expected_digest,
        "engine": {"name": engine["name"][:128], "version": engine["version"][:64]},
        "ordered_mutation_ids": ordered,
        "partitions": normalized_partitions,
        "interaction_pairs": normalized_pairs,
        "diagnostics": diagnostics,
    }


def run_advisory_engine(
    *,
    repo: Path,
    command: Sequence[str],
    request: dict[str, Any],
    timeout: float = 2.0,
    required: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    """Invoke an optional local planner with strict validation and safe fallback semantics."""
    cmd = [str(item) for item in command if str(item)]
    if not cmd:
        if required:
            raise EngineProtocolError("private/advisory engine is required but no command is configured")
        return None, "no advisory engine configured"
    if timeout <= 0:
        raise EngineProtocolError("engine timeout must be > 0")

    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=repo,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
            **_popen_group_kwargs(),
        )
        try:
            stdout, stderr = proc.communicate(
                _canonical(request) + "\n", timeout=timeout
            )
        except subprocess.TimeoutExpired as exc:
            _terminate_process_tree(proc)
            try:
                proc.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
            raise EngineProtocolError(
                f"advisory engine exceeded {timeout:g}s planning timeout"
            ) from exc
        if proc.returncode != 0:
            tail = (stderr or "")[-2000:].strip()
            raise EngineProtocolError(
                f"advisory engine exited with {proc.returncode}" + (f": {tail}" if tail else "")
            )
        if len(stdout.encode("utf-8")) > _MAX_ENGINE_OUTPUT_BYTES:
            raise EngineProtocolError("advisory engine response exceeds 1 MiB")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise EngineProtocolError("advisory engine returned invalid JSON") from exc
        return validate_engine_plan(request, payload), None
    except (OSError, EngineProtocolError) as exc:
        if proc is not None and proc.poll() is None:
            _terminate_process_tree(proc)
        if required:
            raise EngineProtocolError(str(exc)) from exc
        return None, str(exc)
