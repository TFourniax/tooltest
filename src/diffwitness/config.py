from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = ".diffwitness.toml"


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
    return dict(section)


def write_config(repo: Path, *, test: str, prepare: str | None, force: bool = False) -> Path:
    path = repo / DEFAULT_CONFIG
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; use --force to replace it")
    escaped_test = test.replace("\\", "\\\\").replace('"', '\\"')
    lines = [
        "[diffwitness]",
        f'test = "{escaped_test}"',
        "stability_runs = 2",
        "sufficient_search = true",
        "max_subset_order = 3",
        "max_subset_runs = 32",
        "interaction_search = true",
        "max_interaction_runs = 20",
    ]
    if prepare:
        escaped = prepare.replace("\\", "\\\\").replace('"', '\\"')
        lines.insert(2, f'prepare = "{escaped}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
