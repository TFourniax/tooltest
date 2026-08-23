from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
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


def _resolve_target(conn: sqlite3.Connection, identity: str) -> tuple[str, str | None]:
    row = conn.execute("select kind,label from entities where entity_id=? and lifecycle='active'", (identity,)).fetchone()
    if row:
        return str(row[0]), row[1]
    row = conn.execute("select change_id from changes where change_id=?", (identity,)).fetchone()
    if row:
        return "change", identity
    row = conn.execute("select debt_id,title from debts where debt_id=?", (identity,)).fetchone()
    if row:
        return "debt", row[1] or identity
    row = conn.execute("select component_id,path from structure_components where component_id=?", (identity,)).fetchone()
    if row:
        return "component", row[1]
    # A path is convenient at the CLI; resolve it to the stable provider-neutral component identity.
    row = conn.execute("select component_id,path from structure_components where path=?", (identity.replace('\\', '/'),)).fetchone()
    if row:
        return "component", row[1]
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
        target_kind, target_label = _resolve_target(conn, args.target)
        target_id = args.target
        if target_kind == "component":
            component = conn.execute(
                "select component_id from structure_components where component_id=? or path=?",
                (args.target, args.target.replace('\\', '/')),
            ).fetchone()
            if component:
                target_id = str(component[0])
        payload = _loads(source["payload_json"])
        source_event_id = str(source["source_event_id"])
    finally:
        conn.close()

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
        subject={"id": str(source["entity_id"]), "kind": str(source["kind"]), "label": source["label"]},
        epistemic_status="DECLARED",
        payload=payload,
        relations=[relation],
        provenance={
            "producer": "diffwitness",
            "source": "human-cli",
            "preserves_entity_from_event": source_event_id,
        },
        actor={"kind": "human", "id": "local-user"},
        dedupe_key=f"relation:{source['entity_id']}:{args.predicate}:{target_id}",
    )
    ensure_state(repo)
    status = "recorded" if created else "already present"
    print(f"Relation {status}: {source['entity_id']} -{args.predicate}-> {target_id} [DECLARED]")
    print(f"Event: {event['event_id']}")
    return 0


__all__ = ["relation_cli"]
