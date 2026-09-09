from __future__ import annotations

from .language import tr

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .config import load_config
from .debt_budget import ledger_path, merged_debt_config
from .gitops import git, git_metadata_path, repo_root, snapshot_worktree
from .ledger import DebtLedger
from .protect import ProtectError, protect_status
from .view_mode import VIEW_MODES, get_view_mode
from .readiness import build_readiness, verification_readiness, native_human_lines, repository_human_lines


def _evidence_command(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    return verification_readiness(repo, config)


def _generated_untracked(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    parts = normalized.split("/") if normalized else []
    if any(part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".coverage_cache"} for part in parts):
        return True
    name = parts[-1] if parts else normalized
    return bool(re.search(r"\.(?:pyc|pyo)$", name, flags=re.IGNORECASE))


def _working_tree(repo: Path) -> tuple[list[str], bool, list[str]]:
    raw = git(repo, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=normal")
    files: list[str] = []
    generated: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        status = line[:2] if len(line) >= 2 else ""
        value = line[3:] if len(line) >= 4 else line.strip()
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        value = value.strip()
        if status == "??" and _generated_untracked(value):
            generated.append(value)
            continue
        files.append(value)
    unique = sorted(set(files))
    return unique, bool(unique), sorted(set(generated))


def _branch(repo: Path) -> str | None:
    return git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip() or None


def _latest_envelope(repo: Path) -> dict[str, Any] | None:
    path = git_metadata_path(repo, "diffwitness/change-envelope.json")
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"present": True, "readable": False}
    if not isinstance(value, dict):
        return {"present": True, "readable": False}
    proof = value.get("proof") if isinstance(value.get("proof"), dict) else {}
    candidate = value.get("candidate") if isinstance(value.get("candidate"), dict) else {}
    base = value.get("base") if isinstance(value.get("base"), dict) else {}
    return {
        "present": True,
        "readable": True,
        "change_id": value.get("change_id") or value.get("changeId"),
        "schema": value.get("schema") or value.get("schema_version"),
        "proof": {
            "accepted": bool(proof.get("accepted")),
            "claim": proof.get("claim"),
            "certificate_id": proof.get("certificate_id"),
        },
        "candidate": {"tree": candidate.get("tree"), "sha": candidate.get("sha")},
        "base": {"tree": base.get("tree"), "sha": base.get("sha")},
    }


def _tree_for_commit(repo: Path, commit: str | None) -> str | None:
    if not commit:
        return None
    try:
        return git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}").strip() or None
    except Exception:
        return None


def _current_verification(repo: Path, envelope: dict[str, Any] | None) -> dict[str, Any]:
    if not envelope or not envelope.get("readable"):
        return {"status": "unknown", "accepted": False, "reason": "no readable change envelope"}
    proof = envelope.get("proof") if isinstance(envelope.get("proof"), dict) else {}
    accepted = bool(proof.get("accepted"))
    candidate = envelope.get("candidate") if isinstance(envelope.get("candidate"), dict) else {}
    candidate_tree = str(candidate.get("tree") or "").strip() or None
    try:
        current_commit = snapshot_worktree(repo)
        current_tree = _tree_for_commit(repo, current_commit)
    except Exception:
        current_tree = None
    if not candidate_tree or not current_tree:
        return {
            "status": "unknown",
            "accepted": accepted,
            "candidate_tree": candidate_tree,
            "current_tree": current_tree,
            "reason": "current worktree identity could not be compared to the latest envelope",
        }
    if candidate_tree == current_tree:
        return {
            "status": "accepted" if accepted else "unaccepted",
            "accepted": accepted,
            "candidate_tree": candidate_tree,
            "current_tree": current_tree,
            "change_id": envelope.get("change_id"),
        }
    return {
        "status": "stale",
        "accepted": accepted,
        "candidate_tree": candidate_tree,
        "current_tree": current_tree,
        "change_id": envelope.get("change_id"),
        "reason": "the current worktree differs from the latest captured candidate tree",
    }


def _gate_base(repo: Path, envelope: dict[str, Any] | None) -> str:
    if envelope and envelope.get("readable"):
        base = envelope.get("base") if isinstance(envelope.get("base"), dict) else {}
        base_sha = str(base.get("sha") or "").strip()
        if base_sha and _tree_for_commit(repo, base_sha):
            return base_sha
    return "HEAD"


def _protection_status(repo: Path) -> dict[str, Any]:
    try:
        value = protect_status(repo)
    except ProtectError as exc:
        return {
            "schema": "diffwitness.protect-status.v1",
            "mode": "unknown",
            "policy": "unknown",
            "health": "invalid",
            "enabled": False,
            "delegated": False,
            "externalHarnessDetected": False,
            "otherHookActivityDetected": False,
            "adapters": {},
            "receipts": {
                "schema": "diffwitness.protection-summary.v1",
                "count": 0,
                "integrity": False,
                "decisions": {},
                "categories": {},
            },
            "error": str(exc)[:300],
        }
    adapters = value.get("adapters") if isinstance(value.get("adapters"), dict) else {}
    value = dict(value)
    value["ready_adapters"] = sorted(name for name, item in adapters.items() if isinstance(item, dict) and item.get("ready"))
    value["pending_adapters"] = sorted(
        name for name, item in adapters.items() if isinstance(item, dict) and item.get("installed") and not item.get("ready")
    )
    value["broken_adapters"] = sorted(
        name for name, item in adapters.items() if isinstance(item, dict) and not item.get("installed")
    )
    return value


def _native_agent_command(scope: list[str]) -> str | None:
    for adapter in scope:
        if adapter in {"claude", "codex", "cursor"}:
            return adapter
    return None


def build_project_status(repo: Path, *, explicit_config: str | None = None) -> dict[str, Any]:
    config = load_config(repo, explicit_config)
    debt_config = merged_debt_config(config.get("debt") or {})
    ledger = DebtLedger.load(ledger_path(repo, debt_config))
    evidence = _evidence_command(repo, config)
    changed_files, dirty, generated_noise = _working_tree(repo)
    active = ledger.active_items()
    categories = ledger.active_by_category()
    envelope = _latest_envelope(repo)
    current_verification = _current_verification(repo, envelope)
    protection = _protection_status(repo)
    readiness = build_readiness(repo, config=config, verification=evidence, protection=protection, current_verification=current_verification)
    native = readiness["native"]
    setup_scope = native["configuredAdapters"]

    actions: list[dict[str, str]] = []
    if native["configured"] and not native["runtimeUsable"]:
        installed = native["installed"] and native["executableAvailable"]
        actions.append({
            "priority": "high", "kind": "observe-native-agent" if installed else "repair-native-integration",
            "title": "Observe the installed native hooks" if installed else "Repair native integration",
            "command": setup_scope[0] if installed else "dw setup",
            "reason": "Run a harmless provider action; review hooks only if the provider requests it. Trust remains unknown." if installed else "Configured scope is not a working installation. Owned hooks or their recorded executable are missing.",
        })
    if not evidence["ready"]:
        reason = str(evidence.get("problem") or "Verification is not ready.")
        if evidence.get("suggestion"):
            reason += f" Available equivalent detected: {evidence['suggestion']} (not applied automatically)."
        actions.append(
            {
                "priority": "high",
                "kind": "configure-evidence",
                "title": "Finish verification setup",
                "command": "dw doctor",
                "reason": reason,
            }
        )

    broken = list(protection.get("broken_adapters") or [])
    ready_providers = list(protection.get("ready_adapters") or [])
    pending = list(protection.get("pending_adapters") or [])
    if protection.get("health") == "invalid" or broken:
        actions.append(
            {
                "priority": "high",
                "kind": "repair-protection",
                "title": "Repair missing runtime protection hooks",
                "command": "dw protect status",
                "reason": (
                    "Protect cannot safely claim healthy installation"
                    + (f" for: {', '.join(broken)}." if broken else ".")
                    + " Proof remains independent."
                ),
            }
        )

    if dirty:
        if current_verification.get("status") == "accepted":
            actions.append(
                {
                    "priority": "normal",
                    "kind": "current-change-verified",
                    "title": "Current change is already verified",
                    "command": "git status --short",
                    "reason": "The current worktree exactly matches the latest accepted DiffWitness candidate. Any further edit makes this coverage stale.",
                }
            )
        elif evidence["ready"]:
            base = _gate_base(repo, envelope)
            actions.append(
                {
                    "priority": "high",
                    "kind": "verify-change",
                    "title": "Verify the current change",
                    "command": f"dw gate --base {base} --candidate WORKTREE",
                    "reason": f"{len(changed_files)} actionable changed file(s) are present and are not covered by the latest accepted Proof.",
                }
            )
    if active:
        actions.append(
            {
                "priority": "medium",
                "kind": "repay-debt",
                "title": "Review the highest-value debt repayment work",
                "command": "dw plan",
                "reason": f"{len(active)} open obligation(s) account for {ledger.active_points()} debt point(s).",
            }
        )

    if not dirty and evidence["ready"] and not active:
        native_command = _native_agent_command(setup_scope) if native["runtimeUsable"] else None
        if native_command:
            actions.append(
                {
                    "priority": "normal",
                    "kind": "use-native-agent",
                    "title": "Use your configured coding agent normally",
                    "command": native_command,
                    "reason": "Native integration is configured; the task Stop boundary will run Proof, Debt and Continuity automatically. `dw guard` is only a manual fallback.",
                }
            )
        elif not native["configured"]:
            actions.append(
                {
                    "priority": "normal",
                    "kind": "guard-next-change",
                    "title": "Verify the next agent change with the manual boundary",
                    "command": "dw guard -- <agent>",
                    "reason": "No native setup scope is recorded for this repository. Run `dw setup` to use Claude/Codex normally instead.",
                }
            )

    if protection.get("mode") == "builtin" and pending and not broken:
        actions.append(
            {
                "priority": "normal",
                "kind": "activate-provider-protection",
                "title": f"Observe runtime protection for {', '.join(pending)}",
                "command": "codex" if pending == ["codex"] else pending[0],
                "reason": (
                    (f"Already usable now: {', '.join(ready_providers)}. " if ready_providers else "")
                    + "Hooks are installed but have not been observed since activation. Open the provider, review hooks if it requests approval, then run a harmless tool call. Provider trust remains provider-owned and unknown to DiffWitness."
                ),
            }
        )
    if protection.get("mode") == "off":
        actions.append(
            {
                "priority": "normal",
                "kind": "consider-protection",
                "title": "Optionally protect the agent while it works",
                "command": "dw protect enable",
                "reason": "Protect is optional. Enabling it adds deterministic runtime guardrails without changing Proof or Debt semantics.",
            }
        )

    return {
        "schema": "diffwitness.project-status.v1",
        "project": {"name": repo.name, "branch": _branch(repo)},
        "setup": {"native_adapters": setup_scope, "native_ready": native["runtimeUsable"],
                  "native_configured": native["configured"], "native_installed": native["installed"]},
        "readiness": readiness,
        "protection": protection,
        "evidence": evidence,
        "working_tree": {
            "dirty": dirty,
            "changed_file_count": len(changed_files),
            "files": changed_files[:25],
            "truncated": len(changed_files) > 25,
            "generated_untracked_ignored": generated_noise[:25],
        },
        "current_worktree_verification": current_verification,
        "debt": {
            "open_obligations": len(active),
            "points": ledger.active_points(),
            "accepted_points": sum(item.points for item in active if item.accepted),
            "by_category": categories,
        },
        "latest_change_envelope": envelope,
        "next_actions": actions,
        "privacy": {
            "source_code_included": False,
            "raw_diff_included": False,
            "raw_prompt_included": False,
            "raw_agent_events_included": False,
            "raw_commands_included": False,
        },
        "non_claim": "Project status is navigation over runtime protection metadata, executable-readiness preflight, Git identity and the Debt Ledger. Protection observations are not a proof that the application is correct.",
    }


def _protect_line(protection: dict[str, Any]) -> str:
    mode = protection.get("mode")
    health = protection.get("health")
    policy = protection.get("policy")
    if mode == "builtin":
        return tr(f"Protect       builtin · {health} · policy {policy}", f"Protect       intégré · {health} · politique {policy}")
    if mode == "external":
        return tr("Protect       external · delegated", 'Protect       externe · délégué')
    if mode == "off":
        return tr("Protect       off · optional", 'Protect       désactivé · optionnel')
    return f"Protect       {mode or 'unknown'} · {health or 'unknown'}"


def _provider_lines(protection: dict[str, Any], *, guided: bool) -> list[str]:
    adapters = protection.get("adapters") if isinstance(protection.get("adapters"), dict) else {}
    names = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor"}
    lines: list[str] = []
    for adapter, item in sorted(adapters.items()):
        if not isinstance(item, dict):
            continue
        label = names.get(adapter, adapter)
        if item.get("ready"):
            state = tr("ready", 'prêt') if not guided else tr('ready', "prêt")
        elif item.get("installed") and item.get("activation") == "requires-provider-feature-and-trust":
            state = tr("pending provider trust", 'confiance du fournisseur en attente') if not guided else tr('awaiting provider approval', "en attente d’approbation du provider")
        elif item.get("installed"):
            state = tr("installed, not yet observed", 'installé, pas encore observé') if not guided else tr('installed, not yet observed in a session', "installé, pas encore observé en session")
        else:
            state = tr("MISSING HOOKS", 'HOOKS MANQUANTS') if not guided else tr('missing hooks', "hooks manquants")
        prefix = "  " if not guided else "• "
        lines.append(f"{prefix}{label}: {state}")
    return lines


def _action_text(action: dict[str, str], value: dict[str, Any]) -> tuple[str, str]:
    # Translate navigation at display time; the JSON action contract stays canonical.
    kind = action["kind"]
    titles = {
        "observe-native-agent": "Observer les hooks natifs installés",
        "repair-native-integration": "Réparer l’intégration native",
        "configure-evidence": "Terminer la configuration des vérifications",
        "repair-protection": "Réparer les hooks de protection manquants",
        "current-change-verified": "La modification actuelle est déjà vérifiée",
        "verify-change": "Vérifier la modification actuelle",
        "repay-debt": "Examiner les remboursements de dette prioritaires",
        "use-native-agent": "Utiliser normalement l’agent de code configuré",
        "guard-next-change": "Vérifier la prochaine modification avec la frontière manuelle",
        "activate-provider-protection": "Observer la protection runtime : " + ", ".join(value["protection"].get("pending_adapters") or []),
        "consider-protection": "Protéger éventuellement l’agent pendant son travail",
    }
    reasons = {
        "observe-native-agent": "Lance une action sans risque ; examine les hooks uniquement si le fournisseur le demande. La confiance reste inconnue.",
        "repair-native-integration": "La configuration ne suffit pas : des hooks gérés ou leur exécutable enregistré manquent.",
        "configure-evidence": "Les vérifications ne sont pas prêtes. Diagnostic canonique : " + action["reason"],
        "repair-protection": "Protect ne peut pas affirmer que l’installation est saine. La Proof reste indépendante. Adaptateurs manquants : " + ", ".join(value["protection"].get("broken_adapters") or []),
        "current-change-verified": "L’arbre courant correspond exactement au dernier candidat accepté. Toute nouvelle modification rend cette couverture obsolète.",
        "verify-change": f"{value['working_tree']['changed_file_count']} fichier(s) modifié(s) ne sont pas couverts par la dernière Proof acceptée.",
        "repay-debt": f"{value['debt']['open_obligations']} obligation(s) ouverte(s) représentent {value['debt']['points']} point(s) de dette.",
        "use-native-agent": "L’intégration native est configurée ; Stop exécutera automatiquement Proof, Debt et Continuity. `dw guard` reste un recours manuel.",
        "guard-next-change": "Aucune intégration native n’est enregistrée. Lance `dw setup` pour utiliser Claude/Codex normalement.",
        "activate-provider-protection": "Les hooks sont installés mais non observés depuis leur activation. Ouvre le fournisseur, examine les hooks s’il le demande, puis lance une action sans risque. La confiance reste gérée par le fournisseur et inconnue de DiffWitness. Déjà utilisables : " + ", ".join(value["protection"].get("ready_adapters") or []),
        "consider-protection": "Protect est optionnel. Son activation ajoute une protection runtime déterministe sans modifier la sémantique Proof ou Debt.",
    }
    if kind == "configure-evidence" and action["reason"] == "no safe evidence command detected":
        reasons[kind] = "Aucune commande de vérification sûre n’a été détectée."
    return tr(action["title"], titles.get(kind, action["title"])), tr(action["reason"], reasons.get(kind, action["reason"]))


def _render_technical(value: dict[str, Any]) -> str:
    protection = value["protection"]
    evidence = value["evidence"]
    tree = value["working_tree"]
    debt = value["debt"]
    envelope = value.get("latest_change_envelope") or {}
    verification = value.get("current_worktree_verification") or {}
    lines = [
        tr("DIFFWITNESS STATUS · TECHNICAL VIEW", 'DIFFWITNESS STATUS · VUE TECHNIQUE'),
        "",
        *repository_human_lines(value["readiness"]["repository"], guided=False),
        *native_human_lines(value["readiness"]["native"], guided=False),
        _protect_line(protection),
        *_provider_lines(protection, guided=False),
        tr(f"Evidence      {'ready' if evidence['ready'] else 'NOT READY'}", f"Vérification  {'prête' if evidence['ready'] else 'NON PRÊTE'}") + (
            f" ({evidence['source']}: {evidence['command']})" if evidence.get("command") else ""
        ),
        tr(f"Working tree  {tree['changed_file_count']} actionable changed file(s)", f"Arbre courant {tree['changed_file_count']} fichier(s) modifié(s) à traiter") if tree["dirty"] else tr("Working tree  clean", 'Arbre courant propre'),
        tr(f"Proof scope   {verification.get('status', 'unknown')}", f"Portée Proof  {verification.get('status', 'unknown')}"),
        tr(f"Debt          {debt['points']} point(s) · {debt['open_obligations']} open obligation(s)", f"Dette         {debt['points']} point(s) · {debt['open_obligations']} obligation(s) ouverte(s)"),
        tr(f"Last change   {envelope.get('change_id') or ('recorded' if envelope.get('present') else 'none')}", f"Modification  {envelope.get('change_id') or ('enregistrée' if envelope.get('present') else 'aucune')}"),
        "",
        tr("Next actions", 'Actions suivantes'),
    ]
    if tree.get("generated_untracked_ignored"):
        lines.insert(-2, tr(f"Generated     {len(tree['generated_untracked_ignored'])} untracked cache artifact(s) ignored for navigation", f"Générés       {len(tree['generated_untracked_ignored'])} cache(s) non suivi(s) ignoré(s) pour la navigation"))
    for index, action in enumerate(value["next_actions"], start=1):
        title, reason = _action_text(action, value)
        lines.append(f"{index}. {title}")
        lines.append(f"   {action['command']}")
        lines.append(f"   {reason}")
    lines.extend(
        [
            "",
            tr("Protect observations are runtime guard metadata, not executable proof. Gate/Proof claims are exact-tree scoped.", 'Les observations Protect sont des métadonnées de protection runtime, pas une preuve exécutable. Les affirmations Gate/Proof portent sur l’arbre exact.'),
            tr("Prefer less detail? `dw view guided` (or one-off: `dw status --view guided`).", 'Moins de détails ? `dw view guided` (ou une invocation : `dw status --view guided`).'),
        ]
    )
    return "\n".join(lines)


def _guided_heading(value: dict[str, Any]) -> tuple[str, str]:
    evidence = value["evidence"]
    tree = value["working_tree"]
    debt = value["debt"]
    verification = value.get("current_worktree_verification") or {}
    protection = value["protection"]
    if not evidence["ready"]:
        return tr('One configuration step remains', "Il reste une étape de configuration"), tr('DiffWitness cannot yet run verification for this project.', "DiffWitness ne peut pas encore lancer les vérifications de ce projet.")
    native = value["readiness"]["native"]
    if native["configured"] and not native["runtimeUsable"]:
        return (tr('Native integration needs confirmation', "L’intégration native doit être confirmée"), tr('Repair missing hooks/executables or observe a harmless invocation; configuration alone is insufficient.', "Répare les hooks/exécutables manquants ou observe une invocation sans risque ; une configuration seule ne suffit pas."))
    if protection.get("health") == "invalid" or protection.get("broken_adapters"):
        return tr('Live protection needs repair', "La protection live doit être réparée"), tr('An expected protection hook is missing or its local state is invalid. Proof remains independent.', "Un hook de protection attendu manque ou son état local est invalide. La Proof reste indépendante.")
    if tree["dirty"] and verification.get("status") == "accepted":
        return tr('The current change is verified', "La modification actuelle est vérifiée"), tr('The current code exactly matches the latest change accepted by DiffWitness.', "Le code présent correspond exactement à la dernière modification acceptée par DiffWitness.")
    if tree["dirty"]:
        return tr('A change needs verification', "Une modification doit être vérifiée"), tr(f"{tree['changed_file_count']} relevant file(s) have changed since the last applicable Proof.", f"{tree['changed_file_count']} fichier(s) utile(s) ont changé depuis la dernière Proof couverte.")
    if debt["open_obligations"]:
        return tr('Some known issues still need attention', "Quelques points connus restent à traiter"), tr(f"{debt['open_obligations']} technical obligation(s) remain open.", f"{debt['open_obligations']} obligation(s) technique(s) sont encore ouvertes.")
    return tr('Ready for the next change', "Prêt pour la prochaine modification"), tr('Verification is executable and the project has no uncovered change.', "Les vérifications sont exécutables et le projet n’a pas de modification non couverte.")


def _render_guided(value: dict[str, Any]) -> str:
    protection = value["protection"]
    evidence = value["evidence"]
    tree = value["working_tree"]
    debt = value["debt"]
    envelope = value.get("latest_change_envelope") or {}
    verification = value.get("current_worktree_verification") or {}
    heading, summary = _guided_heading(value)
    lines = [
        tr("DIFFWITNESS · GUIDED", 'DIFFWITNESS · VUE GUIDÉE'),
        "",
        heading,
        summary,
        "",
        tr('Project state', "État du projet"),
    ]
    lines.extend(repository_human_lines(value["readiness"]["repository"], guided=True))
    lines.extend(native_human_lines(value["readiness"]["native"], guided=True))
    if protection.get("mode") == "builtin":
        lines.extend(_provider_lines(protection, guided=True) or [tr('• Live protection is enabled; no agent detected.', "• Protection live activée, aucun agent détecté.")])
    elif protection.get("mode") == "external":
        lines.append(tr('• Live protection is delegated to your existing harness.', "• La protection live est déléguée à ton harness existant."))
    else:
        lines.append(tr('• Live protection is off (optional).', "• La protection live est désactivée (optionnelle)."))
    lines.append(tr('✓ Verification can be started.', "✓ Les vérifications peuvent être lancées.") if evidence["ready"] else tr('⚠ Verification cannot start yet.', "⚠ Les vérifications ne peuvent pas encore démarrer."))
    if tree["dirty"] and verification.get("status") == "accepted":
        lines.append(tr('✓ The currently visible change is covered by the latest accepted Proof.', "✓ La modification actuellement visible est couverte par la dernière Proof acceptée."))
    elif tree["dirty"]:
        lines.append(tr(f"⚠ {tree['changed_file_count']} changed file(s) are not yet covered by a current Proof.", f"⚠ {tree['changed_file_count']} fichier(s) modifié(s) ne sont pas encore couverts par une Proof actuelle."))
    else:
        lines.append(tr('• Working tree is clean; this does not constitute Proof.', "• Arbre de travail propre ; cela ne constitue pas une Proof."))
    lines.append(
        tr(f"⚠ {debt['open_obligations']} known issue(s) still need review.", f"⚠ {debt['open_obligations']} point(s) connu(s) restent à revoir.")
        if debt["open_obligations"]
        else tr('✓ No open technical obligations are recorded in the Debt Ledger.', "✓ Aucun point technique ouvert n’est enregistré dans le Debt Ledger.")
    )
    lines.append(tr('✓ A DiffWitness change history exists.', "✓ Un historique de modification DiffWitness existe.") if envelope.get("present") else tr('• No DiffWitness change history yet.', "• Aucun historique de modification DiffWitness pour l’instant."))
    if tree.get("generated_untracked_ignored"):
        lines.append(tr('• Generated caches are ignored in this summary without hiding Git-tracked files.', "• Les caches générés automatiquement sont ignorés dans ce résumé, sans masquer les fichiers suivis par Git."))
    lines += ["", tr('Next step', "Prochaine étape")]
    for index, action in enumerate(value["next_actions"], start=1):
        title, reason = _action_text(action, value)
        lines.append(f"{index}. {title}")
        lines.append(f"   {reason}")
        lines.append(tr(f"   Command: {action['command']}", f"   Commande: {action['command']}"))
    lines.extend(
        [
            "",
            tr('Live protection blocks/observes some actions during work; only executable verification can establish coverage for an exact code version.', "La protection live empêche/observe certaines actions pendant le travail ; seule la vérification exécutable permet de dire qu’une version précise du code est couverte."),
            tr('Engineering details: `dw view technical`.', "Détails d’ingénierie: `dw view technical`."),
        ]
    )
    return "\n".join(lines)


def render_project_status(value: dict[str, Any], *, view: str) -> str:
    return _render_guided(value) if view == "guided" else _render_technical(value)


def status_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw status",
        description=tr('Show a concise, non-mutating project assurance summary and the next useful actions.', 'Afficher un résumé de l’assurance du projet et les actions utiles sans modifier son état.'),
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--view", choices=VIEW_MODES, help=tr('Temporarily override the saved guided/technical display view', 'Remplacer la vue guided/technical enregistrée pour cette invocation'))
    parser.add_argument("--json", action="store_true", help=tr('Emit the bounded diffwitness.project-status JSON contract', 'Émettre le contrat JSON canonique borné diffwitness.project-status'))
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    value = build_project_status(repo, explicit_config=args.config)
    if args.json:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    else:
        print(render_project_status(value, view=args.view or get_view_mode(repo)))
    return 0


__all__ = ["build_project_status", "render_project_status", "status_cli"]
