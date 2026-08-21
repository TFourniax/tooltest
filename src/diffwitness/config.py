from __future__ import annotations

import json
import math
import os
import tomllib
from pathlib import Path
from typing import Any

from .debt_models import DEBT_CATEGORIES
from .gitops import git_result

DEFAULT_CONFIG = ".diffwitness.toml"
LOCAL_ENGINE_SCHEMA = "diffwitness.local-engine.v1"
MAX_LOCAL_ENGINE_BYTES = 16 * 1024
KNOWN_KEYS = {
    "test", "prepare", "timeout", "max_total_seconds", "stability_runs", "sufficient_search", "max_subset_order",
    "max_subset_runs", "interaction_search", "max_interaction_runs", "test_glob", "ignore", "share",
    "test_overlay", "policy", "strategy", "adaptive_threshold", "adaptive_budget", "debt", "engine",
}
DEBT_KEYS = {
    "ledger", "max_total", "max_per_change", "category_limits", "duplicate_scan", "max_scan_files",
    "max_duplicate_signals", "auto_record", *DEBT_CATEGORIES,
}
ENGINE_KEYS = {"command", "timeout", "required"}


def _positive_int(section: dict[str, Any], key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"DiffWitness config `{key}` must be a positive integer")


def _positive_number(section: dict[str, Any], key: str) -> None:
    if key not in section:
        return
    value = section[key]
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError(f"DiffWitness config `{key}` must be a finite positive number")


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


def validate_engine_config(section: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(section) - ENGINE_KEYS)
    if unknown:
        raise ValueError(
            "Unknown DiffWitness engine config key(s): " + ", ".join(unknown)
            + ". Failing rather than silently changing advisory-engine semantics."
        )
    normalized = dict(section)
    command = normalized.get("command")
    if command is not None:
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) or not item.strip() for item in command)
        ):
            raise ValueError("DiffWitness config `engine.command` must be a non-empty array of non-empty strings")
        normalized["command"] = list(command)
    if "timeout" in normalized:
        _positive_number(normalized, "timeout")
    _bool(normalized, "required", prefix="engine.")
    if normalized.get("required") and not normalized.get("command"):
        raise ValueError("DiffWitness config `engine.required = true` requires `engine.command`")
    return normalized


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
    for key in ("timeout", "max_total_seconds"):
        _positive_number(section, key)
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
    if "engine" in normalized:
        if not isinstance(normalized["engine"], dict):
            raise ValueError("DiffWitness config `engine` must be a table")
        normalized["engine"] = validate_engine_config(dict(normalized["engine"]))
    return normalized


def _extract_sections(data: dict[str, Any]) -> dict[str, Any]:
    if "diffwitness" in data:
        raw = data["diffwitness"]
        if not isinstance(raw, dict):
            raise ValueError("DiffWitness config must contain a [diffwitness] table")
        section = dict(raw)
    else:
        section = {key: value for key, value in data.items() if key not in {"debt", "engine"}}

    top_debt = data.get("debt")
    nested_debt = section.get("debt")
    if top_debt is not None and nested_debt is not None:
        raise ValueError("configure debt either as [debt] or [diffwitness.debt], not both")
    debt = nested_debt if nested_debt is not None else top_debt
    if debt is not None:
        if not isinstance(debt, dict):
            raise ValueError("DiffWitness debt config must be a table")
        section["debt"] = dict(debt)

    top_engine = data.get("engine")
    nested_engine = section.get("engine")
    if top_engine is not None and nested_engine is not None:
        raise ValueError("configure engine either as [engine] or [diffwitness.engine], not both")
    engine = nested_engine if nested_engine is not None else top_engine
    if engine is not None:
        if not isinstance(engine, dict):
            raise ValueError("DiffWitness engine config must be a table")
        section["engine"] = dict(engine)
    return section


def load_project_config(repo: Path, explicit: str | None = None) -> dict[str, Any]:
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


def local_engine_profile_path(repo: Path) -> Path | None:
    proc = git_result(repo, "rev-parse", "--git-path", "diffwitness/engine.json")
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def _strict_json_loads(text: str) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    return json.loads(
        text,
        object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON number: {value}")),
    )


def load_local_engine_profile(repo: Path) -> dict[str, Any] | None:
    path = local_engine_profile_path(repo)
    if path is None or not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read local DiffWitness engine profile: {exc}") from exc
    if len(raw) > MAX_LOCAL_ENGINE_BYTES:
        raise ValueError("Local DiffWitness engine profile exceeds 16 KiB")
    try:
        parsed = _strict_json_loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Local DiffWitness engine profile is invalid: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Local DiffWitness engine profile root must be a JSON object")
    unknown = sorted(set(parsed) - {"schema", "engine"})
    if unknown:
        raise ValueError("Unknown local DiffWitness engine profile field(s): " + ", ".join(unknown))
    if parsed.get("schema") != LOCAL_ENGINE_SCHEMA:
        raise ValueError("Unsupported local DiffWitness engine profile schema")
    engine = parsed.get("engine")
    if not isinstance(engine, dict):
        raise ValueError("Local DiffWitness engine profile must contain an engine object")
    return validate_engine_config(dict(engine))


def write_local_engine_profile(repo: Path, engine: dict[str, Any]) -> Path:
    normalized = validate_engine_config(dict(engine))
    if not normalized.get("command"):
        raise ValueError("Local DiffWitness engine profile requires engine.command")
    path = local_engine_profile_path(repo)
    if path is None:
        raise ValueError("Local engine profiles require a Git repository")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": LOCAL_ENGINE_SCHEMA, "engine": normalized}
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        os.replace(temp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    return path


def remove_local_engine_profile(repo: Path) -> bool:
    path = local_engine_profile_path(repo)
    if path is None or not path.exists():
        return False
    path.unlink()
    return True


def engine_config_source(repo: Path, explicit: str | None = None) -> tuple[str, dict[str, Any]]:
    project = load_project_config(repo, explicit)
    if project.get("engine"):
        return "project", dict(project["engine"])
    local = load_local_engine_profile(repo)
    if local:
        return "local", local
    return "community", {}


def load_config(repo: Path, explicit: str | None = None) -> dict[str, Any]:
    project = load_project_config(repo, explicit)
    if project.get("engine"):
        return project
    local = load_local_engine_profile(repo)
    if not local:
        return project
    merged = dict(project)
    merged["engine"] = local
    return merged


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
        "timeout = 300", "max_total_seconds = 900", "adaptive_threshold = 16", "adaptive_budget = 40",
        "stability_runs = 2", "sufficient_search = true", "max_subset_order = 3", "max_subset_runs = 32",
        "interaction_search = true", "max_interaction_runs = 20", "test_overlay = true", "", "[debt]",
        'ledger = ".git/diffwitness/debt-ledger.jsonl"', "auto_record = true", "duplicate_scan = true",
        "max_scan_files = 500", "max_duplicate_signals = 20",
    ]
    if prepare:
        lines.insert(2, f"prepare = {_toml_string(prepare)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
