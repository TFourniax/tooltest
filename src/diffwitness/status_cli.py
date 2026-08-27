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


def build_project_status(repo: Path, *, explicit_config: str | None = None) -> dict[str, Any]:
    config = load_config(repo, explicit_config)
    debt_config = merged_debt_config(config.get("debt") or {})
    ledger = DebtLedger.load(ledger_path(repo, debt_config))
    evidence_command, evidence_source = _evidence_command(repo, config)
    changed_files, dirty = _working_tree(repo)
    active = ledger.active_items()
    categories = ledger.active_by_category()
    envelope = _latest_envelope(repo)

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

    return {
        "schema": "diffwitness.project-status.v1",
        "project": {"name": repo.name, "branch": _branch(repo)},
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
        },
        "non_claim": "Project status is navigation over configured evidence, Git metadata and the Debt Ledger. It is not a proof that the application is correct.",
    }


def _render(value: dict[str, Any]) -> str:
    evidence = value["evidence"]
    tree = value["working_tree"]
    debt = value["debt"]
    envelope = value.get("latest_change_envelope") or {}
    lines = [
        "DIFFWITNESS STATUS",
        "",
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
            "Status is a navigation summary, not a correctness verdict. Use Gate / Proof for executable claims.",
        ]
    )
    return "\n".join(lines)


def status_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw status",
        description="Show a concise, non-mutating project assurance summary and the next useful actions.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--json", action="store_true", help="Emit the bounded diffwitness.project-status.v1 JSON contract")
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    value = build_project_status(repo, explicit_config=args.config)
    if args.json:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    else:
        print(_render(value))
    return 0


__all__ = ["build_project_status", "status_cli"]
