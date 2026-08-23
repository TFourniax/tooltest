from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .continuity_bridge import record_change_envelope
from .continuity_context import compile_context, render_context
from .continuity_events import append_project_event, continuity_paths, read_project_events
from .continuity_state import ensure_state, rebuild_state, state_status
from .gitops import repo_root
from .structure_provider import component_id_for_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _entity_id(prefix: str, label: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    raw = f"{prefix}\0{label}\0{_now()}".encode("utf-8")
    return prefix + "-" + hashlib.sha256(raw).hexdigest()[:12].upper()


def _relations(values: list[str], predicate: str, kind: str) -> list[dict[str, Any]]:
    return [
        {"predicate": predicate, "target": {"id": value, "kind": kind}, "epistemic_status": "DECLARED"}
        for value in values
    ]


def _normalize_component_path(raw: str) -> str:
    path = raw.strip().replace("\\", "/").removeprefix("./")
    if not path or path.startswith("/") or ".." in Path(path).parts:
        raise ValueError(f"invalid component path: {raw}")
    return path


def _component_relations(paths: list[str], predicate: str = "affects") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in paths:
        path = _normalize_component_path(raw)
        result.append(
            {
                "predicate": predicate,
                "target": {"id": component_id_for_path(path), "kind": "component", "label": path},
                "epistemic_status": "DECLARED",
                "metadata": {"path": path, "basis": "human-declaration"},
            }
        )
    return result


def _print(value: Any, json_mode: bool = False) -> None:
    if json_mode:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False))


def state_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw state",
        description="Inspect, import, or rebuild the reconstructible Project State projection.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--repo", default=".")
    status.add_argument("--json", action="store_true")
    rebuild = sub.add_parser("rebuild")
    rebuild.add_argument("--repo", default=".")
    rebuild.add_argument("--structure", action=argparse.BooleanOptionalAction, default=True)
    ingest = sub.add_parser("ingest-envelope")
    ingest.add_argument("envelope", type=Path)
    ingest.add_argument("--repo", default=".")
    ingest.add_argument("--json", action="store_true")
    events = sub.add_parser("events")
    events.add_argument("--repo", default=".")
    events.add_argument("--limit", type=int, default=20)
    events.add_argument("--json", action="store_true")
    graph = sub.add_parser("graph")
    graph.add_argument("--repo", default=".")
    graph.add_argument("--entity")
    graph.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)

    if args.command == "status":
        value = state_status(repo)
        if args.json:
            _print(value, True)
        else:
            print(f"Project events: {value['event_count']} · {'current' if value['state_current'] else 'rebuild required'}")
            print(f"Events: {value['events_path']}")
            print(f"State:  {value['state_path']}")
            if value["counts"]:
                keys = ("entities", "relations", "changes", "proofs", "debts", "structure_symbols", "structure_edges")
                print("entities/relations/changes/proofs/debts/symbols/edges: " + "/".join(str(value["counts"].get(key, 0)) for key in keys))
            if value["structure_dirty_warning"]:
                print("WARN working tree is dirty; cached structure remains HEAD-bound until explicitly refreshed.")
        return 0

    if args.command == "rebuild":
        path = rebuild_state(repo, include_structure=bool(args.structure))
        print(f"Rebuilt Project State: {path}")
        return 0

    if args.command == "ingest-envelope":
        # A manually supplied envelope is a useful historical artifact, but it is not enough to
        # upgrade its embedded Proof summary to VERIFIED. Guard owns that authoritative bridge.
        result = record_change_envelope(repo=repo, path=args.envelope, actor="human-import", trusted_proof=False)
        ensure_state(repo)
        _print(result, args.json)
        return 0

    if args.command == "events":
        rows = read_project_events(continuity_paths(repo).events)[-max(1, min(args.limit, 500)):]
        if args.json:
            _print(rows, True)
        else:
            for event in rows:
                print(f"{event['timestamp']} {event['event_type']:24} {event['epistemic_status']:8} {event['subject']['id']} {event['event_id']}")
        return 0

    if args.command == "graph":
        import sqlite3

        path = ensure_state(repo)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            if args.entity:
                entities = [
                    dict(row)
                    for row in conn.execute(
                        "select entity_id,kind,label,epistemic_status,lifecycle,updated_at from entities where entity_id=?",
                        (args.entity,),
                    )
                ]
                relations = [
                    dict(row)
                    for row in conn.execute(
                        "select source_id,predicate,target_id,target_kind,epistemic_status from relations where source_id=? or target_id=? order by updated_at desc",
                        (args.entity, args.entity),
                    )
                ]
            else:
                entities = [
                    dict(row)
                    for row in conn.execute(
                        "select entity_id,kind,label,epistemic_status,lifecycle,updated_at from entities where lifecycle='active' order by updated_at desc limit 100"
                    )
                ]
                relations = [
                    dict(row)
                    for row in conn.execute(
                        "select source_id,predicate,target_id,target_kind,epistemic_status from relations where lifecycle='active' order by updated_at desc limit 200"
                    )
                ]
        finally:
            conn.close()
        value = {"entities": entities, "relations": relations}
        if args.json:
            _print(value, True)
        else:
            for entity in entities:
                print(f"{entity['entity_id']} [{entity['kind']}/{entity['epistemic_status']}] {entity['label'] or ''}")
            for relation in relations:
                print(f"  {relation['source_id']} -{relation['predicate']}[{relation['epistemic_status']}]-> {relation['target_id']}")
        return 0
    return 2


def context_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw context",
        description="Compile bounded project continuity context for a human or coding agent.",
    )
    parser.add_argument("task", nargs="+")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--max-items", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--refresh-structure", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    task = " ".join(args.task).strip()
    if not task:
        parser.error("task cannot be empty")
    context = compile_context(
        args.repo,
        task,
        max_items=max(1, min(args.max_items, 50)),
        refresh_structure=bool(args.refresh_structure),
    )
    output = (
        json.dumps(context, indent=2, ensure_ascii=False) + "\n"
        if args.json
        else render_context(context, max_chars=max(1000, args.max_chars))
    )
    if args.out:
        out = args.out if args.out.is_absolute() else repo_root(args.repo) / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output, encoding="utf-8")
        print(f"Context: {out}")
    else:
        print(output, end="")
    return 0


def _declare(
    repo: Path,
    *,
    event_type: str,
    kind: str,
    prefix: str,
    label: str,
    explicit_id: str | None,
    payload: dict[str, Any],
    relations: list[dict[str, Any]],
) -> str:
    entity_id = _entity_id(prefix, label, explicit_id)
    event, _ = append_project_event(
        repo=repo,
        event_type=event_type,
        subject={"id": entity_id, "kind": kind, "label": label},
        epistemic_status="DECLARED",
        payload=payload,
        relations=relations,
        provenance={"producer": "diffwitness", "source": "human-cli"},
        actor={"kind": "human", "id": "local-user"},
        dedupe_key=None,
    )
    ensure_state(repo)
    return event["subject"]["id"]


def objective_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw objective")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("label", nargs="+")
    add.add_argument("--repo", default=".")
    add.add_argument("--id")
    add.add_argument("--why")
    add.add_argument("--priority", choices=["low", "normal", "high", "critical"], default="normal")
    add.add_argument("--component", action="append", default=[])
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    label = " ".join(args.label)
    entity_id = _declare(
        repo,
        event_type="objective.declared",
        kind="objective",
        prefix="OBJ",
        label=label,
        explicit_id=args.id,
        payload={"why": args.why, "priority": args.priority},
        relations=_component_relations(args.component, "served_by"),
    )
    print(f"Objective {entity_id}: {label}")
    return 0


def decision_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw decision")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("record")
    add.add_argument("label", nargs="+")
    add.add_argument("--repo", default=".")
    add.add_argument("--id")
    add.add_argument("--why")
    add.add_argument("--objective", action="append", default=[])
    add.add_argument("--component", action="append", default=[])
    add.add_argument("--alternative", action="append", default=[])
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    label = " ".join(args.label)
    relations = _relations(args.objective, "motivated_by", "objective") + _component_relations(args.component, "affects")
    entity_id = _declare(
        repo,
        event_type="decision.recorded",
        kind="decision",
        prefix="DEC",
        label=label,
        explicit_id=args.id,
        payload={"why": args.why, "alternatives": args.alternative},
        relations=relations,
    )
    print(f"Decision {entity_id}: {label}")
    return 0


def invariant_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw invariant")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("label", nargs="+")
    add.add_argument("--repo", default=".")
    add.add_argument("--id")
    add.add_argument("--why")
    add.add_argument("--critical", action="store_true")
    add.add_argument("--component", action="append", default=[])
    add.add_argument("--objective", action="append", default=[])
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    label = " ".join(args.label)
    relations = _component_relations(args.component, "constrains") + _relations(args.objective, "protects", "objective")
    entity_id = _declare(
        repo,
        event_type="invariant.declared",
        kind="invariant",
        prefix="INV",
        label=label,
        explicit_id=args.id,
        payload={"why": args.why, "critical": bool(args.critical)},
        relations=relations,
    )
    print(f"Invariant {entity_id}: {label}")
    return 0


def failed_approach_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw failed-approach")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("record")
    add.add_argument("label", nargs="+")
    add.add_argument("--repo", default=".")
    add.add_argument("--id")
    add.add_argument("--reason", required=True)
    add.add_argument("--decision", action="append", default=[])
    add.add_argument("--component", action="append", default=[])
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    label = " ".join(args.label)
    relations = _relations(args.decision, "informed", "decision") + _component_relations(args.component, "affected")
    entity_id = _declare(
        repo,
        event_type="approach.failed",
        kind="failed-approach",
        prefix="FAIL",
        label=label,
        explicit_id=args.id,
        payload={"reason": args.reason},
        relations=relations,
    )
    print(f"Failed approach {entity_id}: {label}")
    return 0
