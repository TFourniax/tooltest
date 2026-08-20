from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .debt_models import DEBT_CATEGORIES

DEFAULT_CONFIG = ".diffwitness.toml"
KNOWN_KEYS = {
    "test", "prepare", "timeout", "stability_runs", "sufficient_search", "max_subset_order",
    "max_subset_runs", "interaction_search", "max_interaction_runs", "test_glob", "ignore", "share",
    "test_overlay", "policy", "strategy", "adaptive_threshold", "adaptive_budget", "debt",
}
DEBT_KEYS = {
    "ledger", "max_total", "max_per_change", "category_limits", "duplicate_scan", "max_scan_files",
    "max_duplicate_signals", "auto_record", *DEBT_CATEGORIES,
}


def _positive_int(section: dict[str, Any], key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"DiffWitness config `{key}` must be a positive integer")


def _nonnegative_int_or_none(section: dict[str, Any], key: str, *, prefix: str = "") -> None:
    if key not in section or section[key] is None:
        return
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"DiffWitness config `{prefix}{key}` must be a non-negative integer or omitted")


def _bool(section: dict[str, Any], key: str, *, prefix: str = "") -> None:
    if key in section and not isinstance(section[key], bool):
        raise ValueError(f"DiffWitness config `{prefix}{key}` must be true or false")


def _string_list(section: dict[str, Any], key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"DiffWitness config `{key}` must be an array of strings")


def validate_debt_config(section: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(section) - DEBT_KEYS)
    if unknown:
        raise ValueError("Unknown DiffWitness debt config key(s): " + ", ".join(unknown) + ". Failing rather than silently changing debt semantics.")
    if "ledger" in section and (not isinstance(section["ledger"], str) or not section["ledger"].strip()):
        raise ValueError("DiffWitness config `debt.ledger` must be a non-empty string")
    for key in ("max_total", "max_per_change"):
        _nonnegative_int_or_none(section, key, prefix="debt.")
    for key in ("max_scan_files", "max_duplicate_signals"):
        if key in section:
            value = section[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"DiffWitness config `debt.{key}` must be a positive integer")
    for key in ("duplicate_scan", "auto_record"):
        _bool(section, key, prefix="debt.")

    limits = section.get("category_limits")
    if limits is not None:
        if not isinstance(limits, dict):
            raise ValueError("DiffWitness config `debt.category_limits` must be a table")
        unknown_categories = sorted(set(limits) - set(DEBT_CATEGORIES))
        if unknown_categories:
            raise ValueError("Unknown DiffWitness debt category limit(s): " + ", ".join(unknown_categories))
        for category, value in limits.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"DiffWitness config `debt.category_limits.{category}` must be a non-negative integer")

    normalized = dict(section)
    merged_limits = dict(limits or {})
    for category in DEBT_CATEGORIES:
        nested = section.get(category)
        if nested is None:
            continue
        if not isinstance(nested, dict):
            raise ValueError(f"DiffWitness config `debt.{category}` must be a table")
        unknown_nested = sorted(set(nested) - {"max"})
        if unknown_nested:
            raise ValueError(f"Unknown DiffWitness config key(s) under debt.{category}: " + ", ".join(unknown_nested))
        if "max" in nested:
            value = nested["max"]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"DiffWitness config `debt.{category}.max` must be a non-negative integer")
            merged_limits[category] = value
        normalized.pop(category, None)
    normalized["category_limits"] = merged_limits
    return normalized


def validate_config(section: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(section) - KNOWN_KEYS)
    if unknown:
        raise ValueError("Unknown DiffWitness config key(s): " + ", ".join(unknown) + ". Failing rather than silently changing proof semantics.")
    for key in ("test", "prepare"):
        if key in section and section[key] is not None and not isinstance(section[key], str):
            raise ValueError(f"DiffWitness config `{key}` must be a string")
    if "test" in section and isinstance(section["test"], str) and not section["test"].strip():
        raise ValueError("DiffWitness config `test` cannot be empty")
    if "timeout" in section:
        value = section["timeout"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("DiffWitness config `timeout` must be a positive number")
    for key in ("stability_runs", "max_subset_order", "max_subset_runs", "max_interaction_runs", "adaptive_threshold", "adaptive_budget"):
        _positive_int(section, key)
    for key in ("sufficient_search", "interaction_search", "test_overlay"):
        _bool(section, key)
    for key in ("test_glob", "ignore", "share"):
        _string_list(section, key)
    if "policy" in section and section["policy"] not in {"observe", "balanced", "strict"}:
        raise ValueError("DiffWitness config `policy` must be observe, balanced, or strict")
    if "strategy" in section and section["strategy"] not in {"auto", "exhaustive", "adaptive"}:
        raise ValueError("DiffWitness config `strategy` must be auto, exhaustive, or adaptive")
    normalized = dict(section)
    if "debt" in normalized:
        if not isinstance(normalized["debt"], dict):
            raise ValueError("DiffWitness config `debt` must be a table")
        normalized["debt"] = validate_debt_config(dict(normalized["debt"]))
    return normalized


def _extract_sections(data: dict[str, Any]) -> dict[str, Any]:
    if "diffwitness" in data:
        raw = data["diffwitness"]
        if not isinstance(raw, dict):
            raise ValueError("DiffWitness config must contain a [diffwitness] table")
        section = dict(raw)
    else:
        section = {key: value for key, value in data.items() if key != "debt"}
    top_debt = data.get("debt")
    nested_debt = section.get("debt")
    if top_debt is not None and nested_debt is not None:
        raise ValueError("configure debt either as [debt] or [diffwitness.debt], not both")
    debt = nested_debt if nested_debt is not None else top_debt
    if debt is not None:
        if not isinstance(debt, dict):
            raise ValueError("DiffWitness debt config must be a table")
        section["debt"] = dict(debt)
    return section


def load_config(repo: Path, explicit: str | None = None) -> dict[str, Any]:
    path = Path(explicit) if explicit else repo / DEFAULT_CONFIG
    if explicit and not path.is_absolute():
        path = repo / path
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ValueError("DiffWitness config root must be a TOML table")
    return validate_config(_extract_sections(data))


def _toml_string(value: str) -> str:
    # TOML basic strings accept the JSON escape repertoire used here (quotes, backslashes,
    # controls and Unicode escapes). This is safer than hand-escaping only quotes/backslashes,
    # which produced invalid config for commands containing newlines or other control characters.
    return json.dumps(value, ensure_ascii=False)


def write_config(repo: Path, *, test: str, prepare: str | None, force: bool = False) -> Path:
    path = repo / DEFAULT_CONFIG
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; use --force to replace it")
    lines = [
        "[diffwitness]", f"test = {_toml_string(test)}", 'policy = "balanced"', 'strategy = "auto"',
        "adaptive_threshold = 16", "adaptive_budget = 40", "stability_runs = 2", "sufficient_search = true",
        "max_subset_order = 3", "max_subset_runs = 32", "interaction_search = true", "max_interaction_runs = 20",
        "test_overlay = true", "", "[debt]", 'ledger = ".git/diffwitness/debt-ledger.jsonl"', "auto_record = true",
        "duplicate_scan = true", "max_scan_files = 500", "max_duplicate_signals = 20",
    ]
    if prepare:
        lines.insert(2, f"prepare = {_toml_string(prepare)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path