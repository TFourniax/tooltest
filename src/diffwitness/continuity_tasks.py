"""Durable task identity without automatic prompt persistence."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

from .continuity_events import ContinuityError, append_project_events, continuity_paths, read_project_events
from .continuity_state import ensure_state
from .continuity_task_contract import TASK_PROFILE, is_task_edge_event
from .gitops import repo_root
from .language import tr
from .view_mode import VIEW_MODES, get_view_mode


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _spec(kind: str, identity: str, payload: dict[str, Any], *, native: bool = False,
          label: str | None = None, dedupe: str | None = None, relations: list | None = None) -> dict[str, Any]:
    return {
        "event_type": kind,
        "subject": {"id": identity, "kind": "task", **({"label": label} if label is not None else {})},
        "epistemic_status": "OBSERVED" if native and kind in {"task.activated", "task.linked"} else "DECLARED",
        "payload": payload, "relations": relations or [],
        "provenance": {"producer": "diffwitness", "source": "native-session" if native else "human-cli",
                       "diffwitness_profile": TASK_PROFILE},
        "actor": {"kind": "system", "id": "diffwitness-native"} if native else {"kind": "human", "id": "local-user"},
        "dedupe_key": dedupe,
    }


def record_native_task(repo: Path, session_id: str, task: dict[str, Any], boundary_id: str | None = None) -> dict[str, Any]:
    identity = task.get("id")
    payload = {"origin": "native-session", "anchor_sha256": task.get("anchor_sha256"),
               "anchor_chars": task.get("anchor_chars"), "session_sha256": _sha(session_id or "default"),
               "ordinal": task.get("ordinal"), "why": None}
    record = append_project_events(repo=repo, events=[_spec(
        "task.recorded", identity, payload, native=True, label="Task " + str(identity), dedupe="task:" + str(identity)
    )])[0][0]
    if boundary_id is not None:
        append_project_events(repo=repo, events=[_spec(
            "task.activated", identity,
            {"task_event_id": record["event_id"], "session_sha256": payload["session_sha256"], "boundary_id": boundary_id},
            native=True, dedupe=f"task-activation:{boundary_id}:{identity}",
        )])
    return record


def boundary_task_refs(repo: Path, session_id: str, boundary_id: str | None) -> list[dict[str, str]]:
    if boundary_id is None:
        return []  # Old native state has no trustworthy participation boundary.
    digest = _sha(session_id or "default")
    return [{"task_id": event["subject"]["id"], "task_event_id": event["payload"]["task_event_id"],
             "activation_event_id": event["event_id"], "boundary_id": boundary_id}
            for event in read_project_events(continuity_paths(repo).events)
            if event["event_type"] == "task.activated"
            and event["provenance"].get("diffwitness_profile") == TASK_PROFILE
            and event["payload"]["session_sha256"] == digest and event["payload"]["boundary_id"] == boundary_id]


def native_link_specs(change_id: str, refs: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not isinstance(refs, list) or len(refs) > 256:
        raise ContinuityError("native task references must be a list of at most 256 participants")
    result = []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"task_id", "task_event_id", "activation_event_id", "boundary_id"}:
            raise ContinuityError("invalid native task reference fields")
        payload = {key: ref[key] for key in ("task_event_id", "activation_event_id", "boundary_id")}
        payload.update(change_id=change_id, why=None)
        result.append(_link_spec(ref["task_id"], payload, native=True))
    return result


def _link_spec(identity: str, payload: dict[str, Any], *, native: bool) -> dict[str, Any]:
    cid = payload["change_id"]
    status = "OBSERVED" if native else "DECLARED"
    return _spec("task.linked", identity, payload, native=native,
                 dedupe=f"task-change:{payload['activation_event_id']}:{cid}" if native else None,
                 relations=[{"predicate": "worked_on" if native else "motivates",
                             "target": {"id": cid, "kind": "change"}, "epistemic_status": status,
                             "metadata": {"basis": "native-boundary-observation" if native else "explicit-task-declaration",
                                          "causal_proof": False, "why": payload["why"]}}])


def _task_history(repo: Path, identity: str) -> tuple[dict, dict, list[dict]]:
    events = read_project_events(continuity_paths(repo).events)
    history = [event for event in events if event["subject"]["id"] == identity]
    original = next((e for e in history if e["event_type"] == "task.recorded"
                     and e["provenance"].get("diffwitness_profile") == TASK_PROFILE), None)
    latest = next((e for e in reversed(history) if not is_task_edge_event(e)
                   and e["event_type"] != "relation.declared"), None)
    if original is None or latest is None or latest["subject"]["kind"] != "task":
        raise ContinuityError(f"unknown compatible task: {identity}")
    return original, latest, history


def show_task(repo: Path, identity: str) -> dict[str, Any]:
    from .continuity_context import _recent_changes

    original, latest, history = _task_history(repo, identity)
    conn = sqlite3.connect(ensure_state(repo))
    conn.row_factory = sqlite3.Row
    try:
        changes = _recent_changes(conn, [identity], [], limit=256)
        linked = {rel["target"]["id"] for event in history for rel in event.get("relations", [])
                  if rel["target"]["kind"] == "change"}
        changes = [change for change in changes if change["changeId"] in linked]
    finally:
        conn.close()
    return {"schema_version": "task-memory-1", "task": {"id": identity, "label": latest["subject"].get("label"),
            "epistemicStatus": latest["epistemic_status"], "payload": latest["payload"],
            "sourceEventId": latest["event_id"], "recordEventId": original["event_id"]},
            "history": history, "changes": changes}


def task_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw task", description=tr(
        "Save task intent and inspect its durable change history.", "Enregistrer une tâche et retrouver l’historique de ses changements."))
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help=tr("Explicitly save a task label and optional reason", "Enregistrer explicitement une tâche et sa raison"))
    add.add_argument("title")
    add.add_argument("--id")
    add.add_argument("--why")
    describe = commands.add_parser("describe", help=tr("Describe an existing task", "Décrire une tâche existante"))
    describe.add_argument("identity")
    describe.add_argument("--title")
    describe.add_argument("--why")
    link = commands.add_parser("link", help=tr("Declare that a task motivates an existing change; this is not Proof", "Déclarer qu’une tâche motive un changement existant, sans valeur de preuve"))
    link.add_argument("identity")
    link.add_argument("change_id")
    link.add_argument("--why")
    show = commands.add_parser("show", help=tr("Inspect task history and linked changes", "Consulter l’historique de la tâche et les changements liés"))
    show.add_argument("identity")
    for command in (add, describe, link, show):
        command.add_argument("--repo", default=".")
        command.add_argument("--json", action="store_true")
        command.add_argument("--view", choices=VIEW_MODES)
    args = parser.parse_args(argv)
    try:
        repo = repo_root(args.repo)
        if args.command == "show":
            result = show_task(repo, args.identity)
        else:
            if args.command == "add":
                identity = args.id or "TASK-" + uuid.uuid4().hex[:24]
                payload = {"origin": "explicit-declaration", "anchor_sha256": None, "anchor_chars": None,
                           "session_sha256": None, "ordinal": None, "why": args.why}
                spec = _spec("task.recorded", identity, payload, label=args.title, dedupe="task:" + identity)
            else:
                original, latest, _ = _task_history(repo, args.identity)
                if args.command == "describe":
                    if args.title is None and args.why is None:
                        raise ContinuityError("task describe requires --title or --why")
                    payload = copy.deepcopy(original["payload"])
                    payload.update(why=args.why if args.why is not None else latest["payload"]["why"],
                                   source_task_event_id=original["event_id"])
                    spec = _spec("task.described", args.identity, payload,
                                 label=args.title if args.title is not None else latest["subject"]["label"])
                else:
                    spec = _link_spec(args.identity, {"task_event_id": original["event_id"],
                                      "activation_event_id": None, "boundary_id": None,
                                      "change_id": args.change_id, "why": args.why}, native=False)
            event, created = append_project_events(repo=repo, events=[spec])[0]
            ensure_state(repo)
            result = {"task_id": event["subject"]["id"], "event_id": event["event_id"], "created": created}
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.command == "show":
            task = result["task"]
            technical = (args.view or get_view_mode(repo)) == "technical"
            print(f"{task['label']} [{task['epistemicStatus']}]")
            if technical:
                print(task["id"])
            if task["payload"]["why"]:
                print(tr("Why: ", "Raison : ") + task["payload"]["why"])
            if technical:
                for event in result["history"]:
                    print(f"  {event['event_type']} [{event['epistemic_status']}] {event['event_id']}")
            for change in result["changes"]:
                proof = change.get("proof") or {}
                verified = proof.get("accepted") and proof.get("epistemicStatus") == "VERIFIED"
                label = change["changeId"] if technical else ", ".join(change["files"][:4]) or tr("Recorded change", "Changement enregistré")
                status = tr("verified", "vérifié") if verified else tr("historical", "historique")
                print(f"  {label} · {status}")
            if not result["changes"]:
                print(tr("No linked change recorded.", "Aucun changement lié enregistré."))
            print(tr("Task links record intent or participation; they do not prove causality or completion.",
                     "Les liens indiquent une intention ou une participation ; ils ne prouvent ni la causalité ni l’achèvement."))
        else:
            status = tr("recorded", "enregistrée") if result["created"] else tr("already present", "déjà présente")
            print(tr("Task ", "Tâche ") + f"{result['task_id']}: {status}")
        return 0
    except (ContinuityError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"DiffWitness task: {exc}", file=sys.stderr)
        return 2
