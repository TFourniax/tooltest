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


def _hash_payload(payload: dict[str, Any], prefix: str) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return prefix + hashlib.sha256(encoded).hexdigest()[:20]


def expected_certificate_id(report: dict[str, Any]) -> str:
    certificate = str(report.get("certificate_id") or "")
    if certificate.startswith("dw2_"):
        stable = {
            key: value
            for key, value in report.items()
            if key not in {"generated_at", "certificate_id"}
        }
        return _hash_payload(stable, "dw2_")
    if certificate.startswith("dwac1_"):
        stable = {key: value for key, value in report.items() if key != "certificate_id"}
        return _hash_payload(stable, "dwac1_")
    if certificate.startswith("dwa1_"):
        # Assurance is part of the same public certificate protocol. Reuse the exact stable-field
        # contract used by the Debt Ledger rather than maintaining a second subtly divergent hash.
        from .debt_certificate import expected_id

        try:
            return expected_id(report)
        except ValueError as exc:
            raise AttestationError(str(exc)) from exc
    if certificate.startswith("dwv1_"):
        execution = report.get("execution") or {}
        base = report.get("base") or {}
        candidate = report.get("candidate") or {}
        stable = {
            "base_sha": base.get("sha"),
            "candidate_sha": candidate.get("sha"),
            "test_command": report.get("test_command"),
            "test_files": sorted(report.get("changed_test_files") or []),
            "runs": report.get("candidate_run"),
            "prepare": execution.get("prepare"),
            "timeout": execution.get("timeout"),
            "stability_runs": execution.get("stability_runs"),
            "shared_paths": sorted(execution.get("share") or []),
        }
        # validation-1 certificates created by 0.3+ bind directly to content trees. Preserve
        # compatibility with early development certificates that did not yet carry these fields.
        if base.get("tree") or candidate.get("tree"):
            stable["base_tree"] = base.get("tree")
            stable["candidate_tree"] = candidate.get("tree")
        return _hash_payload(stable, "dwv1_")
    if certificate.startswith("dw0_"):
        base = report.get("base") or {}
        candidate = report.get("candidate") or {}
        stable = {
            "base": base.get("sha"),
            "candidate": candidate.get("sha"),
            "changed_files": sorted(report.get("changed_files") or []),
            "ignored": sorted(report.get("ignored") or []),
        }
        if base.get("tree") or candidate.get("tree"):
            stable["base_tree"] = base.get("tree")
            stable["candidate_tree"] = candidate.get("tree")
        return _hash_payload(stable, "dw0_")
    raise AttestationError(f"unsupported or missing DiffWitness certificate id: {certificate!r}")


def verify_integrity(report: dict[str, Any]) -> tuple[bool, str, str]:
    actual = str(report.get("certificate_id") or "")
    expected = expected_certificate_id(report)
    return actual == expected, actual, expected


def _tree(repo: Path, commit: str) -> str:
    value = git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}").strip()
    if not value:
        raise AttestationError(f"cannot resolve tree for {commit}")
    return value


def _candidate_sha(report: dict[str, Any]) -> str | None:
    if "candidate" in report and isinstance(report["candidate"], dict):
        value = report["candidate"].get("sha")
    else:
        value = report.get("candidate_sha")
    return value if isinstance(value, str) and value else None


def _base_sha(report: dict[str, Any]) -> str | None:
    if "base" in report and isinstance(report["base"], dict):
        value = report["base"].get("sha")
    else:
        value = report.get("base_sha")
    return value if isinstance(value, str) and value else None


def _candidate_tree(report: dict[str, Any]) -> str | None:
    candidate = report.get("candidate")
    if isinstance(candidate, dict):
        value = candidate.get("tree")
        if isinstance(value, str) and value:
            return value
    value = report.get("candidate_tree")
    return value if isinstance(value, str) and value else None


def _base_tree(report: dict[str, Any]) -> str | None:
    base = report.get("base")
    if isinstance(base, dict):
        value = base.get("tree")
        if isinstance(value, str) and value:
            return value
    value = report.get("base_tree")
    return value if isinstance(value, str) and value else None


def verify_against_repo(
    report: dict[str, Any],
    *,
    repo: Path,
    against: str = "WORKTREE",
    ignore_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    integrity, actual_id, expected_id = verify_integrity(report)

    candidate_sha = _candidate_sha(report)
    expected_tree = _candidate_tree(report)
    candidate_binding = "embedded-tree" if expected_tree else "resolvable-sha"
    if expected_tree is None:
        if candidate_sha is None:
            raise AttestationError("certificate has neither candidate tree nor candidate SHA")
        expected_tree = _tree(repo, candidate_sha)

    if against.upper() == "WORKTREE":
        current_sha = snapshot_worktree(repo, exclude_paths=ignore_artifacts or [])
        current_label = "WORKTREE"
    else:
        current_sha = resolve_ref(repo, against)
        current_label = against
    current_tree = _tree(repo, current_sha)

    base_tree = _base_tree(report)
    base_sha = _base_sha(report)
    if base_tree:
        base_binding = "embedded-tree"
        base_bound = True
    elif base_sha:
        try:
            base_tree = _tree(repo, base_sha)
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
        # Kept for backwards-compatible machine consumers. Embedded tree binding is stronger than
        # requiring the original commit object to remain in the local object database.
        "base_resolvable": base_bound,
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


def _artifact_relpath(repo: Path, path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
    tracked = git(repo, "ls-files", "--", rel).strip()
    return None if tracked else rel


def verify_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw verify",
        description="Verify proof integrity and whether it still matches repository content.",
    )
    parser.add_argument("certificate", type=Path)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--against", default="WORKTREE", help="WORKTREE or Git ref (default: WORKTREE)")
    parser.add_argument(
        "--ignore-artifact",
        action="append",
        default=[],
        help="Repo-relative generated artifact to exclude from WORKTREE freshness comparison; repeatable",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable verification result")
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
            "contrast": report.get("contrast", "not-applicable"),
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
