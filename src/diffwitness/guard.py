from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .change_envelope import ChangeEnvelopeError, build_change_envelope
from .config import load_config
from .debt_budget import evaluate_and_record, ledger_path, merged_debt_config
from .debt_certificate import validate_debt_certificate
from .debt_scan import scan_change
from .gitops import diff_text, git, repo_root, snapshot_worktree
from .ledger import DebtLedger


DEFAULT_MAX_TOTAL_SECONDS = 900.0


def _tracked_ledger(repo: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return False
    if rel == ".git" or rel.startswith(".git/"):
        return False
    return bool(git(repo, "ls-files", "--", rel).strip())


def _print_change_debt(report, budget) -> None:
    print("\nCHANGE DEBT")
    print(f"+{report.total_points} point(s) / {len(report.signals)} obligation(s)")
    for category, points in sorted(report.by_category.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {category:18} +{points}")
    for signal in report.signals[:8]:
        location = f" {signal.path}" if signal.path else ""
        if signal.line:
            location += f":{signal.line}"
        print(f"  {signal.debt_id} +{int(signal.points or 0)} {signal.category}/{signal.measurement}{location} — {signal.title}")
    if len(report.signals) > 8:
        print(f"  … {len(report.signals) - 8} additional obligation(s)")
    print(f"Debt budget: {'PASS' if budget.passed else 'EXCEEDED'} — projected total {budget.projected_total}; new {budget.change_points}")
    for violation in budget.violations:
        print(f"  ! {violation}")


def _validate_generated_certificate(path: Path, *, repo: Path, candidate_sha: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Guard proof certificate cannot be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Guard proof certificate is not a JSON object")
    validate_debt_certificate(payload, repo=repo, candidate_sha=candidate_sha)


def _agent_provenance(command: list[str]) -> dict[str, str]:
    """Persist only low-risk provenance by default: executable name, never prompts or secret-bearing args."""
    executable = Path(command[0]).name if command else "unknown"
    lowered = executable.lower()
    if "claude" in lowered:
        agent = "claude-code"
    elif "codex" in lowered:
        agent = "codex"
    else:
        agent = executable
    return {"source": "guard", "agent": agent, "executable": executable}


def _persist_guard_envelope(
    *,
    repo: Path,
    base_sha: str,
    candidate_sha: str,
    proof_path: Path,
    temp_dir: Path,
    report=None,
    budget=None,
) -> Path:
    debt_path: Path | None = None
    if report is not None and budget is not None:
        debt_path = temp_dir / "guard-debt.json"
        debt_path.write_text(
            json.dumps(
                {"report": report.to_dict(), "budget": budget.to_dict(), "ledger": {}},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    understanding_path = repo / ".idleproof" / "receipt.json"
    include_understanding = understanding_path.is_file()
    try:
        envelope = build_change_envelope(
            repo=repo,
            base_ref=base_sha,
            candidate_ref=candidate_sha,
            proof_path=proof_path,
            debt_path=debt_path,
            understanding_path=understanding_path if include_understanding else None,
        )
    except ChangeEnvelopeError as exc:
        if not include_understanding:
            raise
        # IdleProof is optional. A stale/mismatched receipt must never be correlated to this
        # change, but it also must not erase otherwise valid DiffWitness Proof/Debt evidence.
        print(f"IdleProof correlation skipped: {exc}", file=sys.stderr)
        envelope = build_change_envelope(
            repo=repo,
            base_ref=base_sha,
            candidate_ref=candidate_sha,
            proof_path=proof_path,
            debt_path=debt_path,
        )

    output = repo / ".git" / "diffwitness" / "change-envelope.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_suffix(".json.tmp")
    staged.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    staged.replace(output)

    # Deterministic IdleProof is generated from the exact same frozen candidate as Proof/Debt.
    # It is deliberately additive: presentation degradation must never erase accepted evidence.
    try:
        from .diffing import parse_file_patches
        from .idleproof_explanation import write_explanation_artifact

        files = parse_file_patches(diff_text(repo, base_sha, candidate_sha))
        explanation_path = write_explanation_artifact(
            repo=repo,
            envelope=envelope,
            file_patches=files,
            debt_signals=list(report.signals) if report is not None else (),
        )
        print(f"IdleProof explanation: {explanation_path}")
    except Exception as exc:
        print(f"IdleProof deterministic explanation deferred: {str(exc)[:300]}", file=sys.stderr)

    print(f"Change envelope: {output}")
    return output


def _sync_idleproof_assurance(repo: Path, envelope_path: Path) -> None:
    """Best-effort bridge into the optional IdleProof understanding layer.

    The envelope is already exact-bound and authoritative evidence remains in DiffWitness. An
    absent/older IdleProof install must never make a valid Guard fail.
    """
    executable = shutil.which("idleproof")
    if executable is None or not (repo / ".idleproof" / "receipt.json").is_file():
        return
    try:
        proc = subprocess.run(
            [executable, "portal", "assurance", "--envelope", str(envelope_path), "--quiet"],
            cwd=repo,
            check=False,
            timeout=15,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"IdleProof assurance sync deferred: {exc}", file=sys.stderr)
        return
    if proc.returncode not in {0, 2}:
        detail = (proc.stderr or proc.stdout or "unsupported IdleProof assurance bridge").strip().splitlines()[-1]
        print(f"IdleProof assurance sync deferred: {detail[:240]}", file=sys.stderr)


def guard_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw guard",
        description="Run a coding agent inside a before/after DiffWitness proof and debt boundary.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--test")
    parser.add_argument("--prepare")
    parser.add_argument("--timeout", type=float)
    parser.add_argument(
        "--max-total-seconds",
        type=float,
        default=None,
        help="Maximum wall-clock seconds for proof after the agent exits (default/config: 900)",
    )
    parser.add_argument("--share", action="append", default=[])
    parser.add_argument("--test-glob", action="append", default=[])
    parser.add_argument("--ignore", action="append", default=[])
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
        help="Fail instead of using the Community planner if the adaptive advisory engine is unavailable or invalid",
    )
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-debt", action="store_true", help="Run the proof boundary without Debt Ledger measurement")
    parser.add_argument("agent", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = list(args.agent)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("an agent command is required after -- (for example: dw guard -- claude)")

    repo = repo_root(args.repo)
    config = load_config(repo, args.config)
    max_total_seconds = float(
        args.max_total_seconds
        if args.max_total_seconds is not None
        else config.get("max_total_seconds", DEFAULT_MAX_TOTAL_SECONDS)
    )
    if max_total_seconds <= 0:
        parser.error("--max-total-seconds must be > 0")
    if args.engine_timeout is not None and args.engine_timeout <= 0:
        parser.error("--engine-timeout must be > 0")
    debt_config = merged_debt_config(config.get("debt") or {})
    ledger = DebtLedger.load(ledger_path(repo, debt_config))
    baseline = snapshot_worktree(repo)
    print(f"DiffWitness Guard armed at {baseline[:12]}")
    print(f"Agent:    {' '.join(command)}")
    print(f"Policy:   {args.policy or 'config/default'}")
    print(f"Strategy: {args.strategy or 'config/default'}")
    print(f"Proof budget: {max_total_seconds:g}s after agent exit")
    print()

    env = os.environ.copy()
    env["DIFFWITNESS_BASE"] = baseline
    try:
        proc = subprocess.run(command, cwd=repo, env=env)
    except FileNotFoundError as exc:
        print(f"DiffWitness Guard: cannot start agent command: {exc}", file=sys.stderr)
        return 127
    except OSError as exc:
        print(f"DiffWitness Guard: agent process failed to start: {exc}", file=sys.stderr)
        return 126
    if proc.returncode != 0:
        print(f"DiffWitness Guard: agent exited with code {proc.returncode}; proof was not attempted.", file=sys.stderr)
        return proc.returncode

    candidate = snapshot_worktree(repo)
    if candidate == baseline or not diff_text(repo, baseline, candidate).strip():
        print("DiffWitness Guard: agent produced no repository change; proof not required.")
        return 0

    gate_args = [
        "--repo", str(repo), "--base", baseline, "--candidate", candidate,
        "--max-total-seconds", str(max_total_seconds), "--no-github-actions"
    ]
    if args.config:
        gate_args += ["--config", args.config]
    if args.test:
        gate_args += ["--test", args.test]
    if args.prepare:
        gate_args += ["--prepare", args.prepare]
    if args.timeout is not None:
        gate_args += ["--timeout", str(args.timeout)]
    if args.policy is not None:
        gate_args += ["--policy", args.policy]
    if args.strategy is not None:
        gate_args += ["--strategy", args.strategy]
    if args.adaptive_threshold is not None:
        gate_args += ["--adaptive-threshold", str(args.adaptive_threshold)]
    if args.adaptive_budget is not None:
        gate_args += ["--adaptive-budget", str(args.adaptive_budget)]
    if args.stability_runs is not None:
        gate_args += ["--stability-runs", str(args.stability_runs)]
    if args.engine:
        gate_args += ["--engine", args.engine]
    if args.engine_timeout is not None:
        gate_args += ["--engine-timeout", str(args.engine_timeout)]
    if args.engine_required is not None:
        gate_args += ["--engine-required" if args.engine_required else "--no-engine-required"]
    for path in args.share:
        gate_args += ["--share", path]
    for pattern in args.test_glob:
        gate_args += ["--test-glob", pattern]
    for pattern in args.ignore:
        gate_args += ["--ignore", pattern]
    if args.report:
        gate_args += ["--report", str(args.report)]

    # Use the public entrypoint rather than gate_cli directly so Guard gets the exact same formal
    # docs-only/test-only preflight semantics as CI and `dw gate`.
    from .entry import main as entry_main

    with tempfile.TemporaryDirectory(prefix="diffwitness-guard-") as td:
        temp_dir = Path(td)
        proof_path = args.certificate or (temp_dir / "guard-proof.json")
        gate_args += ["--certificate", str(proof_path)]
        rc = entry_main(["gate", *gate_args])
        if rc != 0:
            print("\nDiffWitness Guard: PROOF REJECTED", file=sys.stderr)
            return rc
        print("\nDiffWitness Guard: PROOF ACCEPTED")
        _validate_generated_certificate(proof_path, repo=repo, candidate_sha=candidate)

        if args.no_debt:
            envelope_path = _persist_guard_envelope(
                repo=repo,
                base_sha=baseline,
                candidate_sha=candidate,
                proof_path=proof_path,
                temp_dir=temp_dir,
            )
            _sync_idleproof_assurance(repo, envelope_path)
            return 0

        report = scan_change(
            repo=repo,
            base_sha=baseline,
            candidate_sha=candidate,
            certificate_path=proof_path,
            test_globs=list(config.get("test_glob") or []),
            ignore_globs=list(config.get("ignore") or []),
        )
        provenance = _agent_provenance(command)
        for signal in report.signals:
            signal.introduced_by.update(provenance)
        report.metadata["agent_provenance"] = provenance

        auto_record = bool(debt_config.get("auto_record", True))
        tracked_ledger = _tracked_ledger(repo, ledger.path)
        should_record = auto_record and not tracked_ledger
        budget, stats = evaluate_and_record(
            ledger=ledger,
            change=report,
            debt_config=debt_config,
            actor="diffwitness-guard",
            record=should_record,
            record_if_budget_fails=False,
        )
        _print_change_debt(report, budget)

        if auto_record and tracked_ledger:
            print("Debt Ledger: configured ledger is tracked by Git; Guard will not mutate it after proof. Run `dw debt` explicitly to record an accepted change.")
        elif should_record and budget.passed:
            print(f"Debt Ledger: +{stats['introduced']} introduced, {stats['reopened']} reopened, {stats['refreshed']} refreshed")
        elif should_record and not budget.passed:
            print("Debt Ledger: rejected change was not admitted to the durable ledger.")

        envelope_path = _persist_guard_envelope(
            repo=repo,
            base_sha=baseline,
            candidate_sha=candidate,
            proof_path=proof_path,
            temp_dir=temp_dir,
            report=report,
            budget=budget,
        )
        _sync_idleproof_assurance(repo, envelope_path)

        if not budget.passed:
            print("DiffWitness Guard: DEBT BUDGET REJECTED", file=sys.stderr)
            return 1
    return 0
