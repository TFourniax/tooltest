from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any

from .continuity_events import append_project_event
from .continuity_state import ensure_state
from .gitops import repo_root

_ALLOWED_PREDICATES = {
    "motivated_by",
    "affects",
    "introduced_in",
    "created",
    "protects",
    "constrains",
    "informed",
    "supersedes",
    "depends_on",
    "serves",
    "related_to",
}


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _resolve_target(conn: sqlite3.Connection, identity: str) -> tuple[str, str | None, str]:
    row = conn.execute("select kind,label from entities where entity_id=? and lifecycle='active'", (identity,)).fetchone()
    if row:
        return str(row[0]), row[1], identity
    row = conn.execute("select change_id from changes where change_id=?", (identity,)).fetchone()
    if row:
        return "change", identity, identity
    row = conn.execute("select debt_id,title from debts where debt_id=?", (identity,)).fetchone()
    if row:
        return "debt", row[1] or identity, identity
    row = conn.execute("select component_id,path from structure_components where component_id=?", (identity,)).fetchone()
    if row:
        return "component", row[1], str(row[0])
    normalized = identity.replace("\\", "/")
    row = conn.execute("select component_id,path from structure_components where path=?", (normalized,)).fetchone()
    if row:
        return "component", row[1], str(row[0])
    raise ValueError(f"unknown relation target: {identity}; record/import it before relating to it")


def relation_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw relation",
        description="Declare a typed relation between existing Project State entities without upgrading evidence authority.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("source", help="existing source entity id, e.g. DEC-..., OBJ-..., INV-...")
    add.add_argument("predicate", choices=sorted(_ALLOWED_PREDICATES))
    add.add_argument("target", help="existing target id or indexed component path")
    add.add_argument("--repo", default=".")
    add.add_argument("--note")
    args = parser.parse_args(argv)

    try:
        repo = repo_root(args.repo)
        state = ensure_state(repo, include_structure=True)
        conn = sqlite3.connect(state)
        conn.row_factory = sqlite3.Row
        try:
            source = conn.execute(
                "select entity_id,kind,label,payload_json,source_event_id from entities where entity_id=? and lifecycle='active'",
                (args.source,),
            ).fetchone()
            if source is None:
                raise ValueError(f"unknown active relation source: {args.source}")
            target_kind, target_label, target_id = _resolve_target(conn, args.target)
            payload = _loads(source["payload_json"])
            source_event_id = str(source["source_event_id"])
            source_id = str(source["entity_id"])
            source_kind = str(source["kind"])
            source_label = source["label"]
        finally:
            conn.close()
    except (ValueError, sqlite3.DatabaseError) as exc:
        print(f"DiffWitness relation: {exc}", file=sys.stderr)
        return 2

    relation = {
        "predicate": args.predicate,
        "target": {"id": target_id, "kind": target_kind, "label": target_label},
        "epistemic_status": "DECLARED",
        "metadata": {"basis": "human-declaration"},
    }
    if args.note:
        relation["metadata"]["note"] = args.note[:1000]
    event, created = append_project_event(
        repo=repo,
        event_type="relation.declared",
        subject={"id": source_id, "kind": source_kind, "label": source_label},
        epistemic_status="DECLARED",
        payload=payload,
        relations=[relation],
        provenance={
            "producer": "diffwitness",
            "source": "human-cli",
            "preserves_entity_from_event": source_event_id,
        },
        actor={"kind": "human", "id": "local-user"},
        dedupe_key=f"relation:{source_id}:{args.predicate}:{target_id}",
    )
    ensure_state(repo)
    status = "recorded" if created else "already present"
    print(f"Relation {status}: {source_id} -{args.predicate}-> {target_id} [DECLARED]")
    print(f"Event: {event['event_id']}")
    return 0


__all__ = ["relation_cli"]
