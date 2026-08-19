from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .attestation import AttestationError, expected_certificate_id
from .gitops import git, repo_root, resolve_ref, snapshot_worktree


class DebtCertificateError(ValueError):
    pass


def expected_id(report: dict[str, Any]) -> str:
    """Use the public attestation protocol as the single certificate hash contract."""
    try:
        return expected_certificate_id(report)
    except AttestationError as exc:
        raise DebtCertificateError(str(exc)) from exc


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
        if not isinstance(embedded_sha, str) or not embedded_sha:
            raise DebtCertificateError("certificate has neither candidate tree nor candidate SHA binding")
        if embedded_sha != candidate_sha:
            raise DebtCertificateError("certificate candidate SHA does not match the debt measurement candidate")


def is_assurance_certificate(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and str(value.get("certificate_id") or "").startswith("dwa1_")


def assurance_verify_cli(argv: list[str]) -> int:
    """Compatibility verifier retained for callers that imported the early Debt API directly."""
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