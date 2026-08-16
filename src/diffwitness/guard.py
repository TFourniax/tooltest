from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import load_config
from .debt_budget import evaluate_budget, ledger_path, merged_debt_config
from .debt_scan import scan_change
from .gitops import diff_text, git, repo_root, snapshot_worktree
from .ledger import DebtLedger


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


def guard_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw guard", description="Run a coding agent inside a before/after DiffWitness proof and debt boundary.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--test")
    parser.add_argument("--prepare")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--share", action="append", default=[])
    parser.add_argument("--test-glob", action="append", default=[])
    parser.add_argument("--ignore", action="append", default=[])
    parser.add_argument("--policy", choices=["observe", "balanced", "strict"], default=None)
    parser.add_argument("--strategy", choices=["auto", "exhaustive", "adaptive"], default=None)
    parser.add_argument("--adaptive-threshold", type=int, default=None)
    parser.add_argument("--adaptive-budget", type=int, default=None)
    parser.add_argument("--stability-runs", type=int, default=None)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-debt", action="store_true", help="Run the proof boundary without Debt Ledger measurement")
    parser.add_argument("agent", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = list(args.agent)
    if command and command[0] == "--": command = command[1:]
    if not command: parser.error("an agent command is required after -- (for example: dw guard -- claude)")

    repo = repo_root(args.repo)
    config = load_config(repo, args.config)
    debt_config = merged_debt_config(config.get("debt") or {})
    ledger = DebtLedger.load(ledger_path(repo, debt_config))
    baseline = snapshot_worktree(repo)
    print(f"DiffWitness Guard armed at {baseline[:12]}")
    print(f"Agent:    {' '.join(command)}")
    print(f"Policy:   {args.policy or 'config/default'}")
    print(f"Strategy: {args.strategy or 'config/default'}")
    print()

    env = os.environ.copy(); env["DIFFWITNESS_BASE"] = baseline
    try:
        proc = subprocess.run(command, cwd=repo, env=env)
    except FileNotFoundError as exc:
        print(f"DiffWitness Guard: cannot start agent command: {exc}", file=sys.stderr); return 127
    except OSError as exc:
        print(f"DiffWitness Guard: agent process failed to start: {exc}", file=sys.stderr); return 126
    if proc.returncode != 0:
        print(f"DiffWitness Guard: agent exited with code {proc.returncode}; proof was not attempted.", file=sys.stderr); return proc.returncode

    candidate = snapshot_worktree(repo)
    if candidate == baseline or not diff_text(repo, baseline, candidate).strip():
        print("DiffWitness Guard: agent produced no repository change; proof not required."); return 0

    gate_args = ["--repo", str(repo), "--base", baseline, "--candidate", candidate, "--no-github-actions"]
    if args.config: gate_args += ["--config", args.config]
    if args.test: gate_args += ["--test", args.test]
    if args.prepare: gate_args += ["--prepare", args.prepare]
    if args.timeout is not None: gate_args += ["--timeout", str(args.timeout)]
    if args.policy is not None: gate_args += ["--policy", args.policy]
    if args.strategy is not None: gate_args += ["--strategy", args.strategy]
    if args.adaptive_threshold is not None: gate_args += ["--adaptive-threshold", str(args.adaptive_threshold)]
    if args.adaptive_budget is not None: gate_args += ["--adaptive-budget", str(args.adaptive_budget)]
    if args.stability_runs is not None: gate_args += ["--stability-runs", str(args.stability_runs)]
    for path in args.share: gate_args += ["--share", path]
    for pattern in args.test_glob: gate_args += ["--test-glob", pattern]
    for pattern in args.ignore: gate_args += ["--ignore", pattern]
    if args.report: gate_args += ["--report", str(args.report)]

    # Use the public entrypoint rather than gate_cli directly so Guard gets the exact same formal
    # docs-only/test-only preflight semantics as CI and `dw gate`.
    from .entry import main as entry_main
    with tempfile.TemporaryDirectory(prefix="diffwitness-guard-") as td:
        proof_path = args.certificate or (Path(td) / "guard-proof.json")
        gate_args += ["--certificate", str(proof_path)]
        rc = entry_main(["gate", *gate_args])
        if rc != 0:
            print("\nDiffWitness Guard: PROOF REJECTED", file=sys.stderr); return rc
        print("\nDiffWitness Guard: PROOF ACCEPTED")
        if args.no_debt:
            return 0
        report = scan_change(repo=repo, base_sha=baseline, candidate_sha=candidate,
                             certificate_path=proof_path if proof_path.exists() else None,
                             test_globs=list(config.get("test_glob") or []), ignore_globs=list(config.get("ignore") or []))
        budget = evaluate_budget(ledger=ledger, change=report, debt_config=debt_config)
        _print_change_debt(report, budget)
        if debt_config.get("auto_record", True):
            if _tracked_ledger(repo, ledger.path):
                print("Debt Ledger: configured ledger is tracked by Git; Guard will not mutate it after proof. Run `dw debt` explicitly to record the change.")
            else:
                stats = ledger.record_report(report, actor="diffwitness-guard")
                print(f"Debt Ledger: +{stats['introduced']} introduced, {stats['reopened']} reopened, {stats['refreshed']} refreshed")
        if not budget.passed:
            print("DiffWitness Guard: DEBT BUDGET REJECTED", file=sys.stderr); return 1
    return 0
