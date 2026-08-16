from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .gitops import git


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
        base = report.get("base") or {}; candidate = report.get("candidate") or {}; execution = report.get("execution") or {}
        stable = {
            "base_sha": base.get("sha"), "base_tree": base.get("tree"),
            "candidate_sha": candidate.get("sha"), "candidate_tree": candidate.get("tree"), "candidate_ref": candidate.get("ref"),
            "test_command": report.get("test_command"), "test_files": sorted(report.get("changed_test_files") or []),
            "candidate_run": report.get("candidate_run"), "baseline_run": report.get("baseline_with_candidate_tests_run"),
            "classification": report.get("classification"), "prepare": execution.get("prepare"), "timeout": execution.get("timeout"),
            "stability_runs": execution.get("stability_runs"), "shared_paths": sorted(execution.get("share") or []),
            "test_overlay": execution.get("test_overlay"),
        }
        return _hash(stable, "dwa1_")
    if cid.startswith("dwv1_") or cid.startswith("dw0_"):
        return cid
    raise DebtCertificateError(f"unsupported DiffWitness certificate for debt accounting: {cid!r}")


def validate_debt_certificate(report: dict[str, Any], *, repo: Path, candidate_sha: str) -> None:
    cid = str(report.get("certificate_id") or ""); expected = expected_id(report)
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
