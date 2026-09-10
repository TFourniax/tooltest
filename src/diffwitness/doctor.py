from __future__ import annotations

from .language import tr

import argparse
import json
from pathlib import Path
from typing import Any

from .config import load_config
from .continuity_events import ContinuityError
from .continuity_state import state_status
from .engine_capabilities import EngineCapabilityError, inspect_engine_capabilities
from .engine_protocol import EngineProtocolError
from .gitops import GitError, repo_root
from .protect import ProtectError, protect_status
from .view_mode import VIEW_MODES, get_view_mode
from .readiness import build_readiness, verification_readiness, native_human_lines, repository_human_lines, proof_human_lines


DEFAULT_ENGINE_TIMEOUT_SECONDS = 2.0


def _evidence_state(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    return verification_readiness(repo, config)


def _protect_state(repo: Path) -> tuple[dict[str, Any], bool]:
    try:
        protection = protect_status(repo)
    except ProtectError as exc:
        return {"mode": "invalid", "health": "invalid", "error": str(exc), "adapters": {}, "receipts": {}}, False
    adapters = protection.get("adapters") if isinstance(protection.get("adapters"), dict) else {}
    ready = [name for name, item in adapters.items() if isinstance(item, dict) and item.get("ready")]
    pending = [
        name
        for name, item in adapters.items()
        if isinstance(item, dict) and item.get("installed") and not item.get("ready")
    ]
    broken = [name for name, item in adapters.items() if isinstance(item, dict) and not item.get("installed")]
    result = {**protection, "readyAdapters": sorted(ready), "pendingAdapters": sorted(pending), "brokenAdapters": sorted(broken)}
    # Missing runtime observation is not evidence of pending provider approval.
    # Missing hooks or invalid receipt integrity are separate preflight failures.
    # Protect itself remains optional when off/delegated.
    receipts = result.get("receipts") if isinstance(result.get("receipts"), dict) else {}
    healthy_enough = not broken and receipts.get("integrity") is not False
    return result, healthy_enough


def _continuity_state(repo: Path) -> tuple[dict[str, Any], bool, str | None]:
    try:
        continuity = state_status(repo)
    except ContinuityError as exc:
        return {}, False, str(exc)
    return continuity, True, None


def _engine_state(repo: Path, config: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    engine_config: dict[str, Any] = dict(config.get("engine") or {})
    engine_command = [args.engine] if args.engine else list(engine_config.get("command") or [])
    engine_timeout = float(
        args.engine_timeout if args.engine_timeout is not None else engine_config.get("timeout", DEFAULT_ENGINE_TIMEOUT_SECONDS)
    )
    if not engine_command:
        return {"configured": False, "ready": True, "required": False}, True
    try:
        capabilities = inspect_engine_capabilities(cwd=repo, command=engine_command, timeout=engine_timeout)
    except (EngineCapabilityError, EngineProtocolError) as exc:
        required = bool(engine_config.get("required"))
        return {"configured": True, "ready": False, "required": required, "error": str(exc)}, not required
    return {"configured": True, "ready": True, "required": bool(engine_config.get("required")), "capabilities": capabilities}, True


def _native_lines(native: dict[str, Any], *, guided: bool) -> list[str]:
    return native_human_lines(native, guided=guided)


def _render_guided(
    repo: Path,
    *,
    evidence: dict[str, Any],
    protection: dict[str, Any],
    protect_ok: bool,
    continuity: dict[str, Any],
    continuity_ok: bool,
    continuity_error: str | None,
    engine: dict[str, Any],
    setup_scope: list[str],
    native: dict[str, Any],
) -> None:
    names = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor"}
    print(tr('DIFFWITNESS · GUIDED CHECK-UP', "DIFFWITNESS · CHECK-UP GUIDÉ"))
    print()
    if evidence["ready"]:
        print(tr(f"✓ Ready to run verification: {evidence['command']}", f"✓ Vérification prête : {evidence['command']}"))
        if evidence.get("source") == "detected":
            print(tr(f"  Automatically detected ({evidence.get('reason')}).", f"  Détecté automatiquement ({evidence.get('reason')})."))
    else:
        print(tr('⚠ Project verification is not ready yet.', "⚠ La vérification du projet n’est pas encore prête."))
        if evidence.get("command"):
            print(tr(f"  Candidate command: {evidence['command']}", f"  Commande envisagée : {evidence['command']}"))
        if evidence.get("suggestion"):
            print(tr(f"  Command available on this machine: {evidence['suggestion']}", f"  Commande disponible sur cette machine : {evidence['suggestion']}"))
            print(tr('  DiffWitness does not change your configuration automatically.', "  DiffWitness ne modifie pas ta configuration automatiquement."))
        else:
            print(tr('  Add/configure an executable test command before running verification.', "  Ajoute/configure une commande de test exécutable avant de considérer le projet prêt."))

    if setup_scope:
        print(tr('✓ Agent integration configured: ', "✓ Intégration agent configurée : ") + ", ".join(names.get(item, item) for item in setup_scope))
        for line in _native_lines(native, guided=True):
            print(line)
        if native.get("pendingTrustAdapters"):
            print(tr('  DiffWitness cannot approve or bypass Codex trust: open Codex, review `/hooks` and approve them before the first task.', "  DiffWitness ne peut ni approuver ni contourner la confiance Codex : ouvre Codex, examine `/hooks` et approuve-les avant la première tâche."))
    else:
        print(tr('• Agent integration not configured. Run `dw setup` for Claude Code/Codex.', "• Intégration agent non configurée. Lance `dw setup` pour Claude Code/Codex."))

    mode = protection.get("mode")
    if mode == "builtin":
        adapters = protection.get("adapters") if isinstance(protection.get("adapters"), dict) else {}
        for adapter, item in sorted(adapters.items()):
            if not isinstance(item, dict):
                continue
            label = names.get(adapter, adapter)
            if item.get("ready"):
                print(tr(f"✓ Protection {label}: ready", f"✓ Protection {label} : prête"))
            elif item.get("installed") and item.get("activation") == "awaiting-first-observation":
                print(tr(f"• Protection {label}: hooks installed, not yet observed since activation", f"• Protection {label} : hooks installés, pas encore observés depuis l’activation"))
                print(tr('  Trust is unknown to DiffWitness. Review `/hooks` if Codex requests it, then run a harmless action.', "  Confiance inconnue de DiffWitness. Examine `/hooks` si Codex le demande, puis lance une action sans risque."))
            elif item.get("installed"):
                print(tr(f"• Protection {label}: installed, not yet observed in a session", f"• Protection {label} : installée, pas encore observée en session"))
            else:
                print(tr(f"⚠ Protection {label}: missing hooks — run `dw protect status`", f"⚠ Protection {label} : hooks manquants — lance `dw protect status`"))
    elif mode == "external":
        print(tr('✓ Live protection: delegated to your existing harness', "✓ Protection live : déléguée à ton harness existant"))
    elif mode == "off":
        print(tr('• Live protection: off (optional)', "• Protection live : désactivée (optionnelle)"))
    else:
        print(tr('⚠ Live protection: invalid state — run `dw protect status`', "⚠ Protection live : état invalide — lance `dw protect status`"))
    if not protect_ok:
        print(tr('  Proof remains independent, but live protection needs repair.', "  La Proof reste indépendante, mais la protection live doit être réparée."))

    if continuity_ok:
        count = int(continuity.get("event_count") or 0)
        print(tr(f"✓ Project memory: {'ready, currently empty' if count == 0 else f'{count} verified event(s)'}", f"✓ Mémoire projet : {'prête, vide pour l’instant' if count == 0 else f'{count} événement(s) vérifiés'}"))
    else:
        print(tr(f"⚠ Project memory: invalid ({continuity_error})", f"⚠ Mémoire projet : invalide ({continuity_error})"))

    if engine.get("configured"):
        if engine.get("ready"):
            print(tr('✓ Optional planner: compatible', "✓ Planner optionnel : compatible"))
        elif engine.get("required"):
            print(tr('⚠ Required planner: incompatible — fix it before Gate', "⚠ Planner requis : incompatible — corrige-le avant Gate"))
        else:
            print(tr('• Optional planner: unavailable, Community planner remains usable', "• Planner optionnel : indisponible, le planner Community reste utilisable"))

    print()
    if evidence["ready"] and setup_scope and native.get("pendingTrustAdapters"):
        print(tr('ACTION BEFORE THE FIRST CODEX TASK', "ACTION AVANT LA PREMIÈRE TÂCHE CODEX"))
        print(tr('Open Codex, review `/hooks`, then explicitly approve the project hooks.', "Ouvre Codex, examine `/hooks`, puis approuve explicitement les hooks du projet."))
        print(tr('Once SessionStart actually executes, DiffWitness will mark the integration as locally observed.', "Dès que SessionStart est réellement exécuté, DiffWitness marquera l’intégration comme observée live."))
    elif evidence["ready"] and setup_scope and native.get("runtimeUsable"):
        print(tr('READY TO START THE AGENT', "PRÊT À LANCER L’AGENT"))
        print(tr(f"Simply open `{setup_scope[0]}` in this project and work normally.", f"Ouvre simplement `{setup_scope[0]}` dans ce projet et travaille normalement."))
        print(tr('SessionStart arms the native boundary; Stop verifies the exact change at the end of the task.', "SessionStart armera la frontière native; Stop vérifiera la modification exacte à la fin de la tâche."))
    elif setup_scope and not native.get("runtimeUsable"):
        print(tr('INTEGRATION NEEDS CONFIRMATION', "INTÉGRATION À CONFIRMER"))
        print(tr('Repair hooks or their executable if needed, then observe a harmless invocation in your agent.', "Répare les hooks ou leur exécutable si nécessaire, puis observe une invocation sans risque dans ton agent."))
    elif evidence["ready"]:
        print(tr('Ready to run verification. Run `dw setup` to use Claude Code/Codex without a wrapper.', "Vérification prête. Lance `dw setup` pour utiliser Claude Code/Codex sans wrapper."))
    else:
        print(tr('WHAT TO DO NOW', "À FAIRE MAINTENANT"))
        if evidence.get("suggestion"):
            print(tr(f"Validate and configure this test command: {evidence['suggestion']}", f"Valide puis configure cette commande de test : {evidence['suggestion']}"))
        elif evidence.get("command"):
            print(tr(f"Make this command executable or choose another: {evidence['command']}", f"Rends cette commande exécutable ou choisis-en une autre : {evidence['command']}"))
        else:
            print(tr('Tell DiffWitness how to test the project, then run `dw doctor` again.', "Indique à DiffWitness comment tester le projet, puis relance `dw doctor`."))
    print(tr('Engineering details: `dw view technical`, then `dw doctor`.', "Détails d’ingénierie : `dw view technical` puis `dw doctor`."))


def _render_technical(
    repo: Path,
    *,
    evidence: dict[str, Any],
    protection: dict[str, Any],
    protect_ok: bool,
    continuity: dict[str, Any],
    continuity_ok: bool,
    continuity_error: str | None,
    engine: dict[str, Any],
    setup_scope: list[str],
    native: dict[str, Any],
) -> None:
    print(tr(f"Repository: {repo}", f"Dépôt : {repo}"))
    if evidence["ready"]:
        print(tr(f"Verification command: executable · {evidence['source']} - {evidence['command']}", f"Vérification : prête · {evidence['source']} - {evidence['command']}"))
    else:
        print(tr(f"Verification command: NOT EXECUTABLE · {evidence.get('source')}", f"Vérification : NON PRÊTE · {evidence.get('source')}"))
        if evidence.get("command"):
            print(tr(f"Candidate:  {evidence['command']}", f"Candidate :    {evidence['command']}"))
        if evidence.get("suggestion"):
            print(tr(f"Repair:     {evidence['suggestion']} (suggestion only; config unchanged)", f"Réparation :  {evidence['suggestion']} (suggestion ; configuration inchangée)"))
    print(tr(f"Native:     {', '.join(setup_scope) if setup_scope else 'not configured'}", f"Intégration : {', '.join(setup_scope) if setup_scope else 'non configurée'}"))
    for line in _native_lines(native, guided=False):
        print(line)
    if native.get("pendingTrustAdapters"):
        print(tr("  Codex trust is still user-controlled; approve project hooks in `/hooks` before relying on native execution.", '  La confiance Codex reste contrôlée par l’utilisateur ; approuve les hooks dans `/hooks` avant de compter sur leur exécution native.'))

    mode = protection.get("mode")
    health = protection.get("health")
    if mode == "builtin":
        print(tr(f"Protect:    builtin · aggregate {health} · policy {protection.get('policy')}", f"Protect :     intégré · état global {health} · politique {protection.get('policy')}"))
        adapters = protection.get("adapters") if isinstance(protection.get("adapters"), dict) else {}
        for name, item in sorted(adapters.items()):
            if isinstance(item, dict):
                print(
                    tr(f"  {name}: installed={bool(item.get('installed'))} ready={bool(item.get('ready'))} "
                    f"activation={item.get('activation')}", f"  {name} : installé={bool(item.get('installed'))} prêt={bool(item.get('ready'))} activation={item.get('activation')}")
                )
        if protection.get("pendingAdapters"):
            print(tr("Runtime observation is pending. Provider trust is unknown to DiffWitness; review `/hooks` if Codex requests it, then run a harmless tool call.", 'Observation runtime attendue. La confiance reste inconnue de DiffWitness ; examine `/hooks` si Codex le demande, puis lance une action sans risque.'))
        if protection.get("brokenAdapters"):
            print(tr("Action:     repair missing managed hooks with `dw protect status`.", 'Action :      répare les hooks manquants avec `dw protect status`.'))
    elif mode == "external":
        print(tr("Protect:    external · delegated", 'Protect :     externe · délégué'))
    elif mode == "off":
        print(tr("Protect:    off · optional", 'Protect :     désactivé · optionnel'))
    else:
        print(tr(f"Protect:    INVALID · {protection.get('error')}", f"Protect :     INVALIDE · {protection.get('error')}"))
    receipts = protection.get("receipts") if isinstance(protection.get("receipts"), dict) else {}
    if receipts.get("integrity") is False:
        print(tr("Receipts:   INVALID", 'Reçus :       INVALIDES'))
    elif int(receipts.get("count") or 0):
        print(tr(f"Receipts:   {int(receipts.get('count') or 0)} bounded observation(s) · integrity ok", f"Reçus :       {int(receipts.get('count') or 0)} observation(s) bornée(s) · intégrité valide"))
    print(tr("Boundary:   Protect runtime observations never establish VERIFIED software behavior.", 'Limite :      les observations Protect ne prouvent jamais un comportement logiciel VERIFIED.'))

    if not engine.get("configured"):
        print(tr("Advisory:   Community planner only", 'Conseil :     planner Community uniquement'))
    elif engine.get("ready"):
        capabilities = engine.get("capabilities") or {}
        eng = capabilities.get("engine") or {}
        print(tr(f"Advisory:   compatible - {eng.get('name')} {eng.get('version')}", f"Conseil :     compatible - {eng.get('name')} {eng.get('version')}"))
    else:
        print(tr(f"Advisory:   INVALID - {engine.get('error')}", f"Conseil :     INVALIDE - {engine.get('error')}"))

    if continuity_ok:
        count = int(continuity.get("event_count") or 0)
        print(tr(f"Continuity: ready · {count} ProjectEvent(s)", f"Continuity :  prête · {count} ProjectEvent(s)"))
        counts = continuity.get("counts") or {}
        if counts:
            print(
                tr("Memory:     "
                f"{counts.get('entities', 0)} entities / {counts.get('relations', 0)} relations / "
                f"{counts.get('changes', 0)} changes / {counts.get('debts', 0)} debts", f"Mémoire :     {counts.get('entities', 0)} entités / {counts.get('relations', 0)} relations / {counts.get('changes', 0)} modifications / {counts.get('debts', 0)} dettes")
            )
    else:
        print(tr(f"Continuity: INVALID - {continuity_error}", f"Continuity :  INVALIDE - {continuity_error}"))
    print(tr("Trust:      DECLARED/INFERRED/OBSERVED never auto-upgrade to VERIFIED", 'Confiance :   DECLARED/INFERRED/OBSERVED ne deviennent jamais automatiquement VERIFIED'))
    print(tr("Privacy:    no raw prompts/diffs/agent commands in bounded ProjectEvent/Protect history", 'Confidentialité : aucun prompt/diff/commande agent brut dans l’historique borné ProjectEvent/Protect'))

    if evidence["ready"]:
        print("\nWorkflow:")
        if setup_scope:
            if not native.get("installed") or not native.get("executableAvailable"):
                print(tr("  dw setup                               # repair the recorded native installation", '  dw setup                               # réparer l’installation native enregistrée'))
            elif not native.get("runtimeUsable"):
                print(tr(f"  {setup_scope[0]}                                # observe a harmless invocation; review hooks only if requested", f"  {setup_scope[0]}                                # observer une invocation sans risque ; examiner les hooks uniquement si demandé"))
            elif native.get("pendingTrustAdapters"):
                print(tr("  codex                                 # open project, review `/hooks`, approve explicitly", '  codex                                 # ouvrir le projet, examiner `/hooks`, approuver explicitement'))
                print(tr("  dw setup status                       # after SessionStart, confirm native observation", '  dw setup status                       # après SessionStart, confirmer l’observation native'))
            else:
                print(tr(f"  {setup_scope[0]}                                # primary native workflow", f"  {setup_scope[0]}                                # parcours natif principal"))
            print(tr("  dw guard -- <agent>                   # explicit/manual fallback only", '  dw guard -- <agent>                   # recours explicite/manuel uniquement'))
        else:
            print(tr("  dw setup                               # install native Claude/Codex integration", '  dw setup                               # installer l’intégration native Claude/Codex'))
            print(tr("  dw guard -- <agent>                   # manual fallback", '  dw guard -- <agent>                   # recours manuel'))
        print(tr("  dw protect enable                      # optional live guardrails", '  dw protect enable                      # protection live optionnelle'))


def doctor_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw doctor",
        description=tr("Preflight executable evidence, native integration, optional Protect, advisory engine and Continuity without running tests.", 'Contrôler la disponibilité des vérifications, de l’intégration native, de Protect, du moteur de conseil et de Continuity sans exécuter les tests.'),
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--engine", help=tr("Optional advisory engine executable; overrides configured engine.command", 'Exécutable du moteur de conseil optionnel ; remplace engine.command pour cette invocation'))
    parser.add_argument("--engine-timeout", type=float, default=None)
    parser.add_argument("--view", choices=VIEW_MODES)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        repo = repo_root(args.repo)
        config = load_config(repo, args.config)
        evidence = _evidence_state(repo, config)
        protection, protect_ok = _protect_state(repo)
        continuity, continuity_ok, continuity_error = _continuity_state(repo)
        engine, engine_ok = _engine_state(repo, config, args)
        readiness = build_readiness(repo, config=config, verification=evidence, protection=protection)
        native = readiness["native"]
        scope = native["configuredAdapters"]
        result = {
            "schema": "diffwitness.doctor.v1",
            "repository": str(repo),
            "evidence": evidence,
            "native": native,
            "readiness": readiness,
            "readyScope": "selected-local-preflight-with-engine-and-continuity",
            "protect": protection,
            "continuity": {"ready": continuity_ok, "status": continuity, "error": continuity_error},
            "engine": engine,
            "ready": bool(readiness["scopedProduct"]["ready"] and protect_ok and continuity_ok and engine_ok),
        }
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
            return 0 if result["ready"] else 1
        proof = readiness["currentProof"]
        for line in proof_human_lines(proof):
            print(line)
        print(tr(
            f"Verification command: configured={evidence['configured']} · executable={evidence['executableReady']}",
            f"Commande de vérification : configurée={evidence['configured']} · exécutable={evidence['executableReady']}",
        ))
        print(tr('Doctor checks readiness without running project checks; readiness does not establish Proof coverage.',
                 'Doctor contrôle la disponibilité sans exécuter les tests ; elle ne constitue pas une couverture Proof.'))
        view = args.view or get_view_mode(repo)
        for line in repository_human_lines(readiness["repository"], guided=view == "guided"):
            print(line)
        if view == "guided":
            _render_guided(
                repo,
                evidence=evidence,
                protection=protection,
                protect_ok=protect_ok,
                continuity=continuity,
                continuity_ok=continuity_ok,
                continuity_error=continuity_error,
                engine=engine,
                setup_scope=scope,
                native=native,
            )
        else:
            _render_technical(
                repo,
                evidence=evidence,
                protection=protection,
                protect_ok=protect_ok,
                continuity=continuity,
                continuity_ok=continuity_ok,
                continuity_error=continuity_error,
                engine=engine,
                setup_scope=scope,
                native=native,
            )
        return 0 if result["ready"] else 1
    except GitError as exc:
        print(f"DiffWitness doctor: {exc}")
        if not args.json and (args.view or "guided") == "guided":
            print(tr(
                "Next: Run `dw doctor` inside a Git repository. For a new project, run `git init` first.",
                "Suite : Exécutez `dw doctor` dans un dépôt Git. Pour un nouveau projet, exécutez d’abord `git init`.",
            ))
        return 2
    except (ValueError, OSError) as exc:
        print(f"DiffWitness doctor: {exc}")
        return 2


__all__ = ["doctor_cli"]
