from __future__ import annotations

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
        description="Optional deterministic runtime protection for supported coding agents.",
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
            state = "prêt"
        elif raw.get("installed") and raw.get("activation") == "requires-provider-feature-and-trust":
            state = "hooks installés · approbation du provider encore nécessaire"
        elif raw.get("installed"):
            state = "installé · aucune session live observée depuis l’activation"
        else:
            state = "hooks attendus manquants"
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
        print("DIFFWITNESS · PROTECTION LIVE")
        print()
        if mode == "off":
            print("• Protection live désactivée. C’est optionnel : Proof, Debt et Continuity restent disponibles.")
            print("  Pour l’activer : `dw protect enable`.")
            return
        if mode == "external":
            print("✓ Protection live déléguée à ton harness existant.")
            print("  DiffWitness continue de vérifier le résultat final indépendamment.")
            return
        if mode != "builtin":
            print("⚠ L’état Protect local est invalide ou illisible.")
            print("  Répare cet état avant de compter sur la protection live ; la Proof reste indépendante.")
            return
        print(f"Mode builtin · politique {policy}")
        rows = _provider_rows(status)
        if not rows:
            print("⚠ Aucun agent supporté n’est actuellement relié à Protect.")
        for label, state in rows:
            mark = "✓" if state == "prêt" else "•" if "approbation" in state or "aucune session" in state else "⚠"
            print(f"{mark} {label} : {state}")
        receipts = status.get("receipts") if isinstance(status.get("receipts"), Mapping) else {}
        if receipts.get("integrity") is False:
            print("⚠ L’intégrité de l’historique Protect est invalide.")
        elif int(receipts.get("count") or 0):
            print(f"✓ {int(receipts.get('count') or 0)} observation(s) locale(s), chaîne intacte.")
        else:
            print("• Aucune action runtime n’a encore été observée.")
        print()
        print("Important : Protect bloque/observe des actions pendant le travail ; il ne prouve jamais que le logiciel fonctionne.")
        print("La vérification finale est réalisée séparément par DiffWitness Proof.")
        print("Détails d’ingénierie : `dw view technical` puis `dw protect status`.")
        return

    print(f"Protect: {mode} · policy {policy} · aggregate {status.get('health')}")
    if mode == "builtin":
        for label, state in _provider_rows(status):
            print(f"  {label}: {state}")
        if any("approbation" in state for _, state in _provider_rows(status)):
            print("Provider trust is pending for the listed adapter(s); DiffWitness never bypasses provider-native trust.")
    elif mode == "external":
        print("Runtime safety delegated; Proof/Debt/Continuity remain local and independent.")
    elif mode == "off":
        print("Runtime protection off; Proof/Debt/Continuity remain available.")
    receipts = status.get("receipts") if isinstance(status.get("receipts"), Mapping) else {}
    print(f"Receipts: {int(receipts.get('count') or 0)} · integrity {'ok' if receipts.get('integrity') is not False else 'INVALID'}")
    print("Protect runtime observations are not executable proof.")


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
                print("DIFFWITNESS · CHOIX DE PROTECTION")
                if result["externalHarnessDetected"]:
                    print("✓ Un harness externe fiable a été détecté. Recommandation : déléguer Protect avec `dw protect use external`.")
                elif result["otherHookActivityDetected"]:
                    print("• D’autres hooks existent. DiffWitness peut cohabiter sans les supprimer ; recommandation actuelle : builtin.")
                else:
                    print("✓ Aucun conflit fort détecté. Recommandation : `dw protect enable` si tu veux la protection live builtin.")
            else:
                print(f"Protect recommendation: {result['recommendation']}")
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
                print(f"Historique Protect : {len(values)} observation(s) · intégrité {'OK' if integrity else 'INVALIDE'}")
                if not values:
                    print("Aucune action runtime n’a encore été enregistrée.")
                for item in values:
                    print(f"- {item.get('decision')} · {item.get('category')}/{item.get('rule')} · {item.get('path') or 'projet'}")
            else:
                print(f"Protection receipts: {len(values)} · integrity {'ok' if integrity else 'INVALID'}")
                for item in values:
                    print(f"{item.get('ts')}  {str(item.get('decision')).upper():8}  {item.get('category')} / {item.get('rule')}  {item.get('path') or '-'}")
            return 0 if integrity else 1
    except (ProtectError, OSError, ValueError) as exc:
        print(f"DiffWitness Protect: {exc}", file=sys.stderr)
        return 2
    _render_status(result, guided=guided)
    return 0 if _usable(result) else 1


__all__ = ["protect_surface_cli"]
