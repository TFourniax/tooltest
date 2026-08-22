from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .attestation import AttestationError, expected_certificate_id
from .engine_protocol import change_id, repository_fingerprint
from .gitops import git, repo_root, resolve_ref, snapshot_worktree
from .ledger import LedgerError


class ChangeEnvelopeError(LedgerError):
    pass


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ChangeEnvelopeError(f"cannot read {label} {path}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChangeEnvelopeError(f"{label} is not valid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ChangeEnvelopeError(f"{label} must be a JSON object: {path}")
    return value, raw


def _tree(repo: Path, sha: str) -> str:
    value = git(repo, "rev-parse", "--verify", f"{sha}^{{tree}}").strip()
    if not value:
        raise ChangeEnvelopeError(f"cannot resolve Git tree for {sha}")
    return value


def _candidate_binding(repo: Path, raw: str) -> tuple[str, dict[str, Any]]:
    if raw.upper() != "WORKTREE":
        sha = resolve_ref(repo, raw)
        return sha, {"sha": sha, "tree": _tree(repo, sha), "dirty": False}
    candidate_sha = snapshot_worktree(repo)
    candidate_tree = _tree(repo, candidate_sha)
    head = resolve_ref(repo, "HEAD")
    head_tree = _tree(repo, head)
    dirty = candidate_tree != head_tree
    return candidate_sha, {
        "sha": None if dirty else head,
        "tree": candidate_tree,
        "dirty": dirty,
    }


def _certificate_binding(repo: Path, report: dict[str, Any], key: str) -> tuple[str | None, str]:
    if report.get("proof_mode") == "adaptive-core":
        sha = report.get(f"{key}_sha")
        tree = report.get(f"{key}_tree")
    else:
        value = report.get(key)
        binding = value if isinstance(value, dict) else {}
        sha = binding.get("sha")
        tree = binding.get("tree")
    if not isinstance(tree, str) or not tree:
        if not isinstance(sha, str) or not sha:
            raise ChangeEnvelopeError(f"proof certificate has no usable {key} Git binding")
        tree = _tree(repo, sha)
    return (sha if isinstance(sha, str) and sha else None), tree


def _proof_claim(report: dict[str, Any]) -> tuple[str, bool]:
    outcome = report.get("outcome")
    if outcome == "proof-not-required" or report.get("schema_version") == "noop-1":
        return "not-required", True
    if outcome == "validation-only" or report.get("schema_version") == "validation-1":
        return "validation", bool(report.get("valid"))
    if report.get("proof_mode") == "adaptive-core":
        accepted = bool(report.get("contrast")) and bool(report.get("one_minimal")) and not list(report.get("removable_mutation_ids") or [])
        return ("causal" if accepted else "inconclusive"), accepted
    if outcome == "assurance" or report.get("schema_version") == "assurance-1":
        classification = report.get("classification")
        if classification == "causal-contrast":
            return "causal", True
        if classification == "preservation-evidence":
            return "preservation", True
        return "inconclusive", False
    if report.get("schema_version") == 2:
        contrast = report.get("contrast")
        candidate_class = (report.get("candidate_run") or {}).get("classification")
        summary = report.get("summary") or {}
        accepted = (
            candidate_class == "stable-pass"
            and int(summary.get("unwitnessed", 0) or 0) == 0
            and int(summary.get("inconclusive", 0) or 0) == 0
            and int(summary.get("surplus_candidate_hunks", 0) or 0) == 0
        )
        if contrast == "base-fail_candidate-pass":
            return "causal", accepted
        if contrast == "base-pass_candidate-pass":
            return "preservation", accepted
        return "inconclusive", False
    return "unknown", False


def _proof_summary(
    path: Path,
    *,
    repo: Path,
    base_tree: str,
    candidate_tree: str,
) -> dict[str, Any]:
    report, _ = _read_json(path, "proof certificate")
    actual = str(report.get("certificate_id") or "")
    try:
        expected = expected_certificate_id(report)
    except AttestationError as exc:
        raise ChangeEnvelopeError(str(exc)) from exc
    if actual != expected:
        raise ChangeEnvelopeError(f"proof certificate integrity mismatch: expected {expected}, got {actual}")
    _, proof_base_tree = _certificate_binding(repo, report, "base")
    _, proof_candidate_tree = _certificate_binding(repo, report, "candidate")
    if proof_base_tree != base_tree:
        raise ChangeEnvelopeError("proof certificate base tree does not match the envelope change")
    if proof_candidate_tree != candidate_tree:
        raise ChangeEnvelopeError("proof certificate candidate tree does not match the envelope change")
    claim, accepted = _proof_claim(report)
    return {
        "tool": "diffwitness",
        "certificate_id": actual,
        "claim": claim,
        "accepted": accepted,
        "certificate_schema": report.get("schema_version") if report.get("schema_version") is not None else str(report.get("proof_mode") or "unknown"),
    }


def _debt_summary(
    path: Path,
    *,
    repo: Path,
    base_tree: str,
    candidate_tree: str,
) -> dict[str, Any]:
    payload, _ = _read_json(path, "Debt Ledger report")
    report = payload.get("report")
    if not isinstance(report, dict) or report.get("schema_version") != "debt-report-1":
        raise ChangeEnvelopeError("Debt Ledger input must be the JSON produced by `dw debt --json <file>`")
    base_sha = report.get("base_sha")
    if not isinstance(base_sha, str) or not base_sha:
        raise ChangeEnvelopeError("Debt Ledger report has no base SHA binding")
    if _tree(repo, base_sha) != base_tree:
        raise ChangeEnvelopeError("Debt Ledger report base tree does not match the envelope change")
    report_candidate_tree = report.get("candidate_tree")
    if not isinstance(report_candidate_tree, str) or report_candidate_tree != candidate_tree:
        raise ChangeEnvelopeError("Debt Ledger report candidate tree does not match the envelope change")
    summary = report.get("summary") or {}
    points = summary.get("points")
    if isinstance(points, bool) or not isinstance(points, int) or points < 0:
        raise ChangeEnvelopeError("Debt Ledger report has an invalid point total")
    lineages: list[str] = []
    for signal in report.get("signals") or []:
        if not isinstance(signal, dict):
            raise ChangeEnvelopeError("Debt Ledger report contains an invalid signal")
        debt_id = signal.get("debt_id")
        if not isinstance(debt_id, str) or not debt_id.startswith("DW-") or len(debt_id) != 15:
            raise ChangeEnvelopeError("Debt Ledger report contains an invalid debt lineage id")
        lineages.append(debt_id)
    budget = payload.get("budget")
    budget_passed = budget.get("passed") if isinstance(budget, dict) and isinstance(budget.get("passed"), bool) else None
    return {
        "report_schema": "debt-report-1",
        "points": points,
        "open_lineages": sorted(set(lineages)),
        "budget_passed": budget_passed,
    }


def _understanding_summary(
    path: Path,
    *,
    change: str,
    repository: str,
    base_tree: str,
    candidate_tree: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    receipt, raw = _read_json(path, "IdleProof receipt")
    if receipt.get("schema") != "idleproof.receipt.v1":
        raise ChangeEnvelopeError("unsupported IdleProof receipt schema")
    session = receipt.get("session")
    if not isinstance(session, dict):
        raise ChangeEnvelopeError("IdleProof receipt has no completed session")
    binding = session.get("change")
    if not isinstance(binding, dict) or binding.get("available") is not True:
        reason = binding.get("reason") if isinstance(binding, dict) else "missing change binding"
        raise ChangeEnvelopeError(f"IdleProof receipt cannot be correlated safely: {reason}")
    if binding.get("changeId") != change:
        raise ChangeEnvelopeError("IdleProof receipt change_id does not match the envelope change")
    repo_binding = binding.get("repository") or {}
    if repo_binding.get("fingerprint") != repository:
        raise ChangeEnvelopeError("IdleProof receipt repository fingerprint does not match")
    if (binding.get("base") or {}).get("tree") != base_tree:
        raise ChangeEnvelopeError("IdleProof receipt base tree does not match the envelope change")
    if (binding.get("candidate") or {}).get("tree") != candidate_tree:
        raise ChangeEnvelopeError("IdleProof receipt candidate tree does not match the envelope change")
    metrics = receipt.get("metrics") or {}
    result: dict[str, Any] = {
        "tool": "idleproof",
        "receipt_schema": "idleproof.receipt.v1",
        "receipt_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }
    metric_map = {
        "coverage": "coverage",
        "debt": "knowledge_debt",
        "featureCoverage": "feature_coverage",
        "featureDebt": "feature_debt",
    }
    for source, target in metric_map.items():
        value = metrics.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            if target in {"coverage", "feature_coverage"} and value > 100:
                raise ChangeEnvelopeError(f"IdleProof metric {source} exceeds 100")
            result[target] = value
    source = str(session.get("source") or "agent")
    actor = {
        "kind": "agent" if source not in {"human", "automation"} else source,
        "agent": source[:128],
        "session_digest": "sha256:" + hashlib.sha256(str(session.get("id") or "").encode("utf-8")).hexdigest(),
    }
    return result, actor


def build_change_envelope(
    *,
    repo: Path,
    base_ref: str,
    candidate_ref: str,
    proof_path: Path | None = None,
    debt_path: Path | None = None,
    understanding_path: Path | None = None,
) -> dict[str, Any]:
    if proof_path is None and debt_path is None and understanding_path is None:
        raise ChangeEnvelopeError("at least one of --proof, --debt, or --understanding is required")
    base_sha = resolve_ref(repo, base_ref)
    base_tree = _tree(repo, base_sha)
    _, candidate = _candidate_binding(repo, candidate_ref)
    repository = repository_fingerprint(repo)
    cid = change_id(repository=repository, base_tree=base_tree, candidate_tree=candidate["tree"])
    envelope: dict[str, Any] = {
        "schema_version": "change-envelope-1",
        "change_id": cid,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository": {"fingerprint": repository, "vcs": "git"},
        "base": {"sha": base_sha, "tree": base_tree, "dirty": False},
        "candidate": candidate,
        "privacy": {"code_uploaded": False, "contains_paths": False, "contains_prompt_text": False},
    }
    if proof_path is not None:
        envelope["proof"] = _proof_summary(proof_path, repo=repo, base_tree=base_tree, candidate_tree=candidate["tree"])
    if debt_path is not None:
        envelope["debt"] = _debt_summary(debt_path, repo=repo, base_tree=base_tree, candidate_tree=candidate["tree"])
    if understanding_path is not None:
        understanding, actor = _understanding_summary(
            understanding_path,
            change=cid,
            repository=repository,
            base_tree=base_tree,
            candidate_tree=candidate["tree"],
        )
        envelope["understanding"] = understanding
        if actor is not None:
            envelope["actor"] = actor
    return envelope


def envelope_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw envelope",
        description="Bind DiffWitness proof, Debt Ledger, and IdleProof evidence to one exact Git change.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--candidate", default="WORKTREE")
    parser.add_argument("--proof", type=Path, help="DiffWitness certificate for this exact change")
    parser.add_argument("--debt", type=Path, help="JSON from `dw debt --json <file>` for this exact change")
    parser.add_argument("--understanding", type=Path, help="IdleProof receipt carrying an exact change identity")
    parser.add_argument("--out", type=Path, help="Output file (default: .git/diffwitness/change-envelope.json)")
    parser.add_argument("--json", action="store_true", help="also print the complete envelope JSON")
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    envelope = build_change_envelope(
        repo=repo,
        base_ref=args.base,
        candidate_ref=args.candidate,
        proof_path=args.proof,
        debt_path=args.debt,
        understanding_path=args.understanding,
    )
    output = args.out or (repo / ".git" / "diffwitness" / "change-envelope.json")
    if not output.is_absolute():
        output = repo / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Change: {envelope['change_id']}")
    if "proof" in envelope:
        proof = envelope["proof"]
        print(f"Proof: {proof['claim']} ({'accepted' if proof.get('accepted') else 'not accepted'})")
    if "debt" in envelope:
        debt = envelope["debt"]
        budget = debt.get("budget_passed")
        suffix = "" if budget is None else f" · budget {'PASS' if budget else 'EXCEEDED'}"
        print(f"Debt: {debt['points']} point(s) · {len(debt['open_lineages'])} obligation(s){suffix}")
    if "understanding" in envelope:
        understanding = envelope["understanding"]
        print(f"Understanding: {understanding.get('coverage', 0)}% · knowledge debt {understanding.get('knowledge_debt', 0)}")
    print(f"Envelope: {output}")
    if args.json:
        print(json.dumps(envelope, indent=2, ensure_ascii=False))
    return 0
