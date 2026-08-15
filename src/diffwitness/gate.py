from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .analysis import AnalysisError
from .diffing import make_mutations, parse_file_patches
from .github_actions import emit_annotations, is_github_actions, write_outputs, write_step_summary
from .gitops import diff_text, repo_root, resolve_ref, snapshot_worktree
from .proof_cli import (
    _adaptive_policy,
    _candidate_sha,
    _print_adaptive,
    _resolve_evidence,
    _run_adaptive,
    _run_proof,
)
from .reporting import render_markdown


def _escape_workflow(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _adaptive_markdown(doc: dict[str, Any]) -> str:
    mutations = doc.get("mutations") or {}
    core_ids = doc.get("core_mutation_ids") or []
    removable_ids = doc.get("removable_mutation_ids") or []
    lines = [
        "# DiffWitness Adaptive Core certificate",
        "",
        f"**Certificate:** `{doc['certificate_id']}`  ",
        f"**Contrast:** `{'base-fail_candidate-pass' if doc.get('contrast') else 'inconclusive'}`  ",
        f"**1-minimal:** `{'yes' if doc.get('one_minimal') else 'no'}`  ",
        f"**Experiments:** `{doc.get('attempts')}/{doc.get('budget')}`",
        "",
        "## Adaptive summary",
        "",
        f"- Original production mutations: **{len(doc.get('original_mutation_ids') or [])}**",
        f"- Retained causal core: **{len(core_ids)}**",
        f"- Evidence-removable mutations: **{len(removable_ids)}**",
        f"- Reduction ratio: **{float(doc.get('reduction_ratio') or 0.0) * 100:.1f}%**",
        "",
        "## Retained 1-minimal core" if doc.get("one_minimal") else "## Retained budgeted core",
        "",
    ]
    if core_ids:
        for mutation_id in core_ids:
            meta = mutations.get(mutation_id) or {}
            lines.append(f"- `{meta.get('label') or mutation_id}`")
    else:
        lines.append("- none")
    if removable_ids:
        lines += ["", "## Evidence-removable surface", ""]
        for mutation_id in removable_ids:
            meta = mutations.get(mutation_id) or {}
            lines.append(f"- `{meta.get('label') or mutation_id}`")
    lines += [
        "",
        "## Interpretation boundary",
        "",
        str(doc.get("claim") or ""),
        "",
        str(doc.get("non_claim") or ""),
        "",
    ]
    return "\n".join(lines)


def _emit_adaptive_github(doc: dict[str, Any]) -> None:
    mutations = doc.get("mutations") or {}
    for mutation_id in doc.get("removable_mutation_ids") or []:
        meta = mutations.get(mutation_id) or {}
        path = str(meta.get("path") or "")
        label = str(meta.get("label") or mutation_id)
        if path:
            print(
                f"::warning file={_escape_workflow(path)},title=DiffWitness Adaptive Core::"
                + _escape_workflow(
                    f"Evidence remains stably green without this mutation in a reduced real-patch core: {label}"
                )
            )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(_adaptive_markdown(doc))
            handle.write("\n")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"certificate_id={doc['certificate_id']}\n")
            handle.write("contrast=base-fail_candidate-pass\n")
            handle.write(f"witnessed={len(doc.get('core_mutation_ids') or [])}\n")
            handle.write(f"unwitnessed={len(doc.get('removable_mutation_ids') or [])}\n")
            handle.write(f"inconclusive={0 if doc.get('one_minimal') else 1}\n")
            handle.write("witness_ratio=\n")
            handle.write(f"minimal_sufficient_order={len(doc.get('core_mutation_ids') or [])}\n")
            handle.write(f"surplus_candidate_hunks={len(doc.get('removable_mutation_ids') or [])}\n")
            handle.write("proof_mode=adaptive-core\n")


def gate_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw gate",
        description="Validate an existing Git diff with exhaustive or budgeted adaptive causal evidence.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--candidate", default="HEAD")
    parser.add_argument("--test", help="Evidence command; auto-detected when omitted")
    parser.add_argument("--policy", choices=["observe", "balanced", "strict"], default="balanced")
    parser.add_argument("--strategy", choices=["auto", "exhaustive", "adaptive"], default="auto")
    parser.add_argument("--adaptive-threshold", type=int, default=16)
    parser.add_argument("--adaptive-budget", type=int, default=40)
    parser.add_argument("--stability-runs", type=int, default=2)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--github-actions",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Emit GitHub annotations, outputs and job summary",
    )
    args = parser.parse_args(argv)
    if args.adaptive_threshold < 1:
        raise AnalysisError("--adaptive-threshold must be >= 1")

    repo = repo_root(args.repo)
    test = _resolve_evidence(repo, args.test)
    base_sha = resolve_ref(repo, args.base)
    candidate_sha, candidate_ref = _candidate_sha(repo, args.candidate)
    files = parse_file_patches(diff_text(repo, base_sha, candidate_sha))
    mutations = make_mutations(files)
    if not mutations:
        # The outer `dw` entrypoint normally turns this into a formal no-op certificate.
        print("DiffWitness Gate: no executable causal mutation detected.")
        return 0

    strategy = args.strategy
    if strategy == "auto":
        strategy = "adaptive" if len(mutations) > args.adaptive_threshold else "exhaustive"
    print(
        f"DiffWitness Gate: {strategy} strategy for {len(mutations)} production mutation(s) "
        f"under {args.policy} policy"
    )

    github_mode = is_github_actions() if args.github_actions is None else args.github_actions

    if strategy == "adaptive":
        try:
            result, doc = _run_adaptive(
                repo,
                base_sha=base_sha,
                candidate_sha=candidate_sha,
                files=files,
                mutations=mutations,
                test=test,
                stability_runs=args.stability_runs,
                budget=args.adaptive_budget,
                certificate=args.certificate,
            )
        except AnalysisError as exc:
            message = f"adaptive proof inconclusive: {exc}"
            if github_mode:
                print(f"::error title=DiffWitness Adaptive Core::{_escape_workflow(message)}")
                summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
                if summary_path:
                    with Path(summary_path).open("a", encoding="utf-8") as handle:
                        handle.write(f"## DiffWitness Adaptive Core — inconclusive\n\n{message}\n")
            if args.policy == "observe":
                print(f"DiffWitness Gate: {message}")
                return 0
            print(f"DiffWitness Gate rejected: {message}", file=sys.stderr)
            return 1
        _print_adaptive(result, doc, mutations)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(_adaptive_markdown(doc), encoding="utf-8")
        if github_mode:
            _emit_adaptive_github(doc)
        ok, reason = _adaptive_policy(result, args.policy)
        if ok:
            print(f"DiffWitness Gate accepted ({doc['certificate_id']})")
            return 0
        print(f"DiffWitness Gate rejected: {reason}", file=sys.stderr)
        return 1

    rc, report, reason = _run_proof(
        repo,
        base=base_sha,
        candidate=candidate_sha,
        test=test,
        policy=args.policy,
        stability_runs=args.stability_runs,
        certificate=args.certificate,
    )
    if report is not None:
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render_markdown(report), encoding="utf-8")
        if github_mode:
            emit_annotations(report)
            write_step_summary(report)
            write_outputs(report)
            output = os.environ.get("GITHUB_OUTPUT")
            if output:
                with Path(output).open("a", encoding="utf-8") as handle:
                    handle.write("proof_mode=exhaustive\n")
    if rc == 0:
        cert = report.get("certificate_id") if report else "unknown"
        print(f"DiffWitness Gate accepted ({cert})")
        return 0
    print(f"DiffWitness Gate rejected: {reason}", file=sys.stderr)
    return rc
