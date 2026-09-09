from __future__ import annotations

from .language import tr

import argparse
import json
from typing import Any, Mapping

from .gitops import repo_root
from .idleproof_explanation import load_current_explanation
from .view_mode import VIEW_MODES, get_view_mode


def _technical(explanation: Mapping[str, Any]) -> str:
    lines = [
        tr("IdleProof · evidence-backed explanation", 'IdleProof · explication fondée sur les preuves'),
        tr(f"Confidence: {explanation.get('confidence', 'unknown')}", f"Confiance : {explanation.get('confidence', 'unknown')}"),
    ]
    coverage = explanation.get("coverage") if isinstance(explanation.get("coverage"), Mapping) else {}
    if coverage:
        lines.append(tr(f"Coverage: {coverage.get('scope', 'unknown')} · {coverage.get('freshness', 'unknown')}", f"Couverture : {coverage.get('scope', 'unknown')} · {coverage.get('freshness', 'unknown')}"))
    for title, key in ((tr("What changed", 'Ce qui a changé'), "what_changed"), (tr("Why it matters", 'Pourquoi c’est important'), "why_it_matters"), (tr("Verify next", 'Vérifications suivantes'), "verify_next")):
        lines.extend(["", title])
        for item in explanation.get(key) or []:
            lines.append(f"- {item}")
    findings = explanation.get("findings") or []
    if findings:
        lines.extend(["", tr("Evidence-backed findings", 'Constats fondés sur les preuves')])
        for item in findings[:12]:
            if not isinstance(item, Mapping):
                continue
            location = f" · {item['location']}" if item.get("location") else ""
            lines.append(f"- [{item.get('confidence', 'advisory')}] {item.get('title', 'Finding')}{location}")
    lines.extend(["", tr("No LLM or paid API was used for this explanation.", 'Aucun LLM ni API payante n’a été utilisé pour cette explication.')])
    return "\n".join(lines) + "\n"


def _guided(explanation: Mapping[str, Any]) -> str:
    coverage = explanation.get("coverage") if isinstance(explanation.get("coverage"), Mapping) else {}
    covered = coverage.get("current_worktree_covered")
    proof = explanation.get("proof") if isinstance(explanation.get("proof"), Mapping) else {}
    accepted = bool(proof.get("accepted"))
    freshness = str(coverage.get("freshness") or "unknown")

    lines = [tr('DIFFWITNESS · UNDERSTAND', "DIFFWITNESS · COMPRENDRE"), ""]
    if covered is True and accepted:
        lines += [
            tr('✓ The current code version is covered by the latest DiffWitness verification.', "✓ La version actuelle du code est couverte par la dernière vérification DiffWitness."),
            tr('This validation concerns the exact code state currently present; another change will need verification again.', "Cette validation concerne exactement l’état de code actuellement présent ; une nouvelle modification devra être vérifiée à nouveau."),
        ]
    elif freshness == "stale" or covered is False:
        lines += [
            tr('⚠ The latest verification concerns an earlier code version.', "⚠ La dernière vérification concerne une version précédente du code."),
            tr('The current code has changed since: do not consider it verified until a new Proof has run.', "Le code actuel a changé depuis : ne considère pas la version actuelle comme vérifiée tant qu’une nouvelle Proof n’a pas été exécutée."),
        ]
    else:
        lines += [
            tr('⚠ DiffWitness cannot confirm that the latest verification still covers the current code.', "⚠ DiffWitness ne peut pas confirmer que la dernière vérification couvre encore le code actuel."),
            tr('Treat it as historical until another verification.', "Considère-la comme historique jusqu’à une nouvelle vérification."),
        ]

    what = list(explanation.get("what_changed") or [])
    why = list(explanation.get("why_it_matters") or [])
    next_steps = list(explanation.get("verify_next") or [])
    if what:
        lines += ["", tr('What changed', "Ce qui a changé")]
        lines.extend(f"- {item}" for item in what[:6])
    if why:
        lines += ["", tr('Why it matters', "Pourquoi c’est important")]
        lines.extend(f"- {item}" for item in why[:5])
    findings = explanation.get("findings") or []
    if findings:
        lines += ["", tr('Things to know', "Points à connaître")]
        for item in findings[:8]:
            if not isinstance(item, Mapping):
                continue
            label = str(item.get("title") or tr('Finding to review', "Point à vérifier"))
            confidence = str(item.get("confidence") or "advisory")
            qualifier = tr('verified', "vérifié") if confidence == "verified" else tr('consider with caution', "à considérer avec prudence")
            lines.append(f"- {label} ({qualifier})")
    if next_steps:
        lines += ["", tr('What to do next', "À faire ensuite")]
        lines.extend(f"- {item}" for item in next_steps[:6])
    lines += [
        "",
        tr('This explanation comes from local DiffWitness evidence. No LLM or paid API was needed.', "Cette explication vient des preuves locales DiffWitness. Aucun LLM ni API payante n’a été nécessaire."),
        tr('Engineering details: `dw view technical`, then `dw explain`.', "Détails d’ingénierie : `dw view technical` puis `dw explain`."),
    ]
    return "\n".join(lines) + "\n"


def explain_ui_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw explain",
        description=tr("Explain the latest exact-bound DiffWitness change using the saved Guided/Technical view.", 'Expliquer la dernière modification exacte DiffWitness avec la vue Guided/Technical enregistrée.'),
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--view", choices=VIEW_MODES)
    args = parser.parse_args(argv)
    try:
        repo = repo_root(args.repo)
        explanation = load_current_explanation(repo)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(str(exc))
        return 2
    if args.json:
        print(json.dumps(explanation, indent=2, ensure_ascii=False))
        return 0
    view = args.view or get_view_mode(repo)
    print(_guided(explanation) if view == "guided" else _technical(explanation), end="")
    return 0


__all__ = ["explain_ui_cli"]
