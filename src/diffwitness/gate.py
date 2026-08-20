from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .adaptive import find_adaptive_core
from .analysis import AnalysisError
from .assurance import assurance_policy, build_assurance, render_assurance_markdown
from .cli import main as core_main
from .config import load_config
from .diffing import make_mutations, parse_file_patches
from .engine_protocol import EngineProtocolError, build_engine_request, run_advisory_engine
from .github_actions import emit_annotations, is_github_actions, write_outputs, write_step_summary
from .gitops import diff_text, repo_root, resolve_ref
from .proof_cli import (
    _adaptive_document,
    _adaptive_policy,
    _candidate_sha,
    _policy_passes,
    _print_adaptive,
    _resolve_evidence,
)
from .reporting import render_markdown


DEFAULT_MAX_TOTAL_SECONDS = 900.0
DEFAULT_ENGINE_TIMEOUT_SECONDS = 2.0


def _escape_workflow(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _list_setting(cli: list[str] | None, config: dict[str, Any], key: str) -> list[str]:
    if cli is not None:
        return list(cli)
    value = config.get(key, [])
    return list(value) if isinstance(value, list) else []


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
    planning = doc.get("planning") or {}
    engine = planning.get("engine") or {}
    if engine:
        lines += [
            "## Advisory planning",
            "",
            f"- Engine: **{engine.get('name', 'unknown')} {engine.get('version', '')}**",
            f"- Request: `{planning.get('request_id', 'unknown')}`",
            "- Authority: **advisory only** — every removal below was independently executed by the public proof runner.",
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


def _emit_assurance_github(report: dict[str, Any], *, accepted: bool) -> None:
    markdown = render_assurance_markdown(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(markdown)
            handle.write("\n")
    classification = str(report.get("classification"))
    if classification == "non-discriminating-change":
        level = "warning" if accepted else "error"
        print(
            f"::{level} title=DiffWitness non-discriminating evidence::"
            "Candidate tests pass on the base as well as the candidate; they do not discriminate the production change."
        )
    elif classification in {"candidate-not-stable-green", "assurance-inconclusive"}:
        level = "warning" if accepted else "error"
        print(
            f"::{level} title=DiffWitness assurance::{_escape_workflow(str(report.get('claim') or classification))}"
        )
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"certificate_id={report['certificate_id']}\n")
            handle.write("contrast=not-applicable\n")
            handle.write("witnessed=0\n")
            handle.write("unwitnessed=0\n")
            handle.write(f"inconclusive={report['summary'].get('inconclusive', 0)}\n")
            handle.write("witness_ratio=\n")
            handle.write("minimal_sufficient_order=\n")
            handle.write("surplus_candidate_hunks=0\n")
            handle.write(f"proof_mode={classification}\n")


def _write_assurance_artifacts(
    report: dict[str, Any], *, certificate: Path | None, markdown_path: Path | None
) -> None:
    if certificate:
        certificate.parent.mkdir(parents=True, exist_ok=True)
        certificate.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_assurance_markdown(report), encoding="utf-8")


def _run_exhaustive_gate(
    *,
    repo: Path,
    base_sha: str,
    candidate_sha: str,
    test: str,
    policy: str,
    stability_runs: int,
    prepare: str | None,
    timeout: float,
    max_total_seconds: float,
    shared: list[str],
    test_globs: list[str],
    ignore: list[str],
    overlay_tests: bool,
    certificate: Path | None,
) -> tuple[int, dict[str, Any] | None, str]:
    temporary: Path | None = None
    cert = certificate
    if cert is None:
        fd, raw = tempfile.mkstemp(prefix="diffwitness-gate-", suffix=".json")
        os.close(fd)
        temporary = Path(raw)
        cert = temporary
    argv = [
        "prove",
        "--repo",
        str(repo),
        "--base",
        base_sha,
        "--candidate",
        candidate_sha,
        "--test",
        test,
        "--stability-runs",
        str(stability_runs),
        "--timeout",
        str(timeout),
        "--max-total-seconds",
        str(max_total_seconds),
        "--certificate",
        str(cert),
        "--no-github-actions",
    ]
    if prepare:
        argv += ["--prepare", prepare]
    for path in shared:
        argv += ["--share", path]
    for pattern in test_globs:
        argv += ["--test-glob", pattern]
    for pattern in ignore:
        argv += ["--ignore", pattern]
    if not overlay_tests:
        argv.append("--no-test-overlay")
    rc = core_main(argv)
    report: dict[str, Any] | None = None
    if cert.exists():
        try:
            loaded = json.loads(cert.read_text(encoding="utf-8"))
            report = loaded if isinstance(loaded, dict) else None
        except (OSError, json.JSONDecodeError):
            report = None
    if temporary is not None:
        try:
            temporary.unlink()
        except OSError:
            pass
    if rc != 0:
        return rc, report, "exhaustive evidence engine failed"
    if report is None:
        return 2, None, "exhaustive engine produced no readable certificate"
    ok, reason = _policy_passes(report, policy)
    return (0 if ok else 1), report, reason


def gate_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw gate",
        description="Validate an existing Git diff with semantic evidence routing and causal proof when applicable.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--base", required=True)
    parser.add_argument("--candidate", default="HEAD")
    parser.add_argument("--test", help="Evidence command; auto-detected when omitted")
    parser.add_argument("--prepare")
    parser.add_argument("--timeout", type=float)
    parser.add_argument(
        "--max-total-seconds",
        type=float,
        default=None,
        help="Maximum wall-clock seconds for assurance + planning + proof combined (default/config: 900)",
    )
    parser.add_argument("--share", action="append", default=None)
    parser.add_argument("--test-glob", action="append", default=None)
    parser.add_argument("--ignore", action="append", default=None)
    parser.add_argument("--policy", choices=["observe", "balanced", "strict"], default=None)
    parser.add_argument("--strategy", choices=["auto", "exhaustive", "adaptive"], default=None)
    parser.add_argument("--adaptive-threshold", type=int, default=None)
    parser.add_argument("--adaptive-budget", type=int, default=None)
    parser.add_argument("--stability-runs", type=int, default=None)
    parser.add_argument("--engine", help="Optional advisory engine executable; overrides configured engine.command")
    parser.add_argument("--engine-timeout", type=float, default=None)
    parser.add_argument(
        "--engine-required",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Fail instead of using the Community planner if an adaptive advisory engine is unavailable or invalid",
    )
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--github-actions",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Emit GitHub annotations, outputs and job summary",
    )
    args = parser.parse_args(argv)

    repo = repo_root(args.repo)
    config = load_config(repo, args.config)
    test = _resolve_evidence(repo, args.test)
    prepare = args.prepare if args.prepare is not None else config.get("prepare")
    timeout = float(args.timeout if args.timeout is not None else config.get("timeout", 300.0))
    max_total_seconds = float(
        args.max_total_seconds
        if args.max_total_seconds is not None
        else config.get("max_total_seconds", DEFAULT_MAX_TOTAL_SECONDS)
    )
    shared = _list_setting(args.share, config, "share")
    test_globs = _list_setting(args.test_glob, config, "test_glob")
    ignore = _list_setting(args.ignore, config, "ignore")
    policy = str(args.policy or config.get("policy", "balanced"))
    strategy = str(args.strategy or config.get("strategy", "auto"))
    adaptive_threshold = int(
        args.adaptive_threshold
        if args.adaptive_threshold is not None
        else config.get("adaptive_threshold", 16)
    )
    adaptive_budget = int(
        args.adaptive_budget
        if args.adaptive_budget is not None
        else config.get("adaptive_budget", 40)
    )
    stability_runs = int(
        args.stability_runs
        if args.stability_runs is not None
        else config.get("stability_runs", 2)
    )
    overlay_tests = bool(config.get("test_overlay", True))
    engine_config = config.get("engine") or {}
    engine_command = [args.engine] if args.engine else list(engine_config.get("command") or [])
    engine_timeout = float(
        args.engine_timeout
        if args.engine_timeout is not None
        else engine_config.get("timeout", DEFAULT_ENGINE_TIMEOUT_SECONDS)
    )
    engine_required = bool(
        args.engine_required
        if args.engine_required is not None
        else engine_config.get("required", False)
    )
    if timeout <= 0:
        raise AnalysisError("timeout must be > 0")
    if max_total_seconds <= 0:
        raise AnalysisError("max total seconds must be > 0")
    if engine_timeout <= 0:
        raise AnalysisError("engine timeout must be > 0")
    if adaptive_threshold < 1:
        raise AnalysisError("adaptive threshold must be >= 1")
    if adaptive_budget < 1:
        raise AnalysisError("adaptive budget must be >= 1")
    if stability_runs < 1:
        raise AnalysisError("stability runs must be >= 1")

    base_sha = resolve_ref(repo, args.base)
    candidate_sha, candidate_ref = _candidate_sha(repo, args.candidate)
    files = parse_file_patches(
        diff_text(repo, base_sha, candidate_sha), test_globs=test_globs
    )
    mutations = make_mutations(files, ignore_globs=ignore)
    if not mutations:
        print("DiffWitness Gate: no executable causal mutation detected.")
        return 0

    github_mode = is_github_actions() if args.github_actions is None else args.github_actions
    proof_started = time.monotonic()

    # Semantic probe first. This prevents forcing repair-style hunk necessity onto preservation
    # tasks and prevents large non-contrast patches from falling into Adaptive Core by accident.
    assurance = build_assurance(
        source_repo=repo,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        candidate_ref=candidate_ref,
        files=files,
        test_command=test,
        stability_runs=stability_runs,
        timeout=timeout,
        prepare_command=str(prepare) if prepare else None,
        shared_paths=shared,
        overlay_candidate_tests=overlay_tests,
        max_total_seconds=max_total_seconds,
    )
    classification = str(assurance["classification"])
    if classification != "causal-contrast":
        ok, reason = assurance_policy(assurance, policy)
        _write_assurance_artifacts(
            assurance, certificate=args.certificate, markdown_path=args.report
        )
        if github_mode:
            _emit_assurance_github(assurance, accepted=ok)
        print(
            f"DiffWitness Gate: {classification} under {policy} policy "
            f"({assurance['certificate_id']})"
        )
        if ok:
            print(f"DiffWitness Gate accepted: {reason}")
            return 0
        print(f"DiffWitness Gate rejected: {reason}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - proof_started
    remaining_seconds = max_total_seconds - elapsed
    if remaining_seconds <= 0:
        raise AnalysisError(
            f"wall-clock proof budget exhausted during assurance ({max_total_seconds:g}s total)"
        )

    selected = strategy
    if selected == "auto":
        selected = "adaptive" if len(mutations) > adaptive_threshold else "exhaustive"
    print(
        f"DiffWitness Gate: causal contrast proven; {selected} strategy for "
        f"{len(mutations)} production mutation(s) under {policy} policy "
        f"({remaining_seconds:.1f}s proof budget remaining)"
    )

    engine_plan: dict[str, Any] | None = None
    if selected == "adaptive":
        test_files = {file.path for file in files if file.is_test}
        production_mutations = [mutation for mutation in mutations if mutation.path not in test_files]
        if engine_required and not engine_command:
            raise AnalysisError("adaptive advisory engine is required but no engine command is configured")
        if engine_command and production_mutations:
            request = build_engine_request(
                repo=repo,
                base_sha=base_sha,
                base_tree=str(assurance["base"]["tree"]),
                candidate_sha=candidate_sha,
                candidate_tree=str(assurance["candidate"]["tree"]),
                mutations=production_mutations,
                max_experiments=adaptive_budget,
                max_total_seconds=remaining_seconds,
                stability_runs=stability_runs,
                policy=policy,
                strategy=selected,
                test_command=test,
                changed_test_files=sorted(test_files),
            )
            try:
                engine_plan, diagnostic = run_advisory_engine(
                    repo=repo,
                    command=engine_command,
                    request=request,
                    timeout=min(engine_timeout, remaining_seconds),
                    required=engine_required,
                )
            except EngineProtocolError as exc:
                raise AnalysisError(f"required advisory engine failed: {exc}") from exc
            if engine_plan is not None:
                engine = engine_plan["engine"]
                print(
                    f"DiffWitness advisory planner: {engine['name']} {engine['version']} "
                    f"({len(engine_plan['partitions'])} partition(s), "
                    f"{len(engine_plan['interaction_pairs'])} interaction hint(s))"
                )
            elif diagnostic:
                print(f"DiffWitness advisory planner skipped: {diagnostic}", file=sys.stderr)

            remaining_seconds = max_total_seconds - (time.monotonic() - proof_started)
            if remaining_seconds <= 0:
                raise AnalysisError(
                    f"wall-clock proof budget exhausted during assurance/planning ({max_total_seconds:g}s total)"
                )

    if selected == "adaptive":
        try:
            result = find_adaptive_core(
                source_repo=repo,
                base_sha=base_sha,
                candidate_sha=candidate_sha,
                files=files,
                mutations=mutations,
                test_command=test,
                timeout=timeout,
                prepare_command=str(prepare) if prepare else None,
                shared_paths=shared,
                overlay_candidate_tests=overlay_tests,
                stability_runs=stability_runs,
                budget=adaptive_budget,
                max_total_seconds=remaining_seconds,
                ordered_mutation_ids=(engine_plan or {}).get("ordered_mutation_ids"),
                preferred_partitions=(engine_plan or {}).get("partitions"),
            )
            doc = _adaptive_document(
                result,
                repo=repo,
                base_sha=base_sha,
                candidate_sha=candidate_sha,
                test=test,
                mutations=mutations,
            )
            if engine_plan is not None:
                doc["planning"] = {
                    "mode": "advisory",
                    "engine": engine_plan["engine"],
                    "request_id": engine_plan["request_id"],
                    "request_digest": engine_plan["request_digest"],
                    "partitions": len(engine_plan["partitions"]),
                    "interaction_pairs": len(engine_plan["interaction_pairs"]),
                    "authority": "advisory-only",
                }
            doc["execution"] = {
                "prepare": prepare,
                "timeout": timeout,
                "max_total_seconds": max_total_seconds,
                "proof_seconds_after_assurance_and_planning": remaining_seconds,
                "share": shared,
                "test_glob": test_globs,
                "ignore": ignore,
                "test_overlay": overlay_tests,
                "stability_runs": stability_runs,
            }
            stable = {key: value for key, value in doc.items() if key != "certificate_id"}
            encoded = json.dumps(
                stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            doc["certificate_id"] = "dwac1_" + hashlib.sha256(encoded).hexdigest()[:20]
            if args.certificate:
                args.certificate.parent.mkdir(parents=True, exist_ok=True)
                args.certificate.write_text(
                    json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
        except (AnalysisError, TimeoutError) as exc:
            message = f"adaptive proof inconclusive: {exc}"
            if github_mode:
                print(f"::error title=DiffWitness Adaptive Core::{_escape_workflow(message)}")
                summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
                if summary_path:
                    with Path(summary_path).open("a", encoding="utf-8") as handle:
                        handle.write(f"## DiffWitness Adaptive Core — inconclusive\n\n{message}\n")
            if policy == "observe":
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
        ok, reason = _adaptive_policy(result, policy)
        if ok:
            print(f"DiffWitness Gate accepted ({doc['certificate_id']})")
            return 0
        print(f"DiffWitness Gate rejected: {reason}", file=sys.stderr)
        return 1

    rc, report, reason = _run_exhaustive_gate(
        repo=repo,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        test=test,
        policy=policy,
        stability_runs=stability_runs,
        prepare=str(prepare) if prepare else None,
        timeout=timeout,
        max_total_seconds=remaining_seconds,
        shared=shared,
        test_globs=test_globs,
        ignore=ignore,
        overlay_tests=overlay_tests,
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
