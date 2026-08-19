from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .gitops import git, git_version
from .models import AnalysisOutcome


FILESYSTEM_ISOLATION = "reset-before-each-run"


def _certificate_id(report: dict[str, Any]) -> str:
    stable = {k: v for k, v in report.items() if k not in {"generated_at", "certificate_id"}}
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "dw2_" + hashlib.sha256(encoded).hexdigest()[:20]


def _tree_id(repo: Path, commit: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{commit}^{{tree}}").strip()


def build_report(
    *,
    repo: Path,
    base_ref: str,
    base_sha: str,
    candidate_ref: str,
    candidate_sha: str,
    test_command: str,
    outcome: AnalysisOutcome,
    ignored_count: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    results = outcome.mutation_results
    witnessed = sum(r.status == "witnessed" for r in results)
    unwitnessed = sum(r.status == "unwitnessed" for r in results)
    inconclusive = sum(r.status == "inconclusive" for r in results)
    conclusive = witnessed + unwitnessed

    sufficient_sets = [
        r for r in outcome.sufficient_search.results if r.status == "sufficient"
    ]
    sufficient_ids = {mid for result in sufficient_sets for mid in result.mutation_ids}
    mutual_backup = [
        r for r in outcome.interaction_search.results if r.status == "mutual-backup"
    ]

    mutation_roles: dict[str, dict[str, Any]] = {}
    for result in results:
        if result.status == "witnessed":
            role = "essential-under-selected-evidence"
        elif result.status == "unwitnessed":
            role = "individually-removable-under-selected-evidence"
        else:
            role = "inconclusive"
        mutation_roles[result.mutation.id] = {
            "role": role,
            "in_minimal_sufficient_set": result.mutation.id in sufficient_ids,
        }

    surplus_ids: list[str] = []
    if sufficient_sets and outcome.sufficient_search.exhaustive_at_found_order:
        surplus_ids = [
            result.mutation.id
            for result in results
            if result.status == "unwitnessed" and result.mutation.id not in sufficient_ids
        ]

    report: dict[str, Any] = {
        "schema_version": 2,
        "tool": "diffwitness",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "base": {"ref": base_ref, "sha": base_sha, "tree": _tree_id(repo, base_sha)},
        "candidate": {
            "ref": candidate_ref,
            "sha": candidate_sha,
            "tree": _tree_id(repo, candidate_sha),
        },
        "test_command": test_command,
        "config": config,
        "execution": {
            "filesystem_isolation": FILESYSTEM_ISOLATION,
        },
        "contrast": outcome.contrast,
        "candidate_run": outcome.candidate.to_dict(),
        "baseline_with_candidate_tests_run": outcome.baseline.to_dict(),
        "candidate_test_files_overlaid_on_base": sorted(outcome.test_files),
        "summary": {
            "mutations": len(results),
            "witnessed": witnessed,
            "unwitnessed": unwitnessed,
            "inconclusive": inconclusive,
            "ignored": ignored_count,
            "witness_ratio": (witnessed / conclusive) if conclusive else None,
            "minimal_sufficient_order": outcome.sufficient_search.found_order,
            "minimal_sufficient_sets": len(sufficient_sets),
            "mutual_backup_pairs": len(mutual_backup),
            "surplus_candidate_hunks": len(surplus_ids),
        },
        "sufficient_search": outcome.sufficient_search.to_dict(),
        "interaction_search": outcome.interaction_search.to_dict(),
        "surplus_candidate_mutation_ids": surplus_ids,
        "minimization": {
            "removed_mutation_ids": outcome.minimized_removed_ids or [],
            "note": "Greedy/local reduction; a different removal order can produce another passing subset.",
        }
        if outcome.minimized_removed_ids is not None
        else None,
        "mutation_roles": mutation_roles,
        "results": [r.to_dict() for r in results],
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "git": git_version(repo),
        },
        "interpretation": {
            "witnessed": "Removing this exact candidate change made the selected evidence stably fail.",
            "unwitnessed": "The selected evidence stayed stably green without this exact change.",
            "inconclusive": "Patch application, timeout, or unstable execution prevented a causal claim.",
            "sufficient": "Adding this real-hunk subset to base+candidate-tests was enough to make the evidence stably pass.",
            "mutual-backup": "Each hunk was individually removable, but removing both together made the evidence stably fail.",
        },
    }
    report["certificate_id"] = _certificate_id(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# DiffWitness evidence certificate",
        "",
        f"**Certificate:** `{report['certificate_id']}`  ",
        f"**Contrast:** `{report['contrast']}`  ",
        f"**Candidate stability:** `{report['candidate_run']['classification']}`  ",
        f"**Baseline stability:** `{report['baseline_with_candidate_tests_run']['classification']}`  ",
        f"**Filesystem isolation:** `{report.get('execution', {}).get('filesystem_isolation', 'unspecified')}`",
        "",
        "## Evidence summary",
        "",
        f"- Witnessed hunks: **{s['witnessed']}**",
        f"- Unwitnessed hunks: **{s['unwitnessed']}**",
        f"- Inconclusive hunks: **{s['inconclusive']}**",
        f"- Witness ratio: **{(s['witness_ratio'] * 100):.1f}%**" if s["witness_ratio"] is not None else "- Witness ratio: n/a",
        f"- Minimal sufficient order: **{s['minimal_sufficient_order']}**" if s["minimal_sufficient_order"] else "- Minimal sufficient order: not found within budget",
        f"- Mutual-backup pairs: **{s['mutual_backup_pairs']}**",
        f"- Surplus candidate hunks: **{s['surplus_candidate_hunks']}**",
        "",
        "## Hunk witness map",
        "",
        "| Status | Change | Delta | Runtime |",
        "|---|---|---:|---:|",
    ]
    icon = {"witnessed": "✅ witnessed", "unwitnessed": "⚠️ unwitnessed", "inconclusive": "❔ inconclusive"}
    for result in report["results"]:
        m = result["mutation"]
        runs = result.get("runs")
        runtime = f"{runs['total_duration_s']:.2f}s" if runs else "—"
        label = str(m["label"]).replace("|", "\\|")
        lines.append(
            f"| {icon[result['status']]} | `{label}` | +{m['additions']}/-{m['deletions']} | {runtime} |"
        )

    suff = [r for r in report["sufficient_search"]["results"] if r["status"] == "sufficient"]
    if suff:
        lines += ["", "## Minimal sufficient sets", ""]
        for index, subset in enumerate(suff, 1):
            labels = ", ".join(f"`{label}`" for label in subset["mutation_labels"])
            lines.append(f"{index}. {labels}")

    backups = [r for r in report["interaction_search"]["results"] if r["status"] == "mutual-backup"]
    if backups:
        lines += ["", "## Hidden redundancy / mutual backup", ""]
        for pair in backups:
            labels = " + ".join(f"`{label}`" for label in pair["mutation_labels"])
            lines.append(f"- {labels}")

    surplus = set(report.get("surplus_candidate_mutation_ids") or [])
    if surplus:
        by_id = {r["mutation"]["id"]: r["mutation"]["label"] for r in report["results"]}
        lines += ["", "## Strong surplus candidates", ""]
        lines.append(
            "These hunks were individually removable and are absent from every minimal sufficient set found in an exhaustive search at that cardinality:"
        )
        for mid in sorted(surplus):
            lines.append(f"- `{by_id.get(mid, mid)}`")

    lines += [
        "",
        "## What this proves — and what it does not",
        "",
        "DiffWitness establishes causal evidence only with respect to the selected command and execution environment. An unwitnessed hunk may still be desirable for another requirement; it is a review signal, not an automatic deletion order.",
        "",
    ]
    return "\n".join(lines)


def write_json(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report), encoding="utf-8")