from __future__ import annotations

from .language import tr

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from .gitops import repo_root
from .protect import (
    POLICIES,
    ProtectError,
    _iter_receipts,
    detect_external_harness,
    protect_cli,
    protect_status,
    set_protect_mode,
)
from .view_mode import get_view_mode


def _extract_repo(argv: list[str]) -> tuple[list[str], str]:
    cleaned: list[str] = []
    repo = "."
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--repo" and index + 1 < len(argv):
            repo = argv[index + 1]
            index += 2
            continue
        if value.startswith("--repo="):
            repo = value.split("=", 1)[1]
            index += 1
            continue
        cleaned.append(value)
        index += 1
    return cleaned, repo


def _has_json(argv: list[str]) -> bool:
    return "--json" in argv


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dw protect",
        description=tr("Optional deterministic runtime protection for supported coding agents.", 'Protection runtime déterministe optionnelle pour les agents de code pris en charge.'),
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    sub.add_parser("detect")
    enable = sub.add_parser("enable")
    enable.add_argument("--policy", choices=POLICIES, default="standard")
    enable.add_argument("--force", action="store_true")
    sub.add_parser("disable")
    use = sub.add_parser("use")
    use.add_argument("mode", choices=("external", "builtin", "off"))
    use.add_argument("--policy", choices=POLICIES, default="standard")
    use.add_argument("--force", action="store_true")
    log = sub.add_parser("log")
    log.add_argument("--limit", type=int, default=20)
    return parser


def _provider_rows(status: Mapping[str, Any]) -> list[tuple[str, str]]:
    adapters = status.get("adapters") if isinstance(status.get("adapters"), Mapping) else {}
    names = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor"}
    rows: list[tuple[str, str]] = []
    for name, raw in sorted(adapters.items()):
        if not isinstance(raw, Mapping):
            continue
        label = names.get(str(name), str(name))
        if raw.get("ready"):
            state = tr('ready', "prêt")
        elif raw.get("installed") and raw.get("activation") == "awaiting-first-observation":
            state = tr('hooks installed · no live session observed since activation', "hooks installés · aucune session live observée depuis l’activation")
        elif raw.get("installed"):
            state = tr('installed · no live session observed since activation', "installé · aucune session live observée depuis l’activation")
        else:
            state = tr('expected hooks missing', "hooks attendus manquants")
        rows.append((label, state))
    return rows


def _usable(status: Mapping[str, Any]) -> bool:
    if status.get("mode") in {"off", "external"}:
        return True
    adapters = status.get("adapters") if isinstance(status.get("adapters"), Mapping) else {}
    if not adapters:
        return False
    broken = any(isinstance(item, Mapping) and not item.get("installed") for item in adapters.values())
    receipts = status.get("receipts") if isinstance(status.get("receipts"), Mapping) else {}
    return not broken and receipts.get("integrity") is not False


def _render_status(status: Mapping[str, Any], *, guided: bool) -> None:
    mode = str(status.get("mode") or "unknown")
    policy = str(status.get("policy") or "unknown")
    if guided:
        print(tr('DIFFWITNESS · LIVE PROTECTION', "DIFFWITNESS · PROTECTION LIVE"))
        print()
        if mode == "off":
            print(tr('• Live protection is off. It is optional: Proof, Debt and Continuity remain available.', "• Protection live désactivée. C’est optionnel : Proof, Debt et Continuity restent disponibles."))
            print(tr('  To enable it: `dw protect enable`.', "  Pour l’activer : `dw protect enable`."))
            return
        if mode == "external":
            print(tr('✓ Live protection is delegated to your existing harness.', "✓ Protection live déléguée à ton harness existant."))
            print(tr('  DiffWitness continues to verify the final result independently.', "  DiffWitness continue de vérifier le résultat final indépendamment."))
            return
        if mode != "builtin":
            print(tr('⚠ Local Protect state is invalid or unreadable.', "⚠ L’état Protect local est invalide ou illisible."))
            print(tr('  Repair this state before relying on live protection; Proof remains independent.', "  Répare cet état avant de compter sur la protection live ; la Proof reste indépendante."))
            return
        print(tr(f"Builtin mode · policy {policy}", f"Mode builtin · politique {policy}"))
        rows = _provider_rows(status)
        if not rows:
            print(tr('⚠ No supported agent is currently connected to Protect.', "⚠ Aucun agent supporté n’est actuellement relié à Protect."))
        for label, state in rows:
            mark = "✓" if state == tr('ready', "prêt") else "•" if "approbation" in state or tr('no live session', "aucune session") in state else "⚠"
            print(f"{mark} {label} : {state}")
        if any(isinstance(item, Mapping) and item.get("providerTrust") == "unknown" and not item.get("activeSeen")
               for item in (status.get("adapters") or {}).values()):
            print(tr('  Trust is unknown to DiffWitness. Open Codex; review `/hooks` if Codex requests it, then run a harmless action.', "  Confiance inconnue de DiffWitness. Ouvre Codex ; examine `/hooks` si Codex le demande, puis lance une action sans risque."))
        receipts = status.get("receipts") if isinstance(status.get("receipts"), Mapping) else {}
        if receipts.get("integrity") is False:
            print(tr('⚠ Protect history integrity is invalid.', "⚠ L’intégrité de l’historique Protect est invalide."))
        elif int(receipts.get("count") or 0):
            print(tr(f"✓ {int(receipts.get('count') or 0)} local observation(s), chain intact.", f"✓ {int(receipts.get('count') or 0)} observation(s) locale(s), chaîne intacte."))
        else:
            print(tr('• No runtime action has been observed yet.', "• Aucune action runtime n’a encore été observée."))
        print()
        print(tr('Protect blocks/observes actions during work; it never proves that the software works.', "Important : Protect bloque/observe des actions pendant le travail ; il ne prouve jamais que le logiciel fonctionne."))
        print(tr('Final verification is performed separately by DiffWitness Proof.', "La vérification finale est réalisée séparément par DiffWitness Proof."))
        print(tr('Engineering details: `dw view technical`, then `dw protect status`.', "Détails d’ingénierie : `dw view technical` puis `dw protect status`."))
        return

    print(tr(f"Protect: {mode} · policy {policy} · aggregate {status.get('health')}", f"Protect : {mode} · politique {policy} · état global {status.get('health')}"))
    if mode == "builtin":
        for label, state in _provider_rows(status):
            print(f"  {label}: {state}")
        if any(isinstance(item, Mapping) and item.get("providerTrust") == "unknown" and not item.get("activeSeen")
               for item in (status.get("adapters") or {}).values()):
            print(tr("Provider trust is unknown to DiffWitness. Open Codex and review `/hooks` if Codex requests it; then run a harmless tool call.", 'La confiance est inconnue de DiffWitness. Ouvre Codex et examine `/hooks` si Codex le demande ; lance ensuite une action sans risque.'))
    elif mode == "external":
        print(tr("Runtime safety delegated; Proof/Debt/Continuity remain local and independent.", 'Protection runtime déléguée ; Proof/Debt/Continuity restent locaux et indépendants.'))
    elif mode == "off":
        print(tr("Runtime protection off; Proof/Debt/Continuity remain available.", 'Protection runtime désactivée ; Proof/Debt/Continuity restent disponibles.'))
    receipts = status.get("receipts") if isinstance(status.get("receipts"), Mapping) else {}
    print(tr(f"Receipts: {int(receipts.get('count') or 0)} · integrity {'ok' if receipts.get('integrity') is not False else 'INVALID'}", f"Reçus : {int(receipts.get('count') or 0)} · intégrité {'valide' if receipts.get('integrity') is not False else 'INVALIDE'}"))
    print(tr("Protect runtime observations are not executable proof.", 'Les observations runtime Protect ne sont pas une preuve exécutable.'))


def protect_surface_cli(argv: list[str]) -> int:
    # Machine output is delegated untouched so Guided/Technical never fork the JSON contract.
    if _has_json(argv):
        return protect_cli(argv)
    cleaned, repo_arg = _extract_repo(list(argv))
    try:
        repo = repo_root(repo_arg)
    except Exception:
        return protect_cli(argv)
    try:
        guided = get_view_mode(repo) == "guided"
    except Exception:
        guided = False
    try:
        args = _parser().parse_args(cleaned)
        if args.action == "detect":
            result = detect_external_harness(repo)
            if guided:
                print(tr('DIFFWITNESS · PROTECTION CHOICE', "DIFFWITNESS · CHOIX DE PROTECTION"))
                if result["externalHarnessDetected"]:
                    print(tr('✓ A trusted external harness was detected. Recommendation: delegate Protect with `dw protect use external`.', "✓ Un harness externe fiable a été détecté. Recommandation : déléguer Protect avec `dw protect use external`."))
                elif result["otherHookActivityDetected"]:
                    print(tr('• Other hooks exist. DiffWitness can coexist without removing them; current recommendation: builtin.', "• D’autres hooks existent. DiffWitness peut cohabiter sans les supprimer ; recommandation actuelle : builtin."))
                else:
                    print(tr('✓ No strong conflict detected. Recommendation: `dw protect enable` if you want builtin live protection.', "✓ Aucun conflit fort détecté. Recommandation : `dw protect enable` si tu veux la protection live builtin."))
            else:
                print(tr(f"Protect recommendation: {result['recommendation']}", f"Recommandation Protect : {result['recommendation']}"))
                print(json.dumps(result.get("signals") or [], ensure_ascii=False))
            return 0
        if args.action == "enable":
            result = set_protect_mode(repo, "builtin", policy=args.policy, force=args.force)
        elif args.action == "disable":
            result = set_protect_mode(repo, "off")
        elif args.action == "use":
            result = set_protect_mode(repo, args.mode, policy=args.policy, force=args.force)
        elif args.action == "status":
            result = protect_status(repo)
        else:
            values, integrity = _iter_receipts(repo, limit=max(1, min(args.limit, 200)))
            if guided:
                print(tr(f"Protect history: {len(values)} observation(s) · integrity {'OK' if integrity else 'INVALID'}", f"Historique Protect : {len(values)} observation(s) · intégrité {'OK' if integrity else 'INVALIDE'}"))
                if not values:
                    print(tr('No runtime action has been recorded yet.', "Aucune action runtime n’a encore été enregistrée."))
                for item in values:
                    print(f"- {item.get('decision')} · {item.get('category')}/{item.get('rule')} · {item.get('path') or tr('project', 'projet')}")
            else:
                print(tr(f"Protection receipts: {len(values)} · integrity {'ok' if integrity else 'INVALID'}", f"Reçus de protection : {len(values)} · intégrité {'valide' if integrity else 'INVALIDE'}"))
                for item in values:
                    print(f"{item.get('ts')}  {str(item.get('decision')).upper():8}  {item.get('category')} / {item.get('rule')}  {item.get('path') or '-'}")
            return 0 if integrity else 1
    except (ProtectError, OSError, ValueError) as exc:
        print(f"DiffWitness Protect: {exc}", file=sys.stderr)
        return 2
    _render_status(result, guided=guided)
    return 0 if _usable(result) else 1


__all__ = ["protect_surface_cli"]
