"""Local readiness projections; never execute evidence or mutate provider state."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .autodetect import command_available, default_evidence, suggested_available_command
from .config import load_config
from .gitops import git_metadata_path, repository_state
from .native_activation import SUPPORTED_NATIVE_PROVIDERS, native_activation_summary


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def verification_readiness(repo: Path, config: dict | None = None) -> dict[str, Any]:
    try:
        config = load_config(repo, None) if config is None else config
    except Exception as exc:
        return {'configured': False, 'selected': False, 'executableReady': False, 'ready': False,
                'source': 'invalid-config', 'command': None, 'reason': str(exc)[:300], 'checksRun': False}
    command = config.get('test')
    configured = isinstance(command, str) and bool(command.strip())
    plan = None if configured else default_evidence(repo)
    command = command.strip() if configured else plan.command if plan else None
    ready = bool(command and command_available(command, cwd=repo))
    reason = ('configured project evidence' if configured else plan.reason if plan else 'no safe evidence command detected')
    if command and not ready:
        reason = 'selected command executable is unavailable'
    return {
        'configured': configured, 'selected': bool(command), 'executableReady': ready,
        'ready': ready, 'checksRun': False,
        'source': 'configured' if configured else 'detected' if plan else 'missing',
        'command': command, 'reason': reason,
        'problem': None if ready else reason,
        'suggestion': suggested_available_command(command) if command and not ready else None,
        **({'confidence': plan.confidence} if plan else {}),
    }


def native_readiness(repo: Path) -> dict[str, Any]:
    # Inspect the recorded owner, never resolve a replacement through this CLI/PATH.
    from .idleproof_entry import _adapter_installed

    scope = _read_object(git_metadata_path(repo, 'diffwitness/setup-scope.json'))
    installation = _read_object(repo / '.idleproof/integration.json')
    scoped = scope.get('adapters', []) if scope.get('schema') == 'diffwitness.setup-scope.v1' else []
    installed_scope = installation.get('expectedAdapters', [])
    configured = list(dict.fromkeys(
        name for values in (scoped, installed_scope) if isinstance(values, list)
        for name in values if isinstance(name, str) and name in SUPPORTED_NATIVE_PROVIDERS
    ))
    owner = installation.get('diffwitnessCommand')
    owner = owner if isinstance(owner, str) and owner else None
    path = Path(owner) if owner else None
    executable = bool(path and path.is_absolute() and path.is_file() and (os.name == 'nt' or os.access(path, os.X_OK)))
    native = native_activation_summary(repo, configured)
    adapters = {}
    for name, observed in native['adapters'].items():
        installed = bool(owner and _adapter_installed(repo, name, owner))
        usable = installed and executable and observed['observed']
        state = 'missing-hooks' if not installed else 'missing-executable' if not executable else 'awaiting-observation' if not observed['observed'] else 'usable'
        adapters[name] = {**observed, 'installed': installed, 'executableAvailable': executable,
                          'runtimeUsable': usable, 'ready': usable, 'localState': state}
    usable = bool(adapters) and all(item['runtimeUsable'] for item in adapters.values())
    return {
        **native, 'adapters': adapters, 'configuredAdapters': configured,
        'configured': bool(configured), 'installed': bool(adapters) and all(item['installed'] for item in adapters.values()),
        'executableAvailable': executable if configured else False, 'runtimeUsable': usable, 'ready': usable,
        'requiresActionBeforeTask': bool(configured) and not usable,
        'runtimeScope': 'owned-hooks-present, recorded-executable-present, locally-observed; provider-approval-not-asserted',
    }


def build_readiness(repo: Path, *, config: dict | None = None, verification: dict | None = None,
                    protection: dict | None = None, current_verification: dict | None = None) -> dict[str, Any]:
    native = native_readiness(repo)
    verification = verification_readiness(repo, config) if verification is None else verification
    if protection is None:
        from .protect import ProtectError, protect_status
        try:
            protection = protect_status(repo)
        except (ProtectError, ValueError, OSError):
            protection = {'mode': 'invalid', 'adapters': {}, 'receipts': {'integrity': False}}
    mode = protection.get('mode')
    adapters = protection.get('adapters') or {}
    integrity = (protection.get('receipts') or {}).get('integrity')
    protect_ready = (bool(adapters) and all(item.get('ready') for item in adapters.values()) and integrity is True) if mode == 'builtin' else False if mode not in {'off', 'external'} else None
    protect = {'mode': mode, 'selected': mode == 'builtin', 'ready': protect_ready,
               'delegated': mode == 'external', 'receiptIntegrity': integrity}
    if current_verification is None:
        # Reuse the existing exact-tree reader; no independent Proof decision here.
        from .status_cli import _current_verification, _latest_envelope
        current_verification = _current_verification(repo, _latest_envelope(repo))
    status = current_verification.get('status')
    proof = {**current_verification, 'currentTreeVerified': status == 'accepted',
             'freshness': 'stale' if status == 'stale' else 'fresh' if status in {'accepted', 'unaccepted'} else 'unknown'}
    blockers = []
    if not verification.get('executableReady'):
        blockers.append('verification-command-unavailable')
    if native['configured'] and not native['runtimeUsable']:
        blockers.append('native-runtime-not-usable')
    if protect_ready is False:
        blockers.append('protect-not-ready')
    return {
        'schema': 'diffwitness.readiness.v1', 'repository': repository_state(repo),
        'native': native, 'verification': verification,
        'protect': protect, 'currentProof': proof,
        'scopedProduct': {'scope': 'selected-local-hooks-and-verification-launcher',
                          'workflow': 'native' if native['configured'] else 'manual',
                          'ready': not blockers, 'blockedBy': blockers,
                          'excludes': ['provider-approval', 'test-outcome', 'current-tree-proof',
                                       'remote-services', 'engine-capabilities', 'continuity-integrity']},
    }


def native_human_lines(native: dict, *, guided: bool) -> list[str]:
    lines = []
    for name, item in native.get('adapters', {}).items():
        state = item.get('localState')
        if state == 'missing-hooks':
            detail = 'hooks manquants ; répare avec `dw setup`' if guided else 'MISSING HOOKS; repair with `dw setup`'
        elif state == 'missing-executable':
            detail = 'exécutable enregistré indisponible ; répare cette installation' if guided else 'recorded executable unavailable; repair that installation'
        elif state == 'awaiting-observation':
            detail = 'hooks installés ; première invocation à observer' if guided else 'hooks installed; awaiting first observation'
        else:
            detail = 'hooks installés et observés localement' if guided else 'hooks installed and locally observed'
        lines.append(f'{name}: {detail}')
        if item.get('providerTrust') == 'unknown':
            lines.append('  Confiance gérée par Codex, inconnue de DiffWitness. Examine `/hooks` si Codex le demande.' if guided else '  Provider trust is unknown to DiffWitness. Review `/hooks` if Codex requests it.')
    return lines or (['Intégration native non configurée (facultative).'] if guided else ['Native integration not configured (optional).'])


def repository_human_lines(state: dict, *, guided: bool) -> list[str]:
    if state.get("state") != "unborn":
        return []
    return [
        "Ce dépôt n’a pas encore de commit. DiffWitness utilise une base d’analyse vide sans créer de commit dans ta branche. L’identité reste locale jusqu’au premier commit ; aucune Proof n’est supposée."
        if guided else
        "Repository: unborn HEAD; empty analytical base; local provisional identity. No user commit or Proof is implied."
    ]
