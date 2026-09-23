from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from .continuity_contract import ARTIFACT_PROFILE, PROFILE_PROVENANCE_FIELD
from .continuity_events import ContinuityError, _canonical, append_project_events
from .engine_protocol import change_id, repository_fingerprint
from .gitops import repo_root
from .json_contract import strict_json_loads


def _read_envelope(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        value = strict_json_loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise ContinuityError(f"cannot read change envelope {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContinuityError("change envelope must be a JSON object")
    return value, "sha256:" + hashlib.sha256(raw).hexdigest()


def _integer_field(summary: dict[str, Any], field: str, *, section: str, maximum: int | None = None) -> None:
    if field not in summary:
        return
    value = summary[field]
    if (not isinstance(value, int) or isinstance(value, bool) or value < 0
            or (maximum is not None and value > maximum)):
        bound = f" between 0 and {maximum}" if maximum is not None else " >= 0"
        raise ContinuityError(f"change envelope {section}.{field} must be an integer{bound}")


def _validate_summaries(envelope: dict[str, Any]) -> None:
    # Validate supplied scalar values before applying legacy defaults. This is a
    # bounded admission check, not full change-envelope JSON Schema enforcement.
    for section in ("proof", "debt", "understanding"):
        value = envelope.get(section)
        if value is not None and not isinstance(value, dict):
            raise ContinuityError(f"change envelope {section} summary must be an object")
    proof = envelope.get("proof") or {}
    if "accepted" in proof and not isinstance(proof["accepted"], bool):
        raise ContinuityError("change envelope proof.accepted must be a boolean")
    debt = envelope.get("debt") or {}
    _integer_field(debt, "points", section="debt")
    budget = debt.get("budget_passed")
    if budget is not None and not isinstance(budget, bool):
        raise ContinuityError("change envelope debt.budget_passed must be a boolean or null")
    lineages = debt.get("open_lineages")
    if lineages is not None and (not isinstance(lineages, list)
                                or any(not isinstance(value, str) for value in lineages)):
        raise ContinuityError("change envelope debt.open_lineages must be an array of strings")
    understanding = envelope.get("understanding") or {}
    for field in ("coverage", "feature_coverage"):
        _integer_field(understanding, field, section="understanding", maximum=100)
    for field in ("knowledge_debt", "feature_debt"):
        _integer_field(understanding, field, section="understanding")
    # Check every consumed scalar before legacy defaults/string projection.
    for section, fields in (("proof", ("certificate_id", "claim")),
                            ("understanding", ("receipt_digest",)),
                            ("actor", ("kind", "agent", "id"))):
        summary = envelope.get(section)
        if summary is not None and not isinstance(summary, dict):
            raise ContinuityError(f"change envelope {section} must be an object")
        for field in fields:
            if summary is not None and field in summary and not isinstance(summary[field], str):
                raise ContinuityError(f"change envelope {section}.{field} must be a string")
    if "certificate_schema" in proof and (not isinstance(proof["certificate_schema"], str)
                                           and type(proof["certificate_schema"]) is not int):
        raise ContinuityError("change envelope proof.certificate_schema must be a string or integer")
    for section in ("base", "candidate"):
        sha = envelope[section].get("sha")
        if sha is not None and not isinstance(sha, str):
            raise ContinuityError(f"change envelope {section}.sha must be a string or null")


def _validate_envelope(repo: Path, envelope: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(envelope, dict):
        raise ContinuityError("change envelope must be a JSON object")
    # Cover direct callers and overflow (1e999), including discarded extensions.
    try:
        _canonical(envelope)
    except ContinuityError as exc:
        raise ContinuityError("change envelope must contain finite JSON values") from exc
    if envelope.get("schema_version") != "change-envelope-1":
        raise ContinuityError("unsupported change-envelope schema")
    for section in ("repository", "base", "candidate"):
        if not isinstance(envelope.get(section), dict):
            raise ContinuityError(f"change envelope {section} must be an object")
    _validate_summaries(envelope)
    repository = envelope["repository"].get("fingerprint")
    base_tree = envelope["base"].get("tree")
    candidate_tree = envelope["candidate"].get("tree")
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


def _changed_files(repo: Path, envelope: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Read exact tree-derived names; never normalize or truncate an identity.

    The tree pair defines change_id. Commit hints may be ephemeral, missing or
    unrelated and therefore cannot define its file observations. Reuse the bounded
    read-only Git runner: no replacement objects, lazy fetch, prompts or filters.
    """
    from .continuity_git_history import _git

    trees = [envelope[side]["tree"] for side in ("base", "candidate")]
    unavailable = {"status": "unavailable", "reason": "tree-identity-unavailable"}
    if any(not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", tree) for tree in trees):
        return [], unavailable
    deadline = time.monotonic() + 30
    for tree in trees:
        kind = _git(repo, 'cat-file', '-t', tree, limit=16, deadline=deadline, missing_ok=(1, 128))
        if kind is None:
            return [], unavailable
        if kind != b'tree\n':
            raise ContinuityError("change envelope tree identity does not identify a Git tree")
    raw = _git(repo, 'diff-tree', '--no-ext-diff', '--no-textconv', '--no-commit-id',
               '--name-only', '--no-renames', '--ignore-submodules=none', '-r', '-z',
               *trees, '--', limit=1024 * 1024, deadline=deadline)
    if raw and not raw.endswith(b'\0'):
        raise ContinuityError("truncated changed-path output")
    names = raw.split(b'\0')[:-1]
    if len(set(names)) != len(names):
        raise ContinuityError("duplicate changed-path output")
    files, reasons, used = [], {}, 0
    for name in sorted(names):
        reason = None
        try:
            path = name.decode('utf-8', errors='strict')
        except UnicodeDecodeError:
            reason = 'non_utf8'
        else:
            if not path or len(path) > 500 or len(json.dumps(path, ensure_ascii=False).encode('utf-8')) > 512:
                reason = 'label_limit'
            elif len(files) >= 256:
                reason = 'path_limit'
            else:
                cost = len(_canonical([path, _file_relation(path)]).encode('utf-8')) + 2
                if used + cost > 128 * 1024:
                    reason = 'byte_limit'
                else:
                    files.append(path)
                    used += cost
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    coverage = {"status": "partial" if reasons else "complete", "total": len(names),
                "omitted": len(names) - len(files)}
    if reasons:
        coverage["reasons"] = reasons
    return files, coverage


def _file_entity_id(path: str) -> str:
    return "file:" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]


def _file_relation(path: str) -> dict[str, Any]:
    return {"predicate": "affects",
            "target": {"id": _file_entity_id(path), "kind": "file", "label": path},
            "epistemic_status": "OBSERVED", "metadata": {"basis": "git-diff-name-only"}}


def _change_actor(envelope: dict[str, Any]) -> dict[str, str]:
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
    task_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Project a frozen change envelope into one atomic continuity event batch.

    Manual imports are never sufficient to promote an embedded Proof summary to VERIFIED. Guard is
    the only caller that uses ``trusted_proof=True`` after the existing authoritative runner has
    already validated that certificate. All event specs are validated before one append+fsync, so a
    malformed Debt/Understanding item cannot leave a partial Project State history for the change.
    """
    if type(trusted_proof) is not bool:
        raise ContinuityError("trusted_proof must be a boolean supplied by the authoritative runner")
    if not isinstance(actor, str) or not actor.strip():
        raise ContinuityError("envelope importer actor must be a non-empty string")
    root = repo_root(repo)
    source_digest = None
    if path is not None:
        source_envelope, source_digest = _read_envelope(path)
        if envelope is not None and _canonical(envelope) != _canonical(source_envelope):
            raise ContinuityError("supplied change envelope does not match the source file")
        # One parsed byte snapshot supplies both the facts and their provenance.
        # The path may be replaced or disappear while Git identities are checked.
        envelope = source_envelope
    elif envelope is None:
        raise ContinuityError("record_change_envelope requires envelope or path")
    cid, base_tree, candidate_tree = _validate_envelope(root, envelope)
    repository = str((envelope.get("repository") or {}).get("fingerprint"))
    changed_files, path_coverage = _changed_files(root, envelope)
    provenance = {
        "producer": "diffwitness",
        "source": "change-envelope",
        "artifact_schema": "change-envelope-1",
        PROFILE_PROVENANCE_FIELD: ARTIFACT_PROFILE,
    }
    if source_digest:
        provenance["artifact_digest"] = source_digest
    event_actor = _change_actor(envelope)

    debt = envelope.get("debt")
    lineages: list[str] = []
    if debt is not None:
        lineages = sorted(set(debt.get("open_lineages") or []))
        for debt_id in lineages:
            if not debt_id.startswith("DW-"):
                raise ContinuityError(f"invalid Debt Ledger lineage in envelope: {debt_id}")

    specs: list[dict[str, Any]] = [
        {
            "event_type": "change.observed",
            "subject": {"id": cid, "kind": "change", "label": cid},
            "epistemic_status": "OBSERVED",
            "payload": {
                "repository_fingerprint": repository,
                "base_tree": base_tree,
                "candidate_tree": candidate_tree,
                "base_sha": (envelope.get("base") or {}).get("sha"),
                "candidate_sha": (envelope.get("candidate") or {}).get("sha"),
                "changed_files": changed_files,
                **({"changed_files_coverage": path_coverage} if path_coverage["status"] != "complete" else {}),
            },
            "relations": [_file_relation(file) for file in changed_files],
            "provenance": provenance,
            "actor": event_actor,
            "dedupe_key": "change:" + cid,
            "bucket": "change",
        }
    ]

    proof = envelope.get("proof")
    if proof is not None:
        cert = str(proof.get("certificate_id") or "")
        if cert:
            accepted = proof.get("accepted", False)
            proof_status = "VERIFIED" if trusted_proof and accepted else "OBSERVED"
            specs.append(
                {
                    "event_type": "proof.completed",
                    "subject": {"id": cert, "kind": "proof-certificate", "label": str(proof.get("claim") or "proof")},
                    "epistemic_status": proof_status,
                    "payload": {
                        "change_id": cid,
                        "claim": str(proof.get("claim") or "unknown"),
                        "accepted": accepted,
                        "certificate_schema": proof.get("certificate_schema"),
                        "authoritative_validation": bool(trusted_proof),
                    },
                    "relations": [
                        {
                            "predicate": "proves",
                            "target": {"id": cid, "kind": "change"},
                            "epistemic_status": proof_status,
                            "metadata": {"authoritative_validation": bool(trusted_proof)},
                        }
                    ],
                    "provenance": {
                        **provenance,
                        "producer": "diffwitness-proof",
                        "authoritative_validation": bool(trusted_proof),
                        "imported_by": actor[:128],
                    },
                    "actor": event_actor,
                    "dedupe_key": f"proof:{cert}:{proof_status.lower()}",
                    "bucket": "proof",
                }
            )

    if isinstance(debt, dict):
        specs.append(
            {
                "event_type": "debt.snapshot",
                "subject": {"id": cid, "kind": "change", "label": cid},
                "epistemic_status": "OBSERVED",
                "payload": {
                    "change_id": cid,
                    "points": debt.get("points", 0),
                    "obligations": len(lineages),
                    "budget_passed": debt.get("budget_passed"),
                },
                "relations": [],
                "provenance": {**provenance, "producer": "debt-ledger"},
                "actor": event_actor,
                "dedupe_key": f"debt-snapshot:{cid}:{debt.get('points', 0)}:{','.join(lineages)}:{debt.get('budget_passed')}",
                "bucket": "debt",
            }
        )
        for debt_id in lineages:
            specs.append(
                {
                    "event_type": "debt.observed",
                    "subject": {"id": debt_id, "kind": "debt", "label": debt_id},
                    "epistemic_status": "OBSERVED",
                    "payload": {"change_id": cid},
                    "relations": [
                        {
                            "predicate": "introduced_in",
                            "target": {"id": cid, "kind": "change"},
                            "epistemic_status": "OBSERVED",
                        }
                    ],
                    "provenance": {**provenance, "producer": "debt-ledger"},
                    "actor": event_actor,
                    "dedupe_key": f"debt:{debt_id}:{cid}",
                    "bucket": "debt",
                }
            )

    understanding = envelope.get("understanding")
    if understanding is not None:
        digest = str(understanding.get("receipt_digest") or "")
        specs.append(
            {
                "event_type": "understanding.recorded",
                "subject": {"id": "understanding:" + cid, "kind": "understanding", "label": "IdleProof understanding"},
                "epistemic_status": "OBSERVED",
                "payload": {
                    "change_id": cid,
                    "coverage": understanding.get("coverage"),
                    "knowledge_debt": understanding.get("knowledge_debt"),
                    "feature_coverage": understanding.get("feature_coverage"),
                    "feature_debt": understanding.get("feature_debt"),
                    "receipt_digest": digest or None,
                },
                "relations": [
                    {
                        "predicate": "describes",
                        "target": {"id": cid, "kind": "change"},
                        "epistemic_status": "OBSERVED",
                    }
                ],
                "provenance": {**provenance, "producer": "idleproof"},
                "actor": event_actor,
                "dedupe_key": f"understanding:{cid}:{digest or 'none'}",
                "bucket": "understanding",
            }
        )

    if task_refs is not None:
        from .continuity_tasks import native_link_specs

        specs.extend({**spec, "bucket": "task"} for spec in native_link_specs(cid, task_refs))

    # `bucket` is bridge-local accounting and never becomes part of ProjectEvent semantics.
    event_specs = [{key: value for key, value in spec.items() if key != "bucket"} for spec in specs]
    results = append_project_events(repo=root, events=event_specs)
    counts = {"change": 0, "proof": 0, "debt": 0, "understanding": 0}
    if task_refs is not None:
        counts["task"] = 0
    for spec, (_, created) in zip(specs, results, strict=True):
        if created:
            counts[str(spec["bucket"])] += 1
    return {"change_id": cid, "created": counts, "changed_files": changed_files,
            "changed_files_coverage": path_coverage}
