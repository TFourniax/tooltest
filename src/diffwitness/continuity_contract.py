"""Canonical vocabulary and existing ProjectEvent compatibility rules.

Discovery is descriptive, not an authority grant or a new event format. Unknown
historical kinds/predicates remain valid under the existing wire syntax.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from .continuity_task_contract import TASK_PROFILE, task_profile_descriptor, validate_task_profile
from .continuity_lifecycle_contract import MEMORY_LIFECYCLE_PROFILE, memory_lifecycle_descriptor, validate_memory_lifecycle
from .continuity_git_contract import GIT_HISTORY_PROFILE, git_history_descriptor, validate_git_history

CONTRACT_VERSION = "project-memory-contract-1"
EVENT_SCHEMA_VERSION = "project-event-1"
_STATUS_MEANINGS = (
    ("DECLARED", "A recorded assertion or policy declaration, not established behavior."),
    ("INFERRED", "A derived hypothesis whose basis and uncertainty must be retained."),
    ("OBSERVED", "An observed artifact, structure or runtime fact; not executed Proof."),
    ("VERIFIED", "Authority belongs to the exact assertion supported by executed Proof."),
)
EPISTEMIC_STATUSES = frozenset(status for status, _ in _STATUS_MEANINGS)
EVENT_TYPE_PATTERN = r"^[a-z][a-z0-9-]{1,31}\.[a-z][a-z0-9-]{1,31}$"
ENTITY_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_.:/@-]{0,255}$"
ENTITY_KIND_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
RELATION_PREDICATE_PATTERN = r"^[a-z][a-z0-9_.-]{0,63}$"
MAX_EVENT_BYTES = 256 * 1024
MAX_BATCH_EVENTS = 2048
MAX_RELATIONS = 256
MAX_LABEL_CHARS = 500

ENTITY_KINDS = (
    "task", "objective", "decision", "invariant", "failed-approach", "feature",
    "component", "symbol", "dependency", "change", "proof-certificate", "debt",
    "understanding", "file", "external-module", "git-commit", "git-message",
)
HUMAN_DECLARABLE_RELATIONS = frozenset({
    "motivated_by", "affects", "introduced_in", "created", "protects", "constrains",
    "informed", "supersedes", "depends_on", "serves", "related_to",
})
KNOWN_RELATIONS = HUMAN_DECLARABLE_RELATIONS | frozenset({
    "served_by", "affected", "proves", "describes", "refreshed_in", "reopened_in",
    "imports", "calls-name", "worked_on", "motivates",
})
PROJECTION_LIFECYCLES = frozenset({"active", "inactive"})
INACTIVE_EVENT_SUFFIXES = (".superseded", ".retired", ".resolved")
PROFILE_PROVENANCE_FIELD = "diffwitness_profile"
DECLARATION_PROFILE = "project-memory-declaration-1"
ARTIFACT_PROFILE = "project-memory-artifact-1"
DEBT_LIFECYCLE_PROFILE = "project-memory-debt-lifecycle-1"
RELATION_PROFILE = "project-memory-relation-1"
DEBT_LIFECYCLE_SPECS = {
    name: {"epistemic_status": "DECLARED" if name in {"accepted", "unaccepted"} else "OBSERVED",
           "change_relation": {"introduced": "introduced_in", "refreshed": "refreshed_in",
                               "reopened": "reopened_in"}.get(name)}
    for name in ("introduced", "refreshed", "accepted", "unaccepted", "resolved", "reopened")
}
DEBT_SIGNAL_FIELDS = {
    **dict.fromkeys(("category", "rule_id", "title", "severity", "measurement", "path"), "string"),
    "points": "nonnegative-integer", "line": "positive-integer", "end_line": "positive-integer",
}
OBJECTIVE_PRIORITIES = ("low", "normal", "high", "critical")
_DECLARATION_SPECS = {
    "objective.declared": {
        "subject_kind": "objective",
        "payload_fields": {"why": "nullable-string", "priority": "priority"},
        "relations": {"served_by": "component"},
    },
    "decision.recorded": {
        "subject_kind": "decision",
        "payload_fields": {"why": "nullable-string", "alternatives": "string-list"},
        "relations": {"motivated_by": "objective", "affects": "component", "created": "debt"},
    },
    "invariant.declared": {
        "subject_kind": "invariant",
        "payload_fields": {"why": "nullable-string", "critical": "boolean"},
        "relations": {"constrains": "component", "protects": "objective"},
    },
    "approach.failed": {
        "subject_kind": "failed-approach",
        "payload_fields": {"reason": "string"},
        "relations": {"informed": "decision", "affected": "component", "created": "debt"},
    },
}

_ARTIFACT_SPECS = {
    "change.observed": {
        "subject_kind": "change", "producer": "diffwitness",
        "payload_fields": {
            "repository_fingerprint": "nonempty-string", "base_tree": "nonempty-string",
            "candidate_tree": "nonempty-string", "base_sha": "nullable-string",
            "candidate_sha": "nullable-string", "changed_files": "string-list",
        },
        "relations": {"affects": "file"},
    },
    "proof.completed": {
        "subject_kind": "proof-certificate", "producer": "diffwitness-proof",
        "payload_fields": {
            "change_id": "nonempty-string", "claim": "nonempty-string",
            "accepted": "boolean", "certificate_schema": "nullable-schema",
            "authoritative_validation": "boolean",
        },
        "relations": {"proves": "change"},
    },
    "debt.snapshot": {
        "subject_kind": "change", "producer": "debt-ledger",
        "payload_fields": {"change_id": "nonempty-string", "points": "nonnegative-integer",
                           "obligations": "nonnegative-integer", "budget_passed": "nullable-boolean"},
        "relations": {},
    },
    "debt.observed": {
        "subject_kind": "debt", "producer": "debt-ledger",
        "payload_fields": {"change_id": "nonempty-string"},
        "relations": {"introduced_in": "change"},
    },
    "understanding.recorded": {
        "subject_kind": "understanding", "producer": "idleproof",
        "payload_fields": {
            "change_id": "nonempty-string", "coverage": "nullable-percentage",
            "feature_coverage": "nullable-percentage", "knowledge_debt": "nullable-nonnegative-integer",
            "feature_debt": "nullable-nonnegative-integer", "receipt_digest": "nullable-string",
        },
        "relations": {"describes": "change"},
    },
}


def _matches_payload_field(rule: str, value: Any) -> bool:
    if rule.startswith("nullable-"):
        return value is None or _matches_payload_field(rule.removeprefix("nullable-"), value)
    if rule == "nonempty-string":
        return isinstance(value, str) and bool(value.strip())
    if rule == "schema":
        return isinstance(value, str) or type(value) is int
    if rule == "nonnegative-integer":
        return type(value) is int and value >= 0
    if rule == "positive-integer":
        return type(value) is int and value >= 1
    if rule == "percentage":
        return type(value) is int and 0 <= value <= 100
    if rule == "string":
        return isinstance(value, str)
    if rule == "boolean":
        return isinstance(value, bool)
    if rule == "string-list":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if rule == "priority":
        return value in OBJECTIVE_PRIORITIES
    return False


def validate_admission_profile(event: dict[str, Any]) -> None:
    """Validate an explicitly selected profile after legacy envelope validation.

    Unprofiled history retains its original semantics. A profile is a shape and
    declaration boundary, never authenticated provenance or executed Proof.
    """
    provenance = event["provenance"]
    if PROFILE_PROVENANCE_FIELD not in provenance:
        return
    if provenance[PROFILE_PROVENANCE_FIELD] == GIT_HISTORY_PROFILE:
        validate_git_history(event)
        return
    if provenance[PROFILE_PROVENANCE_FIELD] == MEMORY_LIFECYCLE_PROFILE:
        validate_memory_lifecycle(event)
        return
    if provenance[PROFILE_PROVENANCE_FIELD] == TASK_PROFILE:
        validate_task_profile(event)
        return
    if provenance[PROFILE_PROVENANCE_FIELD] == ARTIFACT_PROFILE:
        _validate_artifact_profile(event)
        return
    if provenance[PROFILE_PROVENANCE_FIELD] == DEBT_LIFECYCLE_PROFILE:
        _validate_debt_lifecycle_profile(event)
        return
    if provenance[PROFILE_PROVENANCE_FIELD] == RELATION_PROFILE:
        _validate_relation_profile(event)
        return
    if provenance[PROFILE_PROVENANCE_FIELD] != DECLARATION_PROFILE:
        raise ValueError("unsupported Project Memory admission profile")
    spec = _DECLARATION_SPECS.get(event["event_type"])
    if spec is None or event["subject"]["kind"] != spec["subject_kind"]:
        raise ValueError("declaration profile event type and subject kind do not match")
    if event["epistemic_status"] != "DECLARED":
        raise ValueError("declaration profile requires DECLARED authority")
    for field in ("producer", "source"):
        value = provenance.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"declaration profile requires provenance.{field}")
    actor_id = event["actor"].get("id")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError("declaration profile requires a non-empty string actor.id")
    payload = event["payload"]
    for field, rule in spec["payload_fields"].items():
        if field not in payload or not _matches_payload_field(rule, payload[field]):
            raise ValueError(f"declaration profile payload.{field} must be {rule}")
    if "lifecycle" in payload and (
        not isinstance(payload["lifecycle"], str) or payload["lifecycle"] not in PROJECTION_LIFECYCLES
    ):
        raise ValueError("declaration profile lifecycle must be active or inactive")
    for relation in event.get("relations", []):
        target_kind = spec["relations"].get(relation["predicate"])
        if target_kind is None or relation["target"]["kind"] != target_kind:
            raise ValueError("declaration profile relation predicate and target kind do not match")
        if relation.get("epistemic_status") not in (None, "DECLARED"):
            raise ValueError("declaration profile relations require DECLARED authority")


def _validate_artifact_profile(event: dict[str, Any]) -> None:
    # Local import keeps contract discovery independent of the engine runtime.
    from .engine_protocol import change_id

    kind, payload, provenance = event["event_type"], event["payload"], event["provenance"]
    spec = _ARTIFACT_SPECS.get(kind)
    if spec is None or event["subject"]["kind"] != spec["subject_kind"]:
        raise ValueError("artifact profile event type and subject kind do not match")
    for field, rule in spec["payload_fields"].items():
        if field not in payload or not _matches_payload_field(rule, payload[field]):
            raise ValueError(f"artifact profile payload.{field} must be {rule}")
    for field, value in (("producer", spec["producer"]), ("source", "change-envelope"),
                         ("artifact_schema", "change-envelope-1")):
        if provenance.get(field) != value:
            raise ValueError(f"artifact profile provenance.{field} must be {value}")
    if "artifact_digest" in provenance and not _matches_payload_field("nonempty-string", provenance["artifact_digest"]):
        raise ValueError("artifact profile provenance.artifact_digest must be a non-empty string")
    if not _matches_payload_field("nonempty-string", event["actor"].get("id")):
        raise ValueError("artifact profile requires a non-empty string actor.id")
    if "lifecycle" in payload and (
        not isinstance(payload["lifecycle"], str) or payload["lifecycle"] not in PROJECTION_LIFECYCLES
    ):
        raise ValueError("artifact profile lifecycle must be active or inactive")

    status = "OBSERVED"
    if kind == "proof.completed":
        trusted = payload["authoritative_validation"]
        if provenance.get("authoritative_validation") is not trusted:
            raise ValueError("artifact profile Proof provenance authority mismatch")
        if not _matches_payload_field("nonempty-string", provenance.get("imported_by")):
            raise ValueError("artifact profile Proof requires provenance.imported_by")
        status = "VERIFIED" if trusted and payload["accepted"] else "OBSERVED"
    if event["epistemic_status"] != status:
        raise ValueError("artifact profile epistemic status is inconsistent with the artifact summary")

    subject_id = event["subject"]["id"]
    relations = event.get("relations", [])
    cid = payload.get("change_id")
    if kind == "change.observed":
        expected = change_id(repository=payload["repository_fingerprint"],
                             base_tree=payload["base_tree"], candidate_tree=payload["candidate_tree"])
        if subject_id != expected:
            raise ValueError("artifact profile change identity mismatch")
        files = payload["changed_files"]
        if len(files) != len(set(files)) or len(relations) != len(files):
            raise ValueError("artifact profile changed files and relations do not match")
        for file, relation in zip(files, relations, strict=True):
            target = relation["target"]
            if (target["id"] != "file:" + hashlib.sha256(file.encode("utf-8")).hexdigest()[:24]
                    or target.get("label") != file
                    or relation.get("metadata", {}).get("basis") != "git-diff-name-only"):
                raise ValueError("artifact profile file relation identity mismatch")
    elif kind == "debt.snapshot":
        if subject_id != cid or relations:
            raise ValueError("artifact profile debt snapshot change identity/relations mismatch")
    else:
        if len(relations) != 1 or relations[0]["target"]["id"] != cid:
            raise ValueError("artifact profile relation must reference the payload change_id")
        if kind == "debt.observed" and not subject_id.startswith("DW-"):
            raise ValueError("artifact profile debt lineage must start with DW-")
        if kind == "understanding.recorded" and subject_id != "understanding:" + cid:
            raise ValueError("artifact profile understanding identity mismatch")
    for relation in relations:
        target_kind = spec["relations"].get(relation["predicate"])
        if target_kind is None or relation["target"]["kind"] != target_kind:
            raise ValueError("artifact profile relation predicate and target kind do not match")
        if relation.get("epistemic_status", status) != status:
            raise ValueError("artifact profile relation authority mismatch")
        if kind == "proof.completed" and relation.get("metadata", {}).get("authoritative_validation") is not payload["authoritative_validation"]:
            raise ValueError("artifact profile Proof relation authority mismatch")


def _validate_verification_summary(value: Any) -> None:
    if not isinstance(value, dict) or len(value) > 20:
        raise ValueError("debt lifecycle verification must be a bounded object")
    for key, item in value.items():
        if not isinstance(key, str) or len(key) > 80 or (
            item is not None and type(item) not in (str, int, float, bool)
        ) or (isinstance(item, str) and len(item) > 300):
            raise ValueError("debt lifecycle verification must contain bounded scalar summaries")
    # Finite numbers are enforced by the enclosing canonical JSON boundary.


def _validate_debt_lifecycle_profile(event: dict[str, Any]) -> None:
    payload, provenance = event["payload"], event["provenance"]
    legacy = payload.get("legacy_event_type")
    spec = DEBT_LIFECYCLE_SPECS.get(legacy) if isinstance(legacy, str) else None
    if spec is None or event["event_type"] != "debt." + legacy:
        raise ValueError("debt lifecycle event type does not match legacy_event_type")
    if event["subject"]["kind"] != "debt" or not event["subject"]["id"].startswith("DW-"):
        raise ValueError("debt lifecycle subject must be a DW- debt identity")
    if event["epistemic_status"] != spec["epistemic_status"]:
        raise ValueError("debt lifecycle authority does not match the transition")
    digest = provenance.get("legacy_event_hash")
    if (provenance.get("producer") != "debt-ledger" or provenance.get("source") != "debt-event-1"
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or event.get("dedupe_key") != "legacy-debt:" + digest):
        raise ValueError("debt lifecycle provenance and dedupe identity must match the source event")
    if event["actor"]["kind"] != "ledger-actor" or not _matches_payload_field("nonempty-string", event["actor"].get("id")):
        raise ValueError("debt lifecycle requires a named ledger actor")
    if "change_id" not in payload or not _matches_payload_field("nullable-nonempty-string", payload["change_id"]):
        raise ValueError("debt lifecycle requires a nullable change_id")
    cid = payload["change_id"]
    if cid is not None and not re.fullmatch(r"dwchg_[0-9a-f]{24}", cid):
        raise ValueError("debt lifecycle change_id must be a tree-derived change identity")
    predicate = spec["change_relation"]
    relations = event.get("relations", [])
    if len(relations) != (1 if cid is not None and predicate else 0):
        raise ValueError("debt lifecycle relations must match the transition and available change")
    for relation in relations:
        if (relation["predicate"] != predicate or relation["target"]["kind"] != "change"
                or relation["target"]["id"] != cid or relation.get("epistemic_status", "OBSERVED") != "OBSERVED"
                or relation.get("metadata", {}).get("basis") != "validated-debt-ledger-report"):
            raise ValueError("debt lifecycle relation does not match the observed source change")
    if predicate:
        signal = payload.get("signal")
        if not isinstance(signal, dict):
            raise ValueError("debt lifecycle requires a signal summary object")
        for field, rule in DEBT_SIGNAL_FIELDS.items():
            if field in signal and (not _matches_payload_field(rule, signal[field])
                                    or isinstance(signal[field], str) and len(signal[field]) > 500):
                raise ValueError(f"debt lifecycle signal.{field} must be bounded {rule}")
        if "verification" in signal:
            _validate_verification_summary(signal["verification"])
    if legacy == "accepted" and "reason" not in payload:
        raise ValueError("debt acceptance requires a nullable reason")
    if "reason" in payload and (not _matches_payload_field("nullable-string", payload["reason"])
                                or isinstance(payload["reason"], str) and len(payload["reason"]) > 1000):
        raise ValueError("debt lifecycle reason must be a bounded nullable string")
    if "forced" in payload and type(payload["forced"]) is not bool:
        raise ValueError("debt lifecycle forced must be boolean")
    if "verification" in payload:
        _validate_verification_summary(payload["verification"])


def _validate_relation_profile(event: dict[str, Any]) -> None:
    provenance = event["provenance"]
    preserved = provenance.get("preserves_entity_from_event")
    if event["event_type"] != "relation.declared" or event["epistemic_status"] != "DECLARED":
        raise ValueError("relation profile requires a DECLARED relation-only event")
    if (provenance.get("producer") != "diffwitness" or provenance.get("source") != "human-cli"
            or not isinstance(preserved, str) or not re.fullmatch(r"dwev_[0-9a-f]{24}", preserved)):
        raise ValueError("relation profile requires native declaration and preserved source event provenance")
    if event["actor"]["kind"] != "human" or not _matches_payload_field("nonempty-string", event["actor"].get("id")):
        raise ValueError("relation profile requires a named human declaration actor")
    relations = event.get("relations", [])
    if len(relations) != 1:
        raise ValueError("relation profile requires exactly one declared edge")
    relation = relations[0]
    metadata = relation.get("metadata", {})
    if (relation["predicate"] not in HUMAN_DECLARABLE_RELATIONS
            or relation.get("epistemic_status", "DECLARED") != "DECLARED"
            or metadata.get("basis") != "human-declaration"):
        raise ValueError("relation profile predicate, authority and declaration basis must agree")
    if "note" in metadata and (not isinstance(metadata["note"], str) or len(metadata["note"]) > 1000):
        raise ValueError("relation profile note must be a bounded string")
    expected_key = f"relation:{event['subject']['id']}:{relation['predicate']}:{relation['target']['id']}"
    if event.get("dedupe_key") != expected_key:
        raise ValueError("relation profile dedupe identity must match the edge")
    # Payload is the source snapshot, never replacement entity content or authority.


def compatible_profile_adoption(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Only a valid legacy/native pair may ignore the additive profile marker.

    Validate the legacy assertion under the requested profile too; a marker is
    not a way to bless incompatible history. Neither event is mutated.
    """
    profiles = [event["provenance"].get(PROFILE_PROVENANCE_FIELD) for event in (left, right)]
    known = (ARTIFACT_PROFILE, DEBT_LIFECYCLE_PROFILE, RELATION_PROFILE)
    profile = profiles[1] if profiles[0] is None else profiles[0]
    if profile not in known or profiles not in ([None, profile], [profile, None]):
        return False
    for event in (left, right):
        probe = {**event, "provenance": {**event["provenance"], PROFILE_PROVENANCE_FIELD: profile}}
        try:
            validate_admission_profile(probe)
        except ValueError:
            return False
    return True


def projection_lifecycle(event_type: str, payload: dict[str, Any]) -> str:
    """Preserve the existing projection rule, including suffix precedence."""
    if event_type.endswith(INACTIVE_EVENT_SUFFIXES):
        return "inactive"
    explicit = payload.get("lifecycle")
    return explicit if explicit in PROJECTION_LIFECYCLES else "active"


def project_memory_contract() -> dict[str, Any]:
    """Return fresh JSON metadata without reading a repository or user data.

    Kind names are vocabulary, not a promise that every producer/workflow exists.
    Wire validation remains extensible; hashes establish integrity, not Proof.
    """
    return {
        "schema_version": CONTRACT_VERSION,
        "event_schema": EVENT_SCHEMA_VERSION,
        "admission_profiles": {
            GIT_HISTORY_PROFILE: git_history_descriptor(),
            MEMORY_LIFECYCLE_PROFILE: memory_lifecycle_descriptor(),
            TASK_PROFILE: task_profile_descriptor(),
            DEBT_LIFECYCLE_PROFILE: {
                "provenance_field": PROFILE_PROVENANCE_FIELD,
                "event_types": {"debt." + name: copy.deepcopy(spec) for name, spec in DEBT_LIFECYCLE_SPECS.items()},
                "signal_fields": dict(DEBT_SIGNAL_FIELDS),
                "epistemic_status": "DECLARED acceptance policy; OBSERVED ledger lifecycle, never VERIFIED",
                "required_provenance_fields": ["producer", "source", "legacy_event_hash"],
                "required_actor_fields": ["kind", "id"],
                "unavailable_historical_git_object": "null change_id; no invented relation",
                "additional_payload_fields": "preserve", "unprofiled_history": "preserve",
                "unknown_profile_version": "reject", "grants_proof_authority": False,
            },
            RELATION_PROFILE: {
                "provenance_field": PROFILE_PROVENANCE_FIELD,
                "event_types": {"relation.declared": {"predicates": sorted(HUMAN_DECLARABLE_RELATIONS)}},
                "epistemic_status": "DECLARED",
                "required_provenance_fields": ["producer", "source", "preserves_entity_from_event"],
                "required_actor_fields": ["kind", "id"],
                "replaces_source_entity": False, "authenticates_human_actor": False,
                "additional_payload_fields": "preserve-source-snapshot", "unprofiled_history": "preserve",
                "unknown_profile_version": "reject", "grants_proof_authority": False,
            },
            ARTIFACT_PROFILE: {
                "provenance_field": PROFILE_PROVENANCE_FIELD,
                "event_types": copy.deepcopy(_ARTIFACT_SPECS),
                "epistemic_status": "OBSERVED; Proof follows existing authoritative runner flag and acceptance",
                "additional_payload_fields": "preserve",
                "required_provenance_fields": ["producer", "source", "artifact_schema"],
                "required_actor_fields": ["kind", "id"],
                "proof_authority_consistency": "payload, provenance, relation metadata and status agree; not authentication",
                "unknown_profile_version": "reject",
                "unprofiled_history": "preserve",
                "legacy_dedupe": "validate both assertions; ignore only compatible artifact profile marker",
                "grants_proof_authority": False,
            },
            DECLARATION_PROFILE: {
                "provenance_field": PROFILE_PROVENANCE_FIELD,
                "event_types": copy.deepcopy(_DECLARATION_SPECS),
                "epistemic_status": "DECLARED",
                "required_provenance_fields": ["producer", "source"],
                "required_actor_fields": ["kind", "id"],
                "priority_values": list(OBJECTIVE_PRIORITIES),
                "additional_payload_fields": "preserve",
                "unknown_profile_version": "reject",
                "unprofiled_history": "preserve",
                "grants_proof_authority": False,
            },
        },
        "entity_kinds": {
            kind: {
                "concept": "proof" if kind == "proof-certificate" else kind,
                "identity": "preserve-producer-id",
                "legacy_wire_kind": kind in {"file", "external-module"},
            }
            for kind in ENTITY_KINDS
        },
        "epistemic_statuses": dict(_STATUS_MEANINGS),
        "relations": {
            "known": sorted(KNOWN_RELATIONS),
            "human_declarable": sorted(HUMAN_DECLARABLE_RELATIONS),
            "status_if_omitted": "inherit-current-event-status",
            "identity_fields": ["source_id", "predicate", "target_id"],
            "relation_declaration_replaces_source_entity": False,
        },
        "provenance": {
            "wire_type": "object",
            "recommended_fields": ["producer", "source"],
            "existing_optional_fields": [
                "artifact_schema", "artifact_digest", "legacy_event_hash",
                "preserves_entity_from_event", PROFILE_PROVENANCE_FIELD,
            ],
            "actor_required_fields": ["kind"],
            "actor_optional_fields": ["id"],
            "unknown_fields": "preserve",
            "self_asserted_provenance_is_proof": False,
        },
        "lifecycle": {
            "projection_states": sorted(PROJECTION_LIFECYCLES),
            "explicit_payload_field": "lifecycle",
            "inactive_event_suffixes": list(INACTIVE_EVENT_SUFFIXES),
            "suffix_overrides_payload": True,
            "default_projection_state": "active",
            "supersedes_relation_retires_source": False,
            "lifecycle_transition_upgrades_authority": False,
        },
        "wire": {
            "encoding": "UTF-8",
            "record_endings": ["LF", "CRLF", "CR"],
            "duplicate_json_members": "reject",
            "non_finite_numbers": "reject",
            "event_type_pattern": EVENT_TYPE_PATTERN,
            "entity_id_pattern": ENTITY_ID_PATTERN,
            "entity_kind_pattern": ENTITY_KIND_PATTERN,
            "relation_predicate_pattern": RELATION_PREDICATE_PATTERN,
            "max_canonical_event_bytes": MAX_EVENT_BYTES,
            "max_batch_events": MAX_BATCH_EVENTS,
            "max_relations_per_event": MAX_RELATIONS,
            "max_label_chars": MAX_LABEL_CHARS,
        },
        "authority": {
            "descriptor_grants_verified": False,
            "hash_chain_proves_semantics": False,
            "runtime_observation_is_proof": False,
            "llm_output_is_proof": False,
            "replacement_inherits_prior_authority": False,
        },
        "compatibility": {
            "unknown_kinds": "preserve",
            "unknown_predicates": "preserve",
            "extensions_must_match_wire_syntax": True,
            "rewrite_historical_ids_or_hashes": False,
            "automatic_kind_alias_rewriting": False,
            "declaration_of_kind_implies_producer_available": False,
        },
    }
