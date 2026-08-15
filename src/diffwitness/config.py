from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = ".diffwitness.toml"
KNOWN_KEYS = {
    "test",
    "prepare",
    "timeout",
    "stability_runs",
    "sufficient_search",
    "max_subset_order",
    "max_subset_runs",
    "interaction_search",
    "max_interaction_runs",
    "test_glob",
    "ignore",
    "share",
    "test_overlay",
    "policy",
    "strategy",
    "adaptive_threshold",
    "adaptive_budget",
}


def _positive_int(section: dict[str, Any], key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"DiffWitness config `{key}` must be a positive integer")


def _bool(section: dict[str, Any], key: str) -> None:
    if key in section and not isinstance(section[key], bool):
        raise ValueError(f"DiffWitness config `{key}` must be true or false")


def _string_list(section: dict[str, Any], key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"DiffWitness config `{key}` must be an array of strings")


def validate_config(section: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(section) - KNOWN_KEYS)
    if unknown:
        raise ValueError(
            "Unknown DiffWitness config key(s): " + ", ".join(unknown) + ". "
            "Failing rather than silently changing proof semantics."
        )

    for key in ("test", "prepare"):
        if key in section and section[key] is not None and not isinstance(section[key], str):
            raise ValueError(f"DiffWitness config `{key}` must be a string")
    if "test" in section and isinstance(section["test"], str) and not section["test"].strip():
        raise ValueError("DiffWitness config `test` cannot be empty")

    if "timeout" in section:
        value = section["timeout"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("DiffWitness config `timeout` must be a positive number")

    for key in (
        "stability_runs",
        "max_subset_order",
        "max_subset_runs",
        "max_interaction_runs",
        "adaptive_threshold",
        "adaptive_budget",
    ):
        _positive_int(section, key)
    for key in ("sufficient_search", "interaction_search", "test_overlay"):
        _bool(section, key)
    for key in ("test_glob", "ignore", "share"):
        _string_list(section, key)

    if "policy" in section and section["policy"] not in {"observe", "balanced", "strict"}:
        raise ValueError("DiffWitness config `policy` must be observe, balanced, or strict")
    if "strategy" in section and section["strategy"] not in {"auto", "exhaustive", "adaptive"}:
        raise ValueError("DiffWitness config `strategy` must be auto, exhaustive, or adaptive")
    return dict(section)


def load_config(repo: Path, explicit: str | None = None) -> dict[str, Any]:
    path = Path(explicit) if explicit else repo / DEFAULT_CONFIG
    if explicit and not path.is_absolute():
        path = repo / path
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("diffwitness", data)
    if not isinstance(section, dict):
        raise ValueError("DiffWitness config must contain a [diffwitness] table")
    return validate_config(section)


def write_config(repo: Path, *, test: str, prepare: str | None, force: bool = False) -> Path:
    path = repo / DEFAULT_CONFIG
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; use --force to replace it")
    escaped_test = test.replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        "[diffwitness]",
        f'test = "{escaped_test}"',
        'policy = "balanced"',
        'strategy = "auto"',
        "adaptive_threshold = 16",
        "adaptive_budget = 40",
        "stability_runs = 2",
        "sufficient_search = true",
        "max_subset_order = 3",
        "max_subset_runs = 32",
        "interaction_search = true",
        "max_interaction_runs = 20",
        "test_overlay = true",
    ]
    if prepare:
        escaped = prepare.replace("\\", "\\\\").replace('"', '\\"')
        lines.insert(2, f'prepare = "{escaped}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
