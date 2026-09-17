"""Canonical vocabulary and existing ProjectEvent compatibility rules.

Discovery is descriptive, not an authority grant or a new event format. Unknown
historical kinds/predicates remain valid under the existing wire syntax.
"""
from __future__ import annotations

import copy
from typing import Any

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
    "understanding", "file", "external-module",
)
HUMAN_DECLARABLE_RELATIONS = frozenset({
    "motivated_by", "affects", "introduced_in", "created", "protects", "constrains",
    "informed", "supersedes", "depends_on", "serves", "related_to",
})
KNOWN_RELATIONS = HUMAN_DECLARABLE_RELATIONS | frozenset({
    "served_by", "affected", "proves", "describes", "refreshed_in", "reopened_in",
    "imports", "calls-name",
})
PROJECTION_LIFECYCLES = frozenset({"active", "inactive"})
INACTIVE_EVENT_SUFFIXES = (".superseded", ".retired", ".resolved")
PROFILE_PROVENANCE_FIELD = "diffwitness_profile"
DECLARATION_PROFILE = "project-memory-declaration-1"
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


def _matches_payload_field(rule: str, value: Any) -> bool:
    if rule == "nullable-string":
        return value is None or isinstance(value, str)
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
