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
    if certificate.startswith("dw0_"):
        stable = {
            "base": report.get("base", {}).get("sha"),
            "candidate": report.get("candidate", {}).get("sha"),
            "changed_files": sorted(report.get("changed_files") or []),
            "ignored": sorted(report.get("ignored") or []),
        }
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


def _candidate_sha(report: dict[str, Any]) -> str:
    if "candidate" in report and isinstance(report["candidate"], dict):
        value = report["candidate"].get("sha")
    else:
        value = report.get("candidate_sha")
    if not isinstance(value, str) or not value:
        raise AttestationError("certificate has no candidate SHA")
    return value


def _base_sha(report: dict[str, Any]) -> str | None:
    if "base" in report and isinstance(report["base"], dict):
        value = report["base"].get("sha")
    else:
        value = report.get("base_sha")
    return value if isinstance(value, str) and value else None


def verify_against_repo(
    report: dict[str, Any], *, repo: Path, against: str = "WORKTREE"
) -> dict[str, Any]:
    integrity, actual_id, expected_id = verify_integrity(report)
    candidate_sha = _candidate_sha(report)
    expected_tree = _tree(repo, candidate_sha)
    if against.upper() == "WORKTREE":
        current_sha = snapshot_worktree(repo)
        current_label = "WORKTREE"
    else:
        current_sha = resolve_ref(repo, against)
        current_label = against
    current_tree = _tree(repo, current_sha)
    base_sha = _base_sha(report)
    base_resolvable = True
    if base_sha:
        try:
            _tree(repo, base_sha)
        except (GitError, AttestationError):
            base_resolvable = False
    fresh = expected_tree == current_tree
    return {
        "certificate_id": actual_id,
        "integrity": "valid" if integrity else "tampered",
        "expected_certificate_id": expected_id,
        "freshness": "fresh" if fresh else "stale",
        "against": current_label,
        "certificate_candidate_sha": candidate_sha,
        "certificate_candidate_tree": expected_tree,
        "current_sha": current_sha,
        "current_tree": current_tree,
        "base_resolvable": base_resolvable,
        "valid": integrity and fresh and base_resolvable,
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
    parser = argparse.ArgumentParser(prog="dw verify", description="Verify proof integrity and whether it still matches repository content.")
    parser.add_argument("certificate", type=Path)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--against", default="WORKTREE", help="WORKTREE or Git ref (default: WORKTREE)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable verification result")
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    result = verify_against_repo(load_certificate(args.certificate), repo=repo, against=args.against)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"certificate: {result['certificate_id']}")
        print(f"integrity:   {result['integrity']}")
        print(f"freshness:   {result['freshness']} against {result['against']}")
        print(f"base:        {'resolvable' if result['base_resolvable'] else 'missing'}")
        print(f"verdict:     {'VALID' if result['valid'] else 'INVALID'}")
    return 0 if result["valid"] else 1


def note_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw note", description="Attach a verified DiffWitness proof reference to a Git commit using git notes.")
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
    print(f"DiffWitness proof {report['certificate_id']} attached to {commit_sha[:12]} via refs/notes/{args.notes_ref}.")
    print(f"Publish it with: git push origin refs/notes/{args.notes_ref}")
    return 0
