from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .gitops import git, repo_root, resolve_ref, snapshot_worktree


class DebtCertificateError(ValueError):
    pass


def _hash(payload: dict[str, Any], prefix: str) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return prefix + hashlib.sha256(encoded).hexdigest()[:20]


def expected_id(report: dict[str, Any]) -> str:
    cid = str(report.get("certificate_id") or "")
    if cid.startswith("dw2_"):
        return _hash({key: value for key, value in report.items() if key not in {"generated_at", "certificate_id"}}, "dw2_")
    if cid.startswith("dwac1_"):
        return _hash({key: value for key, value in report.items() if key != "certificate_id"}, "dwac1_")
    if cid.startswith("dwa1_"):
        base = report.get("base") or {}
        candidate = report.get("candidate") or {}
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
    if cid.startswith("dwv1_") or cid.startswith("dw0_"):
        # These modes never waive production-debt obligations here; their full integrity remains
        # owned by the canonical attestation implementation.
        return cid
    raise DebtCertificateError(f"unsupported DiffWitness certificate for debt accounting: {cid!r}")


def validate_debt_certificate(report: dict[str, Any], *, repo: Path, candidate_sha: str) -> None:
    cid = str(report.get("certificate_id") or "")
    expected = expected_id(report)
    if cid != expected:
        raise DebtCertificateError(f"certificate integrity mismatch: expected {expected}, got {cid}")
    candidate = report.get("candidate") or {}
    embedded_tree = candidate.get("tree") if isinstance(candidate, dict) else None
    current_tree = git(repo, "rev-parse", "--verify", f"{candidate_sha}^{{tree}}").strip()
    if embedded_tree:
        if embedded_tree != current_tree:
            raise DebtCertificateError("certificate candidate tree does not match the debt measurement candidate")
    else:
        embedded_sha = candidate.get("sha") if isinstance(candidate, dict) else report.get("candidate_sha")
        if embedded_sha and embedded_sha != candidate_sha:
            raise DebtCertificateError("certificate candidate SHA does not match the debt measurement candidate")


def is_assurance_certificate(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and str(value.get("certificate_id") or "").startswith("dwa1_")


def assurance_verify_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw verify",
        description="Verify DiffWitness assurance-certificate integrity and content freshness.",
    )
    parser.add_argument("certificate", type=Path)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--against", default="WORKTREE", help="WORKTREE or Git ref (default: WORKTREE)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.certificate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DebtCertificateError(f"cannot read assurance certificate {args.certificate}: {exc}") from exc
    if not isinstance(report, dict) or not str(report.get("certificate_id") or "").startswith("dwa1_"):
        raise DebtCertificateError("certificate is not a DiffWitness assurance certificate")
    repo = repo_root(args.repo)
    current_sha = snapshot_worktree(repo) if args.against.upper() == "WORKTREE" else resolve_ref(repo, args.against)
    cid = str(report.get("certificate_id") or "")
    expected = expected_id(report)
    integrity = cid == expected
    candidate = report.get("candidate") or {}
    expected_tree = candidate.get("tree") if isinstance(candidate, dict) else None
    if not isinstance(expected_tree, str) or not expected_tree:
        candidate_sha = candidate.get("sha") if isinstance(candidate, dict) else None
        if not isinstance(candidate_sha, str) or not candidate_sha:
            raise DebtCertificateError("assurance certificate has neither candidate tree nor candidate SHA")
        expected_tree = git(repo, "rev-parse", "--verify", f"{candidate_sha}^{{tree}}").strip()
    current_tree = git(repo, "rev-parse", "--verify", f"{current_sha}^{{tree}}").strip()
    fresh = expected_tree == current_tree
    result = {
        "certificate_id": cid,
        "integrity": "valid" if integrity else "tampered",
        "expected_certificate_id": expected,
        "freshness": "fresh" if fresh else "stale",
        "against": args.against,
        "certificate_candidate_tree": expected_tree,
        "current_tree": current_tree,
        "classification": report.get("classification"),
        "valid": integrity and fresh,
    }
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"certificate: {cid}")
        print(f"integrity:   {result['integrity']}")
        print(f"freshness:   {result['freshness']} against {args.against}")
        print(f"class:       {result['classification']}")
        print(f"verdict:     {'VALID' if result['valid'] else 'INVALID'}")
    return 0 if result["valid"] else 1
