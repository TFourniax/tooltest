from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .gitops import GitError, git, repo_root, resolve_ref, snapshot_worktree


class AttestationError(RuntimeError):
    pass


def _hash(payload: dict[str, Any], prefix: str) -> str:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return prefix + hashlib.sha256(raw).hexdigest()[:20]


def _git_binding(report: dict[str, Any], key: str) -> dict[str, Any]:
    value = report.get(key)
    return value if isinstance(value, dict) else {}


def expected_certificate_id(report: dict[str, Any]) -> str:
    actual = str(report.get("certificate_id") or "")
    if actual.startswith("dw2_"):
        stable = {
            key: value
            for key, value in report.items()
            if key not in {"generated_at", "certificate_id"}
        }
        return _hash(stable, "dw2_")

    if actual.startswith("dwac1_"):
        stable = {key: value for key, value in report.items() if key != "certificate_id"}
        return _hash(stable, "dwac1_")

    if actual.startswith("dwa1_"):
        base = _git_binding(report, "base")
        candidate = _git_binding(report, "candidate")
        execution = report.get("execution") or {}
        stable = {
            "base_sha": base.get("sha"),
            "base_tree": base.get("tree"),
            "candidate_sha": candidate.get("sha"),
            "candidate_tree": candidate.get("tree"),
            "candidate_ref": candidate.get("ref"),
            "test_command": report.get("test_command"),
            "test_files": sorted(report.get("changed_test_files") or []),
            "candidate_run": report.get("candidate_run"),
            "baseline_run": report.get("baseline_with_candidate_tests_run"),
            "classification": report.get("classification"),
            "prepare": execution.get("prepare"),
            "timeout": execution.get("timeout"),
            "stability_runs": execution.get("stability_runs"),
            "shared_paths": sorted(execution.get("share") or []),
            "test_overlay": execution.get("test_overlay"),
        }
        return _hash(stable, "dwa1_")

    if actual.startswith("dwv1_"):
        base = _git_binding(report, "base")
        candidate = _git_binding(report, "candidate")
        execution = report.get("execution") or {}
        stable = {
            "base_sha": base.get("sha"),
            "base_tree": base.get("tree"),
            "candidate_sha": candidate.get("sha"),
            "candidate_tree": candidate.get("tree"),
            "test_command": report.get("test_command"),
            "test_files": sorted(report.get("changed_test_files") or []),
            "runs": report.get("candidate_run"),
            "prepare": execution.get("prepare"),
            "timeout": execution.get("timeout"),
            "stability_runs": execution.get("stability_runs"),
            "shared_paths": sorted(execution.get("share") or []),
        }
        return _hash(stable, "dwv1_")

    if actual.startswith("dw0_"):
        base = _git_binding(report, "base")
        candidate = _git_binding(report, "candidate")
        stable = {
            "base": base.get("sha"),
            "candidate": candidate.get("sha"),
            "base_tree": base.get("tree"),
            "candidate_tree": candidate.get("tree"),
            "changed_files": sorted(report.get("changed_files") or []),
            "ignored": sorted(report.get("ignored") or []),
        }
        return _hash(stable, "dw0_")

    raise AttestationError(f"unsupported or missing DiffWitness certificate id: {actual!r}")


def verify_integrity(report: dict[str, Any]) -> tuple[bool, str, str]:
    actual = str(report.get("certificate_id") or "")
    expected = expected_certificate_id(report)
    return actual == expected, actual, expected


def _tree_from_commit(repo: Path, commit: str) -> str:
    value = git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}").strip()
    if not value:
        raise AttestationError(f"cannot resolve tree for {commit}")
    return value


def _binding(report: dict[str, Any], key: str) -> tuple[str | None, str | None]:
    value = _git_binding(report, key)
    sha = value.get("sha")
    tree = value.get("tree")
    if key == "candidate":
        sha = sha or report.get("candidate_sha")
        tree = tree or report.get("candidate_tree")
    else:
        sha = sha or report.get("base_sha")
        tree = tree or report.get("base_tree")
    return (
        sha if isinstance(sha, str) and sha else None,
        tree if isinstance(tree, str) and tree else None,
    )


def _artifact_relpath(repo: Path, path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
    # Never silently ignore tracked evidence artifacts: tracked files are repository content.
    return None if git(repo, "ls-files", "--", rel).strip() else rel


def verify_against_repo(
    report: dict[str, Any],
    *,
    repo: Path,
    against: str = "WORKTREE",
    ignore_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    integrity, actual_id, expected_id = verify_integrity(report)
    candidate_sha, candidate_tree = _binding(report, "candidate")
    base_sha, base_tree = _binding(report, "base")

    if candidate_tree:
        candidate_binding = "embedded-tree"
        expected_tree = candidate_tree
    elif candidate_sha:
        candidate_binding = "resolvable-sha"
        expected_tree = _tree_from_commit(repo, candidate_sha)
    else:
        raise AttestationError("certificate has no candidate content binding")

    if against.upper() == "WORKTREE":
        current_sha = snapshot_worktree(repo, exclude_paths=ignore_artifacts or [])
        current_label = "WORKTREE"
    else:
        current_sha = resolve_ref(repo, against)
        current_label = against
    current_tree = _tree_from_commit(repo, current_sha)

    if base_tree:
        base_binding = "embedded-tree"
        base_bound = True
    elif base_sha:
        try:
            base_tree = _tree_from_commit(repo, base_sha)
            base_binding = "resolvable-sha"
            base_bound = True
        except (GitError, AttestationError):
            base_binding = "missing"
            base_bound = False
    else:
        base_binding = "missing"
        base_bound = False

    fresh = expected_tree == current_tree
    return {
        "certificate_id": actual_id,
        "integrity": "valid" if integrity else "tampered",
        "expected_certificate_id": expected_id,
        "freshness": "fresh" if fresh else "stale",
        "against": current_label,
        "candidate_binding": candidate_binding,
        "certificate_candidate_sha": candidate_sha,
        "certificate_candidate_tree": expected_tree,
        "current_sha": current_sha,
        "current_tree": current_tree,
        "base_binding": base_binding,
        "certificate_base_sha": base_sha,
        "certificate_base_tree": base_tree,
        "base_bound": base_bound,
        "ignored_artifacts": list(ignore_artifacts or []),
        "valid": integrity and fresh and base_bound,
    }


def load_certificate(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AttestationError(f"cannot read certificate {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AttestationError("certificate root must be a JSON object")
    return payload


def verify_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw verify",
        description="Verify certificate integrity and whether it still belongs to repository content.",
    )
    parser.add_argument("certificate", type=Path)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--against", default="WORKTREE")
    parser.add_argument("--ignore-artifact", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo = repo_root(args.repo)
    ignored = list(args.ignore_artifact)
    own = _artifact_relpath(repo, args.certificate)
    if own and own not in ignored:
        ignored.append(own)
    result = verify_against_repo(
        load_certificate(args.certificate),
        repo=repo,
        against=args.against,
        ignore_artifacts=ignored,
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"certificate: {result['certificate_id']}")
        print(f"integrity:   {result['integrity']}")
        print(f"freshness:   {result['freshness']} against {result['against']}")
        print(f"candidate:   {result['candidate_binding']}")
        print(f"base:        {result['base_binding']}")
        if result["ignored_artifacts"]:
            print(f"artifacts:   ignored {', '.join(result['ignored_artifacts'])}")
        print(f"verdict:     {'VALID' if result['valid'] else 'INVALID'}")
    return 0 if result["valid"] else 1


def note_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw note",
        description="Attach a verified DiffWitness proof reference to a Git commit using git notes.",
    )
    parser.add_argument("certificate", type=Path)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--notes-ref", default="diffwitness")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    repo = repo_root(args.repo)
    report = load_certificate(args.certificate)
    commit_sha = resolve_ref(repo, args.commit)
    verification = verify_against_repo(report, repo=repo, against=commit_sha)
    if not verification["valid"]:
        print(
            "DiffWitness: refusing to attach an invalid or stale proof; run `dw verify` for details.",
            file=sys.stderr,
        )
        return 1

    summary = report.get("summary") or {}
    message = json.dumps(
        {
            "protocol": "DiffWitness",
            "certificate_id": report.get("certificate_id"),
            "candidate_tree": verification["current_tree"],
            "outcome": report.get("outcome", "causal-proof"),
            "classification": report.get("classification") or report.get("contrast"),
            "summary": {
                "witnessed": summary.get("witnessed", 0),
                "unwitnessed": summary.get("unwitnessed", 0),
                "inconclusive": summary.get("inconclusive", 0),
                "surplus_candidate_hunks": summary.get("surplus_candidate_hunks", 0),
            },
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    command = ["notes", f"--ref={args.notes_ref}", "add"]
    if args.force:
        command.append("-f")
    command += ["-m", message, commit_sha]
    try:
        git(repo, *command)
    except GitError as exc:
        print(f"DiffWitness: could not attach git note: {exc}", file=sys.stderr)
        return 2
    print(
        f"DiffWitness proof {report['certificate_id']} attached to {commit_sha[:12]} "
        f"via refs/notes/{args.notes_ref}."
    )
    print(f"Publish it with: git push origin refs/notes/{args.notes_ref}")
    return 0
