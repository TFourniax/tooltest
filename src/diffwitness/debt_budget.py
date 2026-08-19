from __future__ import annotations

from pathlib import Path
from typing import Any

from .debt_models import DEBT_CATEGORIES, DebtBudgetResult, DebtReport
from .ledger import DebtLedger, _ledger_lock

DEFAULT_DEBT_CONFIG: dict[str, Any] = {
    "ledger": ".git/diffwitness/debt-ledger.jsonl",
    "max_total": None,
    "max_per_change": None,
    "category_limits": {},
    "duplicate_scan": True,
    "max_scan_files": 500,
    "max_duplicate_signals": 20,
    "auto_record": True,
}


def merged_debt_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_DEBT_CONFIG)
    if config:
        merged.update(config)
    merged["category_limits"] = dict((config or {}).get("category_limits") or {})
    return merged


def ledger_path(repo: Path, debt_config: dict[str, Any]) -> Path:
    raw = str(debt_config.get("ledger") or DEFAULT_DEBT_CONFIG["ledger"])
    path = Path(raw)
    return path if path.is_absolute() else repo / path


def evaluate_budget(*, ledger: DebtLedger, change: DebtReport | None, debt_config: dict[str, Any]) -> DebtBudgetResult:
    config = merged_debt_config(debt_config)
    active_total = ledger.active_points()
    active_by_category = ledger.active_by_category()
    active_ids = {item.debt_id for item in ledger.active_items()}
    genuinely_new_points = 0
    genuinely_new_by_category: dict[str, int] = {}
    if change:
        for signal in change.signals:
            if signal.debt_id in active_ids:
                continue
            points = int(signal.points or 0)
            genuinely_new_points += points
            genuinely_new_by_category[signal.category] = genuinely_new_by_category.get(signal.category, 0) + points

    projected_total = active_total + genuinely_new_points
    projected_by_category = dict(active_by_category)
    for category, points in genuinely_new_by_category.items():
        projected_by_category[category] = projected_by_category.get(category, 0) + points

    violations: list[str] = []
    max_total = config.get("max_total")
    if max_total is not None and projected_total > int(max_total):
        violations.append(f"total debt {projected_total} exceeds budget {int(max_total)}")
    max_change = config.get("max_per_change")
    if max_change is not None and genuinely_new_points > int(max_change):
        violations.append(f"new debt {genuinely_new_points} exceeds per-change budget {int(max_change)}")
    limits = config.get("category_limits") or {}
    for category in DEBT_CATEGORIES:
        limit = limits.get(category)
        if limit is None:
            continue
        points = projected_by_category.get(category, 0)
        if points > int(limit):
            violations.append(f"{category} debt {points} exceeds budget {int(limit)}")

    return DebtBudgetResult(
        passed=not violations,
        projected_total=projected_total,
        change_points=genuinely_new_points,
        active_total=active_total,
        violations=violations,
        projected_by_category=projected_by_category,
    )


def evaluate_and_record(
    *,
    ledger: DebtLedger,
    change: DebtReport,
    debt_config: dict[str, Any],
    actor: str = "diffwitness",
    record: bool = True,
    record_if_budget_fails: bool = True,
) -> tuple[DebtBudgetResult, dict[str, int]]:
    """Evaluate against the latest ledger and optionally append in one writer transaction.

    Budget checks are admission-control decisions. Evaluating on a stale in-memory ledger and only
    taking the ledger lock later during `record_report` lets two concurrent agents both observe spare
    budget and then exceed it together. This helper deliberately shares Debt Ledger's writer lock,
    adopts the current disk history, evaluates against that state, and (when requested) appends before
    releasing it.

    Explicit accounting commands may record a real change even when its budget is already exceeded.
    Admission-control paths such as Guard should set `record_if_budget_fails=False` so a rejected
    candidate is reported but not admitted into the durable ledger. `record=False` provides the same
    fresh, serialized point-in-time check without mutating the ledger.
    """
    with _ledger_lock(ledger.path):
        ledger._adopt_disk_events()
        budget = evaluate_budget(ledger=ledger, change=change, debt_config=debt_config)
        if record and (budget.passed or record_if_budget_fails):
            stats = ledger._record_report_unlocked(change, actor=actor)
        else:
            stats = {"introduced": 0, "reopened": 0, "refreshed": 0}
        return budget, stats
