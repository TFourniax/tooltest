from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .autodetect import default_evidence
from .change_envelope import _proof_claim
from .config import load_config
from .continuity_bridge import record_change_envelope
from .continuity_state import ensure_state
from .debt_budget import evaluate_and_record, ledger_path, merged_debt_config
from .debt_scan import scan_change
from .diffing import make_mutations, parse_file_patches
from .gitops import diff_text, git_metadata_path, repo_root, snapshot_worktree
from .guard import (
    _persist_guard_envelope,
    _sync_idleproof_assurance,
    _tracked_ledger,
    _validate_generated_certificate,
)
from .ledger import DebtLedger
from .proof_cli import DEFAULT_MAX_TOTAL_SECONDS, _run_proof, _state_path


_MAX_RETRIES = 3


def _success(message: str) -> dict[str, Any]:
    """Complete a provider Stop without inventing an approval decision."""
    return {"systemMessage": message}


def _block(message: str) -> dict[str, Any]:
    """Request one bounded provider continuation for a recoverable proof failure."""
    return {"decision": "block", "reason": message, "systemMessage": message}


def _terminal_failure(message: str) -> dict[str, Any]:
    """End a provider turn once when the current task cannot repair its evidence boundary."""
    return {
        "continue": False,
        "stopReason": message,
        "systemMessage": message,
    }


def _read_session_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_session_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text(json.dumps(state), encoding="utf-8")
    staged.replace(path)


def _retry_or_block(path: Path, state: dict[str, Any], message: str) -> dict[str, Any]:
    retries = int(state.get("retries", 0)) + 1
    state["retries"] = retries
    _write_session_state(path, state)
    if retries > _MAX_RETRIES:
        return _terminal_failure(
            "DiffWitness still cannot establish acceptable evidence after "
            f"{_MAX_RETRIES} continuation attempts. The task requires human intervention or a "
            "stronger evidence command before it can be declared complete. "
            f"Last reason: {message[-2600:]}",
        )
    return _block(
        "DiffWitness rejected the current handoff. Continue working until Proof and Debt gates pass. "
        f"Reason: {message[-3000:]}",
    )


def _evidence_command(repo: Path, config: dict[str, Any]) -> str | None:
    configured = config.get("test")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    plan = default_evidence(repo)
    return plan.command if plan is not None else None


def _continuity_health_path(repo: Path) -> Path:
    return git_metadata_path(repo, "diffwitness/continuity-health.json")


def _set_continuity_health(repo: Path, *, state: str, change_id: str | None = None, error: str | None = None) -> None:
    path = _continuity_health_path(repo)
    if state == "ready":
        try:
            path.unlink()
        except (FileNotFoundError, OSError):
            pass
        return
    payload = {
        "schema": "diffwitness.continuity-health.v1",
        "state": "degraded",
        "change_id": change_id,
        "error": (error or "Continuity projection failed")[:1200],
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "action": "Run `dw state status` and `dw state rebuild` after repairing the underlying continuity error.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".json.tmp")
    try:
        staged.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        staged.replace(path)
    except OSError:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass


def _envelope_change_id(envelope_path: Path) -> str | None:
    try:
        value = json.loads(envelope_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    raw = value.get("change_id") or value.get("changeId")
    return str(raw) if isinstance(raw, str) and raw else None


def _record_continuity(repo: Path, envelope_path: Path) -> tuple[str | None, int, str | None]:
    envelope_change_id = _envelope_change_id(envelope_path)
    try:
        result = record_change_envelope(
            repo=repo,
            path=envelope_path,
            actor="diffwitness-ide-hook",
            trusted_proof=True,
        )
        ensure_state(repo)
        created = result.get("created") or {}
        change_id = str(result.get("change_id") or "") or envelope_change_id
        _set_continuity_health(repo, state="ready", change_id=change_id)
        return change_id, sum(int(value or 0) for value in created.values()), None
    except Exception as exc:
        # Proof/Debt evidence remains valid for the exact candidate and must not be erased or cause
        # an agent recursion loop. But a memory-layer failure is product degradation, not success.
        # Persist it locally and surface it in the Stop message/doctor until a successful projection
        # clears the marker.
        message = f"{type(exc).__name__}: {str(exc)[:1000]}"
        _set_continuity_health(repo, state="degraded", change_id=envelope_change_id, error=message)
        return envelope_change_id, 0, message


def finalize_ide_session(
    payload: dict[str, Any] | None = None,
    *,
    repo: str | Path = ".",
    session_id: str | None = None,
    policy: str = "balanced",
) -> dict[str, Any]:
    """Finalize one native Claude/Codex task through the same Proof/Debt envelope as Guard.

    This is deliberately deterministic and local. It performs no model/API call. Proof remains
    authoritative; Debt Ledger is measured against the exact same candidate; the resulting frozen
    change envelope is then projected into Project Continuity and handed to IdleProof/Portal.
    """

    payload = payload if isinstance(payload, dict) else {}
    root = repo_root(payload.get("cwd") or repo)
    sid = str(payload.get("session_id") or session_id or "default")
    path = _state_path(root, sid)
    if not path.exists():
        return _terminal_failure(
            "DiffWitness was not armed at SessionStart, so this task cannot be declared verified. "
            "Repair `dw setup` and start a newly captured task, or use `dw guard` as an explicit "
            "boundary for a new task. Do not launch a nested agent from this session.",
        )

    state = _read_session_state(path)
    base = state.get("base")
    if not isinstance(base, str) or not base:
        return _terminal_failure(
            "DiffWitness SessionStart state is invalid, so this task cannot be declared verified. "
            "Repair `dw setup` and start a newly captured task, or use `dw guard` as an explicit "
            "boundary for a new task. Do not launch a nested agent from this session.",
        )

    candidate = snapshot_worktree(root)
    if candidate == base:
        return _success("DiffWitness: no repository change to prove.")

    files = parse_file_patches(diff_text(root, base, candidate))
    mutations = make_mutations(files)
    if not mutations:
        return _success("DiffWitness: no production-code mutation to prove.")

    config = load_config(root, None)
    test = _evidence_command(root, config)
    if not test:
        return _block(
            "DiffWitness cannot find an evidence command. Add tests or configure [diffwitness].test before declaring the task complete.",
        )

    max_total_seconds = float(config.get("max_total_seconds", DEFAULT_MAX_TOTAL_SECONDS))
    stability_runs = int(config.get("stability_runs", 2))

    with tempfile.TemporaryDirectory(prefix="diffwitness-ide-handoff-") as td:
        temp_dir = Path(td)
        proof_path = temp_dir / "ide-proof.json"
        rc, report, reason = _run_proof(
            root,
            base=base,
            candidate=candidate,
            test=str(test),
            policy=policy,
            stability_runs=stability_runs,
            max_total_seconds=max_total_seconds,
            certificate=proof_path,
            quiet=True,
        )
        if rc != 0:
            return _retry_or_block(path, state, reason or "Proof did not pass")

        try:
            _validate_generated_certificate(proof_path, repo=root, candidate_sha=candidate)
        except Exception as exc:
            return _retry_or_block(path, state, f"generated Proof certificate failed validation: {exc}")

        if not isinstance(report, dict):
            return _retry_or_block(path, state, "Proof certificate was not available for canonical acceptance evaluation")
        proof_claim, proof_accepted = _proof_claim(report)
        if not proof_accepted:
            return _retry_or_block(
                path,
                state,
                f"canonical Proof claim is {proof_claim!r} and is not accepted by the change-envelope contract",
            )

        debt_config = merged_debt_config(config.get("debt") or {})
        ledger = DebtLedger.load(ledger_path(root, debt_config))
        debt_report = scan_change(
            repo=root,
            base_sha=base,
            candidate_sha=candidate,
            certificate_path=proof_path,
            test_globs=list(config.get("test_glob") or []),
            ignore_globs=list(config.get("ignore") or []),
        )
        provenance = {
            "source": "ide-hook",
            "agent": str(payload.get("agent") or payload.get("provider") or payload.get("source") or "coding-agent")[:128],
            "executable": "native-hook",
        }
        for signal in debt_report.signals:
            signal.introduced_by.update(provenance)
        debt_report.metadata["agent_provenance"] = provenance

        auto_record = bool(debt_config.get("auto_record", True))
        tracked_ledger = _tracked_ledger(root, ledger.path)
        should_record = auto_record and not tracked_ledger
        budget, stats = evaluate_and_record(
            ledger=ledger,
            change=debt_report,
            debt_config=debt_config,
            actor="diffwitness-ide-hook",
            record=should_record,
            record_if_budget_fails=False,
        )

        envelope_path = _persist_guard_envelope(
            repo=root,
            base_sha=base,
            candidate_sha=candidate,
            proof_path=proof_path,
            temp_dir=temp_dir,
            report=debt_report,
            budget=budget,
            # Native providers parse stdout as one hook-protocol JSON document. Guard's
            # human-facing artifact paths must not leak into that protocol stream.
            quiet=True,
        )
        change_id, continuity_events, continuity_error = _record_continuity(root, envelope_path)
        _sync_idleproof_assurance(root, envelope_path)

        if not budget.passed:
            violations = "; ".join(str(value) for value in budget.violations[:6]) or "configured debt budget exceeded"
            return _retry_or_block(path, state, f"Debt Ledger budget rejected the change: {violations}")

        try:
            path.unlink()
        except OSError:
            pass

        cert_id = str((report or {}).get("certificate_id") or "unknown")
        debt_suffix = f" · Debt +{debt_report.total_points}/{len(debt_report.signals)} obligation(s)"
        ledger_suffix = ""
        if should_record:
            ledger_suffix = f" · ledger +{stats['introduced']} introduced/{stats['reopened']} reopened"
        if continuity_error:
            continuity_suffix = " · Continuity DEGRADED (Proof remains exact-tree valid; run `dw doctor`)"
        else:
            continuity_suffix = f" · Continuity {continuity_events} event(s)"
            if change_id:
                continuity_suffix += f" · {change_id}"
        return _success(
            f"DiffWitness Proof accepted: {cert_id}{debt_suffix}{ledger_suffix}{continuity_suffix}",
        )
