"""Canonical vocabulary and existing ProjectEvent compatibility rules.

Discovery is descriptive, not an authority grant or a new event format. Unknown
historical kinds/predicates remain valid under the existing wire syntax.
"""
from __future__ import annotations

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
                "preserves_entity_from_event",
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
