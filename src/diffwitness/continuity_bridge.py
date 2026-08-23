from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .continuity_events import ContinuityError, append_project_event
from .engine_protocol import change_id, repository_fingerprint
from .gitops import git, repo_root


def _read_envelope(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuityError(f"cannot read change envelope {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContinuityError("change envelope must be a JSON object")
    return value


def _validate_envelope(repo: Path, envelope: dict[str, Any]) -> tuple[str, str, str]:
    if envelope.get("schema_version") != "change-envelope-1":
        raise ContinuityError("unsupported change-envelope schema")
    repository = (envelope.get("repository") or {}).get("fingerprint")
    base_tree = (envelope.get("base") or {}).get("tree")
    candidate_tree = (envelope.get("candidate") or {}).get("tree")
    cid = envelope.get("change_id")
    if not all(isinstance(value, str) and value for value in (repository, base_tree, candidate_tree, cid)):
        raise ContinuityError("change envelope is missing repository/base/candidate identity")
    local = repository_fingerprint(repo)
    if local != repository:
        raise ContinuityError("change envelope repository fingerprint does not match this repository")
    expected = change_id(repository=repository, base_tree=base_tree, candidate_tree=candidate_tree)
    if expected != cid:
        raise ContinuityError("change envelope change_id integrity mismatch")
    return cid, base_tree, candidate_tree


def _changed_files(repo: Path, envelope: dict[str, Any]) -> list[str]:
    base_sha = (envelope.get("base") or {}).get("sha")
    candidate_sha = (envelope.get("candidate") or {}).get("sha")
    if not isinstance(base_sha, str) or not isinstance(candidate_sha, str) or not base_sha or not candidate_sha:
        return []
    try:
        raw = git(repo, "diff", "--name-only", "--no-renames", base_sha, candidate_sha)
    except Exception:
        return []
    files: list[str] = []
    for line in raw.splitlines():
        path = line.strip().replace("\\", "/")
        if path and not path.startswith("../") and not path.startswith("/"):
            files.append(path[:500])
    return sorted(set(files))[:500]


def _file_entity_id(path: str) -> str:
    """Keep arbitrary valid Git paths in labels while entity ids remain transport-safe."""
    return "file:" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]


def _change_actor(envelope: dict[str, Any]) -> dict[str, str]:
    """Return the actor described by the evidence, not the process importing that evidence."""
    raw = envelope.get("actor")
    if isinstance(raw, dict):
        kind = str(raw.get("kind") or "agent")[:64]
        identity = str(raw.get("agent") or raw.get("id") or kind)[:128]
        if kind and identity:
            return {"kind": kind, "id": identity}
    return {"kind": "unknown", "id": "unknown-change-actor"}


def record_change_envelope(
    *,
    repo: str | Path,
    envelope: dict[str, Any] | None = None,
    path: Path | None = None,
    actor: str = "diffwitness",
    trusted_proof: bool = False,
) -> dict[str, Any]:
    """Project a frozen change envelope into continuity events.

    ``trusted_proof`` is deliberately false for arbitrary/manual envelope imports. An envelope
    contains a *summary* of a proof certificate; seeing that summary is not enough to upgrade a
    claim to VERIFIED. Guard passes ``trusted_proof=True`` only after the authoritative public
    runner has validated the generated certificate.

    ``actor`` identifies the importer for diagnostics/provenance only. The semantic change actor is
    taken from the envelope (when IdleProof supplied one) so importing the same exact Git fact by a
    human and by Guard cannot create a false semantic conflict.
    """
    root = repo_root(repo)
    if envelope is None:
        if path is None:
            raise ContinuityError("record_change_envelope requires envelope or path")
        envelope = _read_envelope(path)
    cid, base_tree, candidate_tree = _validate_envelope(root, envelope)
    repository = str((envelope.get("repository") or {}).get("fingerprint"))
    changed_files = _changed_files(root, envelope)
    source_digest = None
    if path is not None and path.exists():
        source_digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    provenance = {
        "producer": "diffwitness",
        "source": "change-envelope",
        "artifact_schema": "change-envelope-1",
    }
    if source_digest:
        provenance["artifact_digest"] = source_digest
    event_actor = _change_actor(envelope)

    file_relations = [
        {
            "predicate": "affects",
            "target": {"id": _file_entity_id(file), "kind": "file", "label": file},
            "epistemic_status": "OBSERVED",
            "metadata": {"basis": "git-diff-name-only"},
        }
        for file in changed_files
    ]
    _, created = append_project_event(
        repo=root,
        event_type="change.observed",
        subject={"id": cid, "kind": "change", "label": cid},
        epistemic_status="OBSERVED",
        payload={
            "repository_fingerprint": repository,
            "base_tree": base_tree,
            "candidate_tree": candidate_tree,
            "base_sha": (envelope.get("base") or {}).get("sha"),
            "candidate_sha": (envelope.get("candidate") or {}).get("sha"),
            "changed_files": changed_files,
        },
        relations=file_relations,
        provenance=provenance,
        actor=event_actor,
        dedupe_key="change:" + cid,
    )
    counts = {"change": 1 if created else 0, "proof": 0, "debt": 0, "understanding": 0}

    proof = envelope.get("proof")
    if isinstance(proof, dict):
        cert = str(proof.get("certificate_id") or "")
        if cert:
            accepted = bool(proof.get("accepted"))
            proof_status = "VERIFIED" if trusted_proof and accepted else "OBSERVED"
            _, was_created = append_project_event(
                repo=root,
                event_type="proof.completed",
                subject={"id": cert, "kind": "proof-certificate", "label": str(proof.get("claim") or "proof")},
                epistemic_status=proof_status,
                payload={
                    "change_id": cid,
                    "claim": str(proof.get("claim") or "unknown"),
                    "accepted": accepted,
                    "certificate_schema": proof.get("certificate_schema"),
                    "authoritative_validation": bool(trusted_proof),
                },
                relations=[
                    {
                        "predicate": "proves",
                        "target": {"id": cid, "kind": "change"},
                        "epistemic_status": proof_status,
                        "metadata": {"authoritative_validation": bool(trusted_proof)},
                    }
                ],
                provenance={
                    **provenance,
                    "producer": "diffwitness-proof",
                    "authoritative_validation": bool(trusted_proof),
                    "imported_by": actor[:128],
                },
                actor=event_actor,
                dedupe_key=f"proof:{cert}:{proof_status.lower()}",
            )
            counts["proof"] += 1 if was_created else 0

    debt = envelope.get("debt")
    if isinstance(debt, dict):
        lineages = sorted(set(str(value) for value in (debt.get("open_lineages") or []) if isinstance(value, str)))
        snapshot_key = f"debt-snapshot:{cid}:{int(debt.get('points') or 0)}:{','.join(lineages)}:{debt.get('budget_passed')}"
        _, was_created = append_project_event(
            repo=root,
            event_type="debt.snapshot",
            subject={"id": cid, "kind": "change", "label": cid},
            epistemic_status="OBSERVED",
            payload={
                "change_id": cid,
                "points": int(debt.get("points") or 0),
                "obligations": len(lineages),
                "budget_passed": debt.get("budget_passed"),
            },
            relations=[],
            provenance={**provenance, "producer": "debt-ledger"},
            actor=event_actor,
            dedupe_key=snapshot_key,
        )
        counts["debt"] += 1 if was_created else 0
        for debt_id in lineages:
            if not debt_id.startswith("DW-"):
                raise ContinuityError(f"invalid Debt Ledger lineage in envelope: {debt_id}")
            _, was_created = append_project_event(
                repo=root,
                event_type="debt.observed",
                subject={"id": debt_id, "kind": "debt", "label": debt_id},
                epistemic_status="OBSERVED",
                payload={"change_id": cid},
                relations=[
                    {
                        "predicate": "introduced_in",
                        "target": {"id": cid, "kind": "change"},
                        "epistemic_status": "OBSERVED",
                    }
                ],
                provenance={**provenance, "producer": "debt-ledger"},
                actor=event_actor,
                dedupe_key=f"debt:{debt_id}:{cid}",
            )
            counts["debt"] += 1 if was_created else 0

    understanding = envelope.get("understanding")
    if isinstance(understanding, dict):
        digest = str(understanding.get("receipt_digest") or "")
        _, was_created = append_project_event(
            repo=root,
            event_type="understanding.recorded",
            subject={"id": "understanding:" + cid, "kind": "understanding", "label": "IdleProof understanding"},
            epistemic_status="OBSERVED",
            payload={
                "change_id": cid,
                "coverage": understanding.get("coverage"),
                "knowledge_debt": understanding.get("knowledge_debt"),
                "feature_coverage": understanding.get("feature_coverage"),
                "feature_debt": understanding.get("feature_debt"),
                "receipt_digest": digest or None,
            },
            relations=[
                {
                    "predicate": "describes",
                    "target": {"id": cid, "kind": "change"},
                    "epistemic_status": "OBSERVED",
                }
            ],
            provenance={**provenance, "producer": "idleproof"},
            actor=event_actor,
            dedupe_key=f"understanding:{cid}:{digest or 'none'}",
        )
        counts["understanding"] += 1 if was_created else 0
    return {"change_id": cid, "created": counts, "changed_files": changed_files}
