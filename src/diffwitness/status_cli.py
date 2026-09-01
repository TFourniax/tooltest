from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .autodetect import default_evidence
from .config import load_config
from .debt_budget import ledger_path, merged_debt_config
from .gitops import git, repo_root
from .ledger import DebtLedger
from .protect import ProtectError, protect_status
from .view_mode import VIEW_MODES, get_view_mode


def _evidence_command(repo: Path, config: dict[str, Any]) -> tuple[str | None, str]:
    configured = config.get("test")
    if isinstance(configured, str) and configured.strip():
        return configured.strip(), "configured"
    detected = default_evidence(repo)
    if detected is None:
        return None, "missing"
    return detected.command, "detected"


def _working_tree(repo: Path) -> tuple[list[str], bool]:
    raw = git(repo, "status", "--porcelain=v1", "--untracked-files=normal")
    files: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        value = line[3:] if len(line) >= 4 else line.strip()
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        files.append(value.strip())
    return sorted(set(files)), bool(files)


def _branch(repo: Path) -> str | None:
    value = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    return None if value == "HEAD" else value


def _latest_envelope(repo: Path) -> dict[str, Any] | None:
    path = repo / ".git" / "diffwitness" / "change-envelope.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"present": True, "readable": False}
    if not isinstance(value, dict):
        return {"present": True, "readable": False}
    return {
        "present": True,
        "readable": True,
        "change_id": value.get("change_id") or value.get("changeId"),
        "schema": value.get("schema") or value.get("schema_version"),
    }


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
    return value


def build_project_status(repo: Path, *, explicit_config: str | None = None) -> dict[str, Any]:
    config = load_config(repo, explicit_config)
    debt_config = merged_debt_config(config.get("debt") or {})
    ledger = DebtLedger.load(ledger_path(repo, debt_config))
    evidence_command, evidence_source = _evidence_command(repo, config)
    changed_files, dirty = _working_tree(repo)
    active = ledger.active_items()
    categories = ledger.active_by_category()
    envelope = _latest_envelope(repo)
    protection = _protection_status(repo)

    actions: list[dict[str, str]] = []
    if evidence_command is None:
        actions.append(
            {
                "priority": "high",
                "kind": "configure-evidence",
                "title": "Tell DiffWitness how to verify this project",
                "command": "dw doctor",
                "reason": "No executable evidence command is configured or safely auto-detected.",
            }
        )
    if protection.get("health") in {"degraded", "invalid"}:
        actions.append(
            {
                "priority": "high",
                "kind": "repair-protection",
                "title": "Repair the optional runtime protection layer",
                "command": "dw protect status",
                "reason": "Protect is configured but its local state or installed hooks are not healthy. Proof remains independent.",
            }
        )
    if dirty:
        actions.append(
            {
                "priority": "high" if evidence_command else "medium",
                "kind": "verify-change",
                "title": "Verify the current change",
                "command": "dw gate --candidate WORKTREE",
                "reason": f"{len(changed_files)} changed file(s) are present in the working tree.",
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
    if not actions:
        actions.append(
            {
                "priority": "normal",
                "kind": "guard-next-change",
                "title": "Put the next agent change behind the proof boundary",
                "command": "dw guard -- <agent>",
                "reason": "Evidence is ready, the working tree is clean, and no open debt is recorded.",
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
        "protection": protection,
        "evidence": {
            "ready": evidence_command is not None,
            "source": evidence_source,
            "command": evidence_command,
        },
        "working_tree": {
            "dirty": dirty,
            "changed_file_count": len(changed_files),
            "files": changed_files[:25],
            "truncated": len(changed_files) > 25,
        },
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
        "non_claim": "Project status is navigation over runtime protection metadata, configured evidence, Git metadata and the Debt Ledger. Protection observations are not a proof that the application is correct.",
    }


def _protect_line(protection: dict[str, Any]) -> str:
    mode = protection.get("mode")
    health = protection.get("health")
    policy = protection.get("policy")
    if mode == "builtin":
        return f"Protect       builtin · {health} · policy {policy}"
    if mode == "external":
        return "Protect       external · delegated"
    if mode == "off":
        return "Protect       off · optional"
    return f"Protect       {mode or 'unknown'} · {health or 'unknown'}"


def _render_technical(value: dict[str, Any]) -> str:
    protection = value["protection"]
    evidence = value["evidence"]
    tree = value["working_tree"]
    debt = value["debt"]
    envelope = value.get("latest_change_envelope") or {}
    lines = [
        "DIFFWITNESS STATUS · TECHNICAL VIEW",
        "",
        _protect_line(protection),
        f"Evidence      {'ready' if evidence['ready'] else 'NOT READY'}" + (
            f" ({evidence['source']}: {evidence['command']})" if evidence['ready'] else ""
        ),
        f"Working tree  {tree['changed_file_count']} changed file(s)" if tree["dirty"] else "Working tree  clean",
        f"Debt          {debt['points']} point(s) · {debt['open_obligations']} open obligation(s)",
        f"Last change   {envelope.get('change_id') or ('recorded' if envelope.get('present') else 'none')}",
        "",
        "Next actions",
    ]
    for index, action in enumerate(value["next_actions"], start=1):
        lines.append(f"{index}. {action['title']}")
        lines.append(f"   {action['command']}")
        lines.append(f"   {action['reason']}")
    lines.extend(
        [
            "",
            "Protect observations are runtime guard metadata, not executable proof. Use Gate / Proof for change claims.",
            "Prefer less detail? `dw view guided` (or one-off: `dw status --view guided`).",
        ]
    )
    return "\n".join(lines)


def _guided_heading(value: dict[str, Any]) -> tuple[str, str]:
    evidence = value["evidence"]
    tree = value["working_tree"]
    debt = value["debt"]
    protection = value["protection"]
    if not evidence["ready"]:
        return "Setup needs attention", "DiffWitness does not yet know how to run executable checks for this project."
    if protection.get("health") in {"degraded", "invalid"}:
        return "Runtime protection needs attention", "The optional live guard layer is configured but is not healthy. Verification after the change remains independent."
    if tree["dirty"]:
        return "A change is waiting to be verified", f"{tree['changed_file_count']} changed file(s) are currently present."
    if debt["open_obligations"]:
        return "Some known items need attention", f"{debt['open_obligations']} technical obligation(s) are still open."
    return "Ready for the next change", "Verification setup is available, the working tree is clean, and no open obligation is recorded."


def _guided_protect_line(protection: dict[str, Any]) -> str:
    mode = protection.get("mode")
    health = protection.get("health")
    if mode == "builtin" and health == "ready":
        return "✓ Runtime protection is active while supported agents work."
    if mode == "external":
        return "• Runtime protection is delegated to your external harness; DiffWitness still verifies the resulting change."
    if mode == "off":
        return "• Runtime protection is off; DiffWitness can still verify the resulting change and track debt."
    return "⚠ Runtime protection is configured but needs attention."


def _render_guided(value: dict[str, Any]) -> str:
    protection = value["protection"]
    evidence = value["evidence"]
    tree = value["working_tree"]
    debt = value["debt"]
    envelope = value.get("latest_change_envelope") or {}
    heading, summary = _guided_heading(value)
    lines = [
        "DIFFWITNESS · GUIDED VIEW",
        "",
        heading,
        summary,
        "",
        "What we know",
        _guided_protect_line(protection),
        "✓ Verification setup is ready." if evidence["ready"] else "⚠ Verification setup is not ready yet.",
        f"⚠ {tree['changed_file_count']} changed file(s) are waiting for verification." if tree["dirty"] else "✓ No uncommitted software change is currently visible.",
        f"⚠ {debt['open_obligations']} technical obligation(s) remain to review." if debt["open_obligations"] else "✓ No open technical obligation is recorded in the Debt Ledger.",
        "✓ A previous verified change record is available." if envelope.get("present") else "• No previous change envelope is recorded yet.",
        "",
        "What to do next",
    ]
    for index, action in enumerate(value["next_actions"], start=1):
        lines.append(f"{index}. {action['title']}")
        lines.append(f"   Why: {action['reason']}")
        lines.append(f"   Run: {action['command']}")
    lines.extend(
        [
            "",
            "Runtime protection tells you what was blocked or observed; it does not prove the software works.",
            "Want the engineering details? `dw view technical` (or one-off: `dw status --view technical`).",
        ]
    )
    return "\n".join(lines)


def render_project_status(value: dict[str, Any], *, view: str) -> str:
    if view == "guided":
        return _render_guided(value)
    return _render_technical(value)


def status_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw status",
        description="Show a concise, non-mutating project assurance summary and the next useful actions.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--view", choices=VIEW_MODES, help="Temporarily override the saved guided/technical display view")
    parser.add_argument("--json", action="store_true", help="Emit the bounded diffwitness.project-status.v1 JSON contract")
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    value = build_project_status(repo, explicit_config=args.config)
    if args.json:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    else:
        print(render_project_status(value, view=args.view or get_view_mode(repo)))
    return 0


__all__ = ["build_project_status", "render_project_status", "status_cli"]
