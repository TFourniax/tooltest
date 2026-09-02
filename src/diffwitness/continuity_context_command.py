from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from .continuity_context_enriched import compile_context, render_context
from .gitops import repo_root
from .view_mode import VIEW_MODES, get_view_mode


def _guided_context(context: Mapping[str, Any], *, max_chars: int) -> str:
    lines = ["DIFFWITNESS · MÉMOIRE DU PROJET", "", f"Pour cette tâche : {context.get('task', '')}"]

    components = list(context.get("components") or [])
    if components:
        lines += ["", "Parties du projet qui semblent utiles"]
        for item in components[:8]:
            if isinstance(item, Mapping):
                lines.append(f"- {item.get('path')}")

    objectives = list(context.get("objectives") or [])
    if objectives:
        lines += ["", "Objectifs à garder en tête"]
        for item in objectives[:6]:
            if isinstance(item, Mapping):
                lines.append(f"- {item.get('label')}")

    decisions = list(context.get("decisions") or [])
    if decisions:
        lines += ["", "Décisions déjà prises"]
        for item in decisions[:6]:
            if isinstance(item, Mapping):
                lines.append(f"- {item.get('label')}")

    invariants = list(context.get("invariants") or [])
    if invariants:
        lines += ["", "Règles à ne pas casser"]
        for item in invariants[:6]:
            if isinstance(item, Mapping):
                lines.append(f"- {item.get('label')}")

    debts = list(context.get("knownDebt") or [])
    if debts:
        lines += ["", "Points techniques encore ouverts"]
        for item in debts[:8]:
            if isinstance(item, Mapping):
                lines.append(f"- {item.get('debt_id')} · {item.get('title') or item.get('category') or 'obligation connue'}")

    changes = list(context.get("recentRelatedChanges") or [])
    if changes:
        lines += ["", "Modifications récentes liées"]
        for item in changes[:6]:
            if not isinstance(item, Mapping):
                continue
            proof = item.get("proof") if isinstance(item.get("proof"), Mapping) else {}
            status = "vérifiée" if proof.get("accepted") and proof.get("epistemicStatus") == "VERIFIED" else "historique"
            files = ", ".join(str(value) for value in list(item.get("files") or [])[:3]) or "fichiers non enregistrés"
            lines.append(f"- {files} · {status}")
    else:
        lines += ["", "Aucune modification précédente suffisamment liée n’a été retrouvée."]

    evidence = list(context.get("requiredEvidence") or [])
    actionable = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        command = item.get("command")
        note = item.get("note")
        if command:
            actionable.append(str(command))
        elif item.get("kind") == "native-task-boundary" and note:
            actionable.append(str(note))
    if actionable:
        lines += ["", "Comment DiffWitness vérifiera cette tâche"]
        lines.extend(f"- {item}" for item in actionable[:5])

    warnings = list(context.get("warnings") or [])
    if warnings:
        lines += ["", "À savoir"]
        lines.extend(f"- {item}" for item in warnings[:5])

    lines += [
        "",
        "Cette mémoire sert de contexte et ne remplace jamais les tests/Proof exécutés sur le code exact.",
        "Détails complets : `dw view technical` puis relance `dw context ...`.",
    ]
    text = "\n".join(lines).rstrip() + "\n"
    if len(text) > max_chars:
        return text[: max(1, max_chars - 80)].rstrip() + "\n… contexte raccourci …\n"
    return text


def context_command_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw context",
        description="Compile bounded local project continuity context for a human or coding agent.",
    )
    parser.add_argument("task", nargs="+")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--max-items", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--refresh-structure", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--view", choices=VIEW_MODES)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    task = " ".join(args.task).strip()
    if not task:
        parser.error("task cannot be empty")
    repo = repo_root(args.repo)
    context = compile_context(
        repo,
        task,
        max_items=max(1, min(args.max_items, 50)),
        refresh_structure=bool(args.refresh_structure),
    )
    max_chars = max(1000, args.max_chars)
    if args.json:
        output = json.dumps(context, indent=2, ensure_ascii=False) + "\n"
    else:
        view = args.view or get_view_mode(repo)
        output = _guided_context(context, max_chars=max_chars) if view == "guided" else render_context(context, max_chars=max_chars)
    if args.out:
        out = args.out if args.out.is_absolute() else repo / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output, encoding="utf-8")
        print(f"Context: {out}")
    else:
        print(output, end="")
    return 0


__all__ = ["context_command_cli"]
