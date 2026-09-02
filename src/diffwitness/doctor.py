from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .autodetect import command_available, detect_evidence, suggested_available_command
from .config import load_config
from .continuity_events import ContinuityError
from .continuity_state import state_status
from .engine_capabilities import EngineCapabilityError, inspect_engine_capabilities
from .engine_protocol import EngineProtocolError
from .gitops import GitError, repo_root
from .protect import ProtectError, protect_status
from .view_mode import VIEW_MODES, get_view_mode


DEFAULT_ENGINE_TIMEOUT_SECONDS = 2.0


def _setup_scope(repo: Path) -> list[str]:
    path = repo / ".git" / "diffwitness" / "setup-scope.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(value, dict) or value.get("schema") != "diffwitness.setup-scope.v1":
        return []
    raw = value.get("adapters")
    return [str(item) for item in raw if str(item)] if isinstance(raw, list) else []


def _evidence_state(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    configured = config.get("test")
    if isinstance(configured, str) and configured.strip():
        command = configured.strip()
        ready = command_available(command, cwd=repo)
        return {
            "ready": ready,
            "source": "configured",
            "command": command,
            "suggestion": None if ready else suggested_available_command(command),
            "reason": "configured project evidence" if ready else "configured executable is unavailable",
        }
    plans = detect_evidence(repo)
    for plan in plans:
        if command_available(plan.command, cwd=repo):
            return {
                "ready": True,
                "source": "detected",
                "command": plan.command,
                "confidence": plan.confidence,
                "reason": plan.reason,
                "alternatives": [item.command for item in plans[1:5]],
            }
    if plans:
        first = plans[0]
        return {
            "ready": False,
            "source": "detected-unavailable",
            "command": first.command,
            "confidence": first.confidence,
            "reason": first.reason,
            "suggestion": suggested_available_command(first.command),
        }
    return {"ready": False, "source": "missing", "command": None, "suggestion": None, "reason": "no safe evidence command detected"}


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
    # Pending provider approval is not a broken product state. Missing managed hooks / invalid receipt
    # integrity are. Protect itself remains optional when off/delegated.
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
) -> None:
    names = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor"}
    print("DIFFWITNESS · CHECK-UP GUIDÉ")
    print()
    if evidence["ready"]:
        print(f"✓ Vérification prête : {evidence['command']}")
        if evidence.get("source") == "detected":
            print(f"  Détecté automatiquement ({evidence.get('reason')}).")
    else:
        print("⚠ La vérification du projet n’est pas encore prête.")
        if evidence.get("command"):
            print(f"  Commande envisagée : {evidence['command']}")
        if evidence.get("suggestion"):
            print(f"  Commande disponible sur cette machine : {evidence['suggestion']}")
            print("  DiffWitness ne modifie pas ta configuration automatiquement.")
        else:
            print("  Ajoute/configure une commande de test exécutable avant de considérer le projet prêt.")

    if setup_scope:
        print("✓ Intégration agent : " + ", ".join(names.get(item, item) for item in setup_scope))
        print("  Utilise ces agents normalement : leur fin de tâche déclenche Proof, Debt et Continuity.")
    else:
        print("• Intégration agent non configurée. Lance `dw setup` pour Claude Code/Codex.")

    mode = protection.get("mode")
    if mode == "builtin":
        adapters = protection.get("adapters") if isinstance(protection.get("adapters"), dict) else {}
        for adapter, item in sorted(adapters.items()):
            if not isinstance(item, dict):
                continue
            label = names.get(adapter, adapter)
            if item.get("ready"):
                print(f"✓ Protection {label} : prête")
            elif item.get("installed") and item.get("activation") == "requires-provider-feature-and-trust":
                print(f"• Protection {label} : hooks installés, approbation du provider encore nécessaire")
            elif item.get("installed"):
                print(f"• Protection {label} : installée, pas encore observée en session")
            else:
                print(f"⚠ Protection {label} : hooks manquants — lance `dw protect status`")
    elif mode == "external":
        print("✓ Protection live : déléguée à ton harness existant")
    elif mode == "off":
        print("• Protection live : désactivée (optionnelle)")
    else:
        print("⚠ Protection live : état invalide — lance `dw protect status`")
    if not protect_ok:
        print("  La Proof reste indépendante, mais la protection live doit être réparée.")

    if continuity_ok:
        count = int(continuity.get("event_count") or 0)
        print(f"✓ Mémoire projet : {'prête, vide pour l’instant' if count == 0 else f'{count} événement(s) vérifiés'}")
    else:
        print(f"⚠ Mémoire projet : invalide ({continuity_error})")

    if engine.get("configured"):
        if engine.get("ready"):
            print("✓ Planner optionnel : compatible")
        elif engine.get("required"):
            print("⚠ Planner requis : incompatible — corrige-le avant Gate")
        else:
            print("• Planner optionnel : indisponible, le planner Community reste utilisable")

    print()
    if evidence["ready"] and setup_scope:
        print("PRÊT À CODER")
        print(f"Ouvre simplement `{setup_scope[0]}` dans ce projet et travaille normalement.")
        print("DiffWitness vérifiera la modification exacte à la fin de la tâche.")
    elif evidence["ready"]:
        print("Vérification prête. Lance `dw setup` pour utiliser Claude Code/Codex sans wrapper.")
    else:
        print("À FAIRE MAINTENANT")
        if evidence.get("suggestion"):
            print(f"Valide puis configure cette commande de test : {evidence['suggestion']}")
        elif evidence.get("command"):
            print(f"Rends cette commande exécutable ou choisis-en une autre : {evidence['command']}")
        else:
            print("Indique à DiffWitness comment tester le projet, puis relance `dw doctor`.")
    print("Détails d’ingénierie : `dw view technical` puis `dw doctor`.")


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
) -> None:
    print(f"Repository: {repo}")
    if evidence["ready"]:
        print(f"Evidence:   ready · {evidence['source']} - {evidence['command']}")
    else:
        print(f"Evidence:   NOT READY · {evidence.get('source')}")
        if evidence.get("command"):
            print(f"Candidate:  {evidence['command']}")
        if evidence.get("suggestion"):
            print(f"Repair:     {evidence['suggestion']} (suggestion only; config unchanged)")
    print(f"Native:     {', '.join(setup_scope) if setup_scope else 'not configured'}")

    mode = protection.get("mode")
    health = protection.get("health")
    if mode == "builtin":
        print(f"Protect:    builtin · aggregate {health} · policy {protection.get('policy')}")
        adapters = protection.get("adapters") if isinstance(protection.get("adapters"), dict) else {}
        for name, item in sorted(adapters.items()):
            if isinstance(item, dict):
                print(
                    f"  {name}: installed={bool(item.get('installed'))} ready={bool(item.get('ready'))} "
                    f"activation={item.get('activation')}"
                )
        if protection.get("pendingAdapters"):
            print("Pending provider trust is not treated as a broken adapter; provider approval is never bypassed.")
        if protection.get("brokenAdapters"):
            print("Action:     repair missing managed hooks with `dw protect status`.")
    elif mode == "external":
        print("Protect:    external · delegated")
    elif mode == "off":
        print("Protect:    off · optional")
    else:
        print(f"Protect:    INVALID · {protection.get('error')}")
    receipts = protection.get("receipts") if isinstance(protection.get("receipts"), dict) else {}
    if receipts.get("integrity") is False:
        print("Receipts:   INVALID")
    elif int(receipts.get("count") or 0):
        print(f"Receipts:   {int(receipts.get('count') or 0)} bounded observation(s) · integrity ok")
    print("Boundary:   Protect runtime observations never establish VERIFIED software behavior.")

    if not engine.get("configured"):
        print("Advisory:   Community planner only")
    elif engine.get("ready"):
        capabilities = engine.get("capabilities") or {}
        eng = capabilities.get("engine") or {}
        print(f"Advisory:   compatible - {eng.get('name')} {eng.get('version')}")
    else:
        print(f"Advisory:   INVALID - {engine.get('error')}")

    if continuity_ok:
        count = int(continuity.get("event_count") or 0)
        print(f"Continuity: ready · {count} ProjectEvent(s)")
        counts = continuity.get("counts") or {}
        if counts:
            print(
                "Memory:     "
                f"{counts.get('entities', 0)} entities / {counts.get('relations', 0)} relations / "
                f"{counts.get('changes', 0)} changes / {counts.get('debts', 0)} debts"
            )
    else:
        print(f"Continuity: INVALID - {continuity_error}")
    print("Trust:      DECLARED/INFERRED/OBSERVED never auto-upgrade to VERIFIED")
    print("Privacy:    no raw prompts/diffs/agent commands in bounded ProjectEvent/Protect history")

    if evidence["ready"]:
        print("\nWorkflow:")
        if setup_scope:
            print(f"  {setup_scope[0]}                                # primary native workflow")
            print("  dw guard -- <agent>                   # explicit/manual fallback only")
        else:
            print("  dw setup                               # install native Claude/Codex integration")
            print("  dw guard -- <agent>                   # manual fallback")
        print("  dw protect enable                      # optional live guardrails")


def doctor_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw doctor",
        description="Preflight executable evidence, native integration, optional Protect, advisory engine and Continuity without running tests.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--engine", help="Optional advisory engine executable; overrides configured engine.command")
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
        scope = _setup_scope(repo)
        result = {
            "schema": "diffwitness.doctor.v1",
            "repository": str(repo),
            "evidence": evidence,
            "native": {"adapters": scope, "ready": bool(scope)},
            "protect": protection,
            "continuity": {"ready": continuity_ok, "status": continuity, "error": continuity_error},
            "engine": engine,
            "ready": bool(evidence["ready"] and protect_ok and continuity_ok and engine_ok),
        }
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
            return 0 if result["ready"] else 1
        view = args.view or get_view_mode(repo)
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
            )
        return 0 if result["ready"] else 1
    except (GitError, ValueError, OSError) as exc:
        print(f"DiffWitness doctor: {exc}")
        return 2


__all__ = ["doctor_cli"]
