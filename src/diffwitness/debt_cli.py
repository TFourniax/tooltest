from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .autodetect import default_evidence
from .config import load_config
from .debt_budget import evaluate_budget, ledger_path, merged_debt_config
from .debt_certificate import validate_debt_certificate
from .debt_history import trend
from .debt_models import DebtReport, sort_signals
from .debt_scan import scan_change
from .debt_verify import recheck_item
from .gitops import repo_root, resolve_ref, snapshot_worktree
from .ledger import DebtLedger, LedgerError, LedgerItem
from .project_scan import scan_project


def _resolve_debt_context(repo: Path, explicit_config: str | None) -> tuple[dict[str, Any], dict[str, Any], DebtLedger]:
    config = load_config(repo, explicit_config)
    debt_config = merged_debt_config(config.get("debt") or {})
    return config, debt_config, DebtLedger.load(ledger_path(repo, debt_config))


def _resolve_test(repo: Path, config: dict[str, Any], explicit: str | None) -> str | None:
    if explicit and explicit.strip(): return explicit
    configured = config.get("test")
    if isinstance(configured, str) and configured.strip(): return configured
    plan = default_evidence(repo)
    return plan.command if plan else None


def _candidate(repo: Path, raw: str, *, exclude_paths: list[str] | None = None) -> tuple[str, str]:
    if raw.upper() == "WORKTREE": return snapshot_worktree(repo, exclude_paths=exclude_paths or []), "WORKTREE"
    return resolve_ref(repo, raw), raw


def _ledger_relpath(repo: Path, ledger: DebtLedger) -> str | None:
    try: return ledger.path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError: return None


def _ledger_snapshot_exclusions(repo: Path, ledger: DebtLedger) -> list[str]:
    rel = _ledger_relpath(repo, ledger)
    if not rel or rel == ".git" or rel.startswith(".git/"): return []
    return [rel]


def _validate_certificate(path: Path | None, *, repo: Path, candidate_sha: str) -> None:
    if path is None: return
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise LedgerError(f"cannot read proof certificate {path}: {exc}") from exc
    if not isinstance(payload, dict): raise LedgerError("proof certificate must be a JSON object")
    validate_debt_certificate(payload, repo=repo, candidate_sha=candidate_sha)


def _agent_name(command: list[str]) -> str:
    executable = Path(command[0]).name if command else "unknown"
    lowered = executable.lower()
    if "claude" in lowered: return "claude-code"
    if "codex" in lowered: return "codex"
    return executable


def _print_signals(report: DebtReport, *, max_signals: int = 30) -> None:
    print(f"Debt impact: +{report.total_points} point(s) across {len(report.signals)} obligation(s)")
    for category, points in sorted(report.by_category.items(), key=lambda item: (-item[1], item[0])): print(f"  {category:18} +{points}")
    if not report.signals: print("  no debt signals detected under the configured rules"); return
    print()
    for signal in sort_signals(report.signals)[:max_signals]:
        location = f" {signal.path}" if signal.path else ""
        if signal.line: location += f":{signal.line}"
        print(f"{signal.debt_id}  +{int(signal.points or 0):>2}  {signal.category}/{signal.measurement}{location} — {signal.title}")
    if len(report.signals) > max_signals: print(f"… {len(report.signals) - max_signals} additional signal(s)")


def _print_health(project: DebtReport, ledger: DebtLedger) -> None:
    active = ledger.active_items(); print("DIFFWITNESS\nProject health / debt ledger"); print(f"Debt                     {ledger.active_points()}"); print("--------------------------------")
    for category, points in sorted(ledger.active_by_category().items(), key=lambda item: (-item[1], item[0])): print(f"{category:24} {points:>5}")
    accepted = sum(item.points for item in active if item.accepted)
    if accepted: print(f"accepted debt             {accepted:>5}")
    print(f"\nCurrent project scan: {project.total_points} point(s), {len(project.signals)} signal(s)")
    hotspots: dict[str, int] = {}
    for item in active:
        if item.path: hotspots[item.path] = hotspots.get(item.path, 0) + item.points
    if hotspots:
        print("High-debt areas")
        for path, points in sorted(hotspots.items(), key=lambda item: (-item[1], item[0]))[:8]: print(f"  {points:>3}  {path}")


def _write_json(path: Path | None, value: dict[str, Any]) -> None:
    if not path: return
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def debt_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw debt", description="Measure debt introduced by a Git change and optionally record its lineages.")
    parser.add_argument("--repo", default="."); parser.add_argument("--config"); parser.add_argument("--base", default="HEAD"); parser.add_argument("--candidate", default="WORKTREE")
    parser.add_argument("--certificate", type=Path, help="Existing DiffWitness proof/assurance certificate for this exact change"); parser.add_argument("--json", type=Path); parser.add_argument("--no-record", action="store_true"); parser.add_argument("--ignore-budget", action="store_true")
    args = parser.parse_args(argv); repo = repo_root(args.repo); config, debt_config, ledger = _resolve_debt_context(repo, args.config)
    base_sha = resolve_ref(repo, args.base); candidate_sha, _ = _candidate(repo, args.candidate, exclude_paths=_ledger_snapshot_exclusions(repo, ledger)); _validate_certificate(args.certificate, repo=repo, candidate_sha=candidate_sha)
    report = scan_change(repo=repo, base_sha=base_sha, candidate_sha=candidate_sha, certificate_path=args.certificate, test_globs=list(config.get("test_glob") or []), ignore_globs=list(config.get("ignore") or []))
    budget = evaluate_budget(ledger=ledger, change=report, debt_config=debt_config); _print_signals(report); print(); print(f"Budget: {'PASS' if budget.passed else 'EXCEEDED'} — projected total {budget.projected_total}; new {budget.change_points}")
    for violation in budget.violations: print(f"  ! {violation}")
    if not args.no_record and debt_config.get("auto_record", True):
        stats = ledger.record_report(report); print(f"Ledger: +{stats['introduced']} introduced, {stats['reopened']} reopened, {stats['refreshed']} refreshed")
    _write_json(args.json, {"report": report.to_dict(), "budget": budget.to_dict(), "ledger": ledger.export_state()})
    return 0 if budget.passed or args.ignore_budget else 1


def health_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw health", description="Scan current project debt and reconcile the local Debt Ledger.")
    parser.add_argument("--repo", default="."); parser.add_argument("--config"); parser.add_argument("--json", type=Path); parser.add_argument("--no-record", action="store_true"); parser.add_argument("--trend-days", type=int, default=30)
    args = parser.parse_args(argv)
    if args.trend_days < 1: parser.error("--trend-days must be positive")
    repo = repo_root(args.repo); _, debt_config, ledger = _resolve_debt_context(repo, args.config)
    report = scan_project(repo=repo, duplicate_scan=bool(debt_config.get("duplicate_scan", True)), max_scan_files=int(debt_config.get("max_scan_files", 500)), max_duplicate_signals=int(debt_config.get("max_duplicate_signals", 20)))
    if not args.no_record and debt_config.get("auto_record", True): ledger.reconcile_project_report(report)
    _print_health(report, ledger); debt_trend = trend(ledger, days=args.trend_days); arrow = "↑" if debt_trend.delta_points > 0 else ("↓" if debt_trend.delta_points < 0 else "→")
    print(f"Trend {args.trend_days}d              {debt_trend.delta_points:+d} {arrow}"); print(f"  introduced {debt_trend.introduced} / resolved {debt_trend.resolved} / reopened {debt_trend.reopened}")
    budget = evaluate_budget(ledger=ledger, change=None, debt_config=debt_config)
    if not budget.passed:
        print("\nDebt budget exceeded")
        for violation in budget.violations: print(f"  ! {violation}")
    _write_json(args.json, {"project_scan": report.to_dict(), "ledger": ledger.export_state(), "trend": debt_trend.to_dict(), "budget": budget.to_dict()})
    return 0 if budget.passed else 1


def _plan_items(items: list[LedgerItem], *, max_points: int, limit: int) -> list[LedgerItem]:
    chosen: list[LedgerItem] = []; points = 0
    for item in sorted(items, key=lambda value: (-value.points, value.measurement != "causal", value.category, value.debt_id)):
        if len(chosen) >= limit: break
        if chosen and points + item.points > max_points: continue
        chosen.append(item); points += item.points
    return chosen


def plan_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw plan", description="Build an explainable repayment plan from open Debt Ledger items.")
    parser.add_argument("--repo", default="."); parser.add_argument("--config"); parser.add_argument("--max-points", type=int, default=30); parser.add_argument("--limit", type=int, default=8); parser.add_argument("--include-accepted", action="store_true"); parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.max_points < 1 or args.limit < 1: parser.error("--max-points and --limit must be positive")
    repo = repo_root(args.repo); _, _, ledger = _resolve_debt_context(repo, args.config); selected = _plan_items(ledger.active_items(include_accepted=args.include_accepted), max_points=args.max_points, limit=args.limit)
    payload = {"selected_points": sum(item.points for item in selected), "selected": [item.to_dict() for item in selected], "non_claim": "This is a deterministic priority plan, not a forecast of engineering time or guaranteed point reduction."}
    if args.json: print(json.dumps(payload, indent=2, ensure_ascii=False)); return 0
    if not selected: print("DiffWitness plan: no open debt selected."); return 0
    print(f"Repayment plan — {payload['selected_points']} point(s), {len(selected)} obligation(s)")
    for index, item in enumerate(selected, 1): print(f"{index}. {item.debt_id} [{item.category}/{item.measurement}] {item.title} (+{item.points})" + (f" — {item.path}" if item.path else ""))
    print("\nThe point total is accounting weight, not an estimate of minutes or difficulty."); return 0


def _repayment_prompt(items: list[LedgerItem]) -> str:
    lines = ["You are repaying explicitly tracked DiffWitness software debt.", "", "Constraints:", "- Preserve currently validated behavior unless a debt item explicitly requires a behavior correction.", "- Change only what is necessary to resolve the listed obligations.", "- Do not add dependencies unless a listed debt item requires one and no existing facility suffices.", "- Add or improve regression evidence when the debt is evidence/test related.", "- Prefer removing redundant surface over adding abstractions solely to make a metric green.", "- Do not edit the DiffWitness debt ledger directly.", "- Finish with the repository in a testable state; DiffWitness will independently gate and re-measure it.", "", "Debt obligations:"]
    for item in items:
        location = item.path or "project"
        if item.line: location += f":{item.line}"
        lines += [f"- {item.debt_id} | {item.category} | {item.measurement} | {item.points} point(s)", f"  {item.title}", f"  Location: {location}", f"  Why open: {item.explanation}", f"  Verification expected: {json.dumps(item.verification, sort_keys=True, ensure_ascii=False)}"]
    return "\n".join(lines) + "\n"


def _split_agent(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" not in argv: return argv, []
    index = argv.index("--"); return argv[:index], argv[index + 1:]


def _command_with_prompt(command: list[str], prompt: str) -> list[str]:
    if any("{prompt}" in token for token in command): return [token.replace("{prompt}", prompt) for token in command]
    return [*command, prompt]


def repay_cli(argv: list[str]) -> int:
    parse_argv, agent_command = _split_agent(argv)
    parser = argparse.ArgumentParser(prog="dw repay", description="Run a constrained debt-repayment mission and independently verify the result.")
    parser.add_argument("debt_ids", nargs="*"); parser.add_argument("--repo", default="."); parser.add_argument("--config"); parser.add_argument("--all", action="store_true"); parser.add_argument("--max-points", type=int, default=20); parser.add_argument("--limit", type=int, default=6); parser.add_argument("--test"); parser.add_argument("--allow-new-debt", action="store_true"); parser.add_argument("--prompt-only", action="store_true"); parser.add_argument("--json", type=Path)
    args = parser.parse_args(parse_argv)
    if args.debt_ids and args.all: parser.error("use explicit debt IDs or --all, not both")
    repo = repo_root(args.repo); config, debt_config, ledger = _resolve_debt_context(repo, args.config); state = ledger.items()
    if args.debt_ids:
        missing = [debt_id for debt_id in args.debt_ids if debt_id not in state or not state[debt_id].active]
        if missing: raise LedgerError("unknown/non-open debt id(s): " + ", ".join(missing))
        selected = [state[debt_id] for debt_id in args.debt_ids]
    else:
        available = ledger.active_items(include_accepted=False); selected = available if args.all else _plan_items(available, max_points=args.max_points, limit=args.limit)
    if not selected: print("DiffWitness repay: no open unaccepted debt selected."); return 0
    prompt = _repayment_prompt(selected)
    if args.prompt_only or not agent_command: print(prompt); return 0
    test_command = _resolve_test(repo, config, args.test)
    if not test_command: raise LedgerError("automatic repayment requires an evidence command; configure [diffwitness].test or pass --test")
    exclude = _ledger_snapshot_exclusions(repo, ledger); baseline = snapshot_worktree(repo, exclude_paths=exclude); preexisting_ids = {item.debt_id for item in ledger.active_items()}; before_event_count = len(ledger.events)
    env = os.environ.copy(); env["DIFFWITNESS_REPAY"] = "1"; env["DIFFWITNESS_BASE"] = baseline; command = _command_with_prompt(agent_command, prompt)
    print(f"DiffWitness Repay: {len(selected)} obligation(s), {sum(item.points for item in selected)} point(s)\nAgent: {' '.join(agent_command)}")
    try: proc = subprocess.run(command, cwd=repo, env=env)
    except FileNotFoundError as exc: print(f"DiffWitness repay: cannot start agent: {exc}", file=sys.stderr); return 127
    if proc.returncode != 0: print(f"DiffWitness repay: agent exited with code {proc.returncode}; verification stopped.", file=sys.stderr); return proc.returncode
    candidate = snapshot_worktree(repo, exclude_paths=exclude)
    if candidate == baseline: print("DiffWitness repay: agent produced no repository change; debt remains open.", file=sys.stderr); return 1
    from .entry import main as entry_main
    with tempfile.TemporaryDirectory(prefix="diffwitness-repay-") as td:
        certificate = Path(td) / "gate.json"; gate_args = ["--repo", str(repo), "--base", baseline, "--candidate", candidate, "--test", test_command, "--policy", "balanced", "--certificate", str(certificate), "--no-github-actions"]
        rc = entry_main(["gate", *gate_args])
        if rc != 0: print("DiffWitness repay: independent Gate rejected the repayment patch.", file=sys.stderr); return 1
        _validate_certificate(certificate if certificate.exists() else None, repo=repo, candidate_sha=candidate)
        change_report = scan_change(repo=repo, base_sha=baseline, candidate_sha=candidate, certificate_path=certificate if certificate.exists() else None, test_globs=list(config.get("test_glob") or []), ignore_globs=list(config.get("ignore") or []))
        provenance = {"source": "repay", "agent": _agent_name(agent_command), "executable": Path(agent_command[0]).name}
        for signal in change_report.signals: signal.introduced_by.update(provenance)
        change_report.metadata["agent_provenance"] = provenance
        budget_before_record = evaluate_budget(ledger=ledger, change=change_report, debt_config=debt_config); ledger.record_report(change_report, actor="diffwitness-repay")
    current = snapshot_worktree(repo, exclude_paths=exclude); rechecks = []
    for original in selected:
        fresh = ledger.items().get(original.debt_id) or original
        result = recheck_item(fresh, repo=repo, current_sha=current, test_command=test_command, stability_runs=int(config.get("stability_runs", 2)), timeout=float(config.get("timeout", 300.0)), prepare_command=str(config.get("prepare")) if config.get("prepare") else None, shared_paths=list(config.get("share") or []), duplicate_scan=bool(debt_config.get("duplicate_scan", True)), max_scan_files=int(debt_config.get("max_scan_files", 500)), max_duplicate_signals=int(debt_config.get("max_duplicate_signals", 20)))
        rechecks.append(result)
        if result.resolved: ledger.resolve(fresh.debt_id, reason=result.reason, verification=result.verification, actor="diffwitness-repay")
    final_budget = evaluate_budget(ledger=ledger, change=None, debt_config=debt_config); active_now = {item.debt_id for item in ledger.active_items()}; new_open = sorted(active_now - preexisting_ids); unresolved = [result.debt_id for result in rechecks if not result.resolved]
    output = {"selected": [item.debt_id for item in selected], "rechecks": [result.to_dict() for result in rechecks], "new_open_debt": new_open, "unresolved_selected": unresolved, "change_report": change_report.to_dict(), "budget_before_record": budget_before_record.to_dict(), "final_budget": final_budget.to_dict(), "ledger_event_delta": len(ledger.events) - before_event_count}; _write_json(args.json, output)
    print(f"\nRepayment verification: {len(selected) - len(unresolved)}/{len(selected)} selected obligation(s) resolved")
    for result in rechecks: print(f"  {result.debt_id}: {result.status} — {result.reason}")
    if new_open: print(f"New open debt introduced: {', '.join(new_open)}")
    for violation in final_budget.violations: print(f"Budget violation: {violation}")
    success = not unresolved and final_budget.passed and (args.allow_new_debt or not new_open); print(f"DiffWitness Repay: {'ACCEPTED' if success else 'REJECTED'}"); return 0 if success else 1


def recheck_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dw recheck", description="Replay verification adapters for existing debt lineages.")
    parser.add_argument("debt_ids", nargs="*"); parser.add_argument("--repo", default="."); parser.add_argument("--config"); parser.add_argument("--all", action="store_true"); parser.add_argument("--test"); parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.debt_ids and not args.all: raise LedgerError("specify debt IDs or --all")
    repo = repo_root(args.repo); config, debt_config, ledger = _resolve_debt_context(repo, args.config); items = ledger.items(); selected = ledger.active_items() if args.all else []
    for debt_id in args.debt_ids:
        item = items.get(debt_id)
        if item is None or not item.active: raise LedgerError(f"unknown/non-open debt id: {debt_id}")
        selected.append(item)
    test_command = _resolve_test(repo, config, args.test); current = snapshot_worktree(repo); results = []
    for item in selected:
        result = recheck_item(item, repo=repo, current_sha=current, test_command=test_command, stability_runs=int(config.get("stability_runs", 2)), timeout=float(config.get("timeout", 300.0)), prepare_command=str(config.get("prepare")) if config.get("prepare") else None, shared_paths=list(config.get("share") or []), duplicate_scan=bool(debt_config.get("duplicate_scan", True)), max_scan_files=int(debt_config.get("max_scan_files", 500)), max_duplicate_signals=int(debt_config.get("max_duplicate_signals", 20))); results.append(result)
        if result.resolved: ledger.resolve(item.debt_id, reason=result.reason, verification=result.verification, actor="diffwitness-recheck")
    if args.json: print(json.dumps([result.to_dict() for result in results], indent=2, ensure_ascii=False))
    else:
        for result in results: print(f"{result.debt_id}: {result.status} — {result.reason}")
    return 0 if all(result.status != "inconclusive" for result in results) else 1


def ledger_cli(argv: list[str]) -> int:
    """Backward-compatible import shim; the implementation lives in ledger_cli.py."""
    from .ledger_cli import ledger_cli as implementation

    return implementation(argv)
