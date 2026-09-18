"""Public lifecycle and history operations for existing project declarations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .continuity_events import ContinuityError, append_project_events, continuity_paths, read_project_events
from .continuity_lifecycle_contract import MEMORY_ACTIONS, MEMORY_KINDS, MEMORY_LIFECYCLE_PROFILE, MemoryHistoryValidator, is_memory_lifecycle, lifecycle_view
from .continuity_state import ensure_state
from .gitops import repo_root
from .language import tr
from .view_mode import VIEW_MODES, get_view_mode


def _history(repo: Path, kind: str, identity: str) -> tuple[list[dict], dict]:
    events = read_project_events(continuity_paths(repo).events)
    validator = MemoryHistoryValidator()
    for event in events:
        validator.admit(event)
    current = validator.current.get(identity)
    if current is None or current["assertion"]["subject"]["kind"] != kind:
        raise ContinuityError(f"unknown {kind}: {identity}")
    return events, current


def lifecycle_spec(repo: Path, kind: str, identity: str, action: str, reason: str,
                   replacement_id: str | None = None) -> dict[str, Any]:
    _, current = _history(repo, kind, identity)
    replacement_event_id = None
    if replacement_id is not None:
        _, replacement = _history(repo, kind, replacement_id)
        replacement_event_id = replacement["assertion"]["event_id"]
    return {"event_type": f"{MEMORY_KINDS[kind]}.{MEMORY_ACTIONS[action]}",
            "subject": {"id": identity, "kind": kind}, "epistemic_status": "DECLARED",
            "payload": {"source_event_id": current["assertion"]["event_id"],
                        "previous_revision_event_id": current["revision"]["event_id"], "reason": reason,
                        "replacement_id": replacement_id, "replacement_event_id": replacement_event_id},
            "relations": [], "actor": {"kind": "human", "id": "local-user"}, "dedupe_key": None,
            "provenance": {"producer": "diffwitness", "source": "human-cli", "diffwitness_profile": MEMORY_LIFECYCLE_PROFILE}}


def show_memory(repo: Path, kind: str, identity: str) -> dict[str, Any]:
    events, current = _history(repo, kind, identity)
    lifecycle = lifecycle_view(current["revision"]) if current["action"] else {
        "action": "unreviewed", "active": current["active"], "reason": None,
        "epistemicStatus": None, "sourceEventId": None, "replacementId": None, "replacementEventId": None}
    return {"schema_version": "memory-history-1", "identity": identity, "kind": kind,
            "assertion": current["assertion"], "lifecycle": lifecycle,
            "history": [e for e in events if e["subject"]["id"] == identity],
            "supersedes": [e["subject"]["id"] for e in events if is_memory_lifecycle(e)
                           and e["payload"]["replacement_id"] == identity]}


def add_lifecycle_parsers(sub) -> None:
    for name in (*MEMORY_ACTIONS, "show"):
        command = sub.add_parser(name)
        command.add_argument("identity")
        command.add_argument("--repo", default=".")
        command.add_argument("--json", action="store_true")
        command.add_argument("--view", choices=VIEW_MODES)
        if name != "show":
            command.add_argument("--reason", required=True)
        if name == "supersede":
            command.add_argument("--with", dest="replacement", required=True)


def memory_lifecycle_cli(kind: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"dw {kind}", description=tr(
        "Review memory applicability without rewriting its assertion.", "Réviser l’applicabilité d’un élément de mémoire sans réécrire son assertion."))
    sub = parser.add_subparsers(dest="command", required=True)
    add_lifecycle_parsers(sub)
    args = parser.parse_args(argv)
    try:
        repo = repo_root(args.repo)
        if args.command != "show":
            spec = lifecycle_spec(repo, kind, args.identity, args.command, args.reason, getattr(args, "replacement", None))
            append_project_events(repo=repo, events=[spec])
            ensure_state(repo)
        result = show_memory(repo, kind, args.identity)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            assertion, state = result["assertion"], result["lifecycle"]
            print(f"{assertion['subject'].get('label') or args.identity} [{assertion['epistemic_status']}]")
            translations = {"confirmed": "confirmé", "rejected": "rejeté", "retired": "retiré", "superseded": "remplacé", "unreviewed": "non révisé"}
            print(tr("Applicability: ", "Applicabilité : ") + tr(state["action"], translations[state["action"]]))
            if state["reason"]:
                print(tr("Reason: ", "Raison : ") + state["reason"] + " [DECLARED]")
            if state["replacementId"]:
                print(tr("Replacement: ", "Remplacement : ") + state["replacementId"])
            if result["supersedes"]:
                print(tr("Replaces: ", "Remplace : ") + ", ".join(result["supersedes"]))
            if (args.view or get_view_mode(repo)) == "technical":
                for event in result["history"]:
                    print(f"  {event['event_type']} [{event['epistemic_status']}] {event['event_id']}")
            print(tr("A review is a declared judgment, not executed Proof.", "Une révision est un jugement déclaré, pas une preuve exécutée."))
        return 0
    except (ContinuityError, ValueError) as exc:
        print(tr("Memory action rejected: ", "Action de mémoire refusée : ") + str(exc), file=sys.stderr)
        return 2
