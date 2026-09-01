from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .gitops import repo_root

VIEW_MODES = ("guided", "technical")
DEFAULT_VIEW_MODE = "technical"


def _preference_path(repo: Path) -> Path:
    return repo / ".git" / "diffwitness" / "ui-preferences.json"


def normalize_view_mode(value: str | None, *, default: str = DEFAULT_VIEW_MODE) -> str:
    raw = (value or "").strip().lower()
    return raw if raw in VIEW_MODES else default


def get_view_mode(repo: Path) -> str:
    override = os.environ.get("DIFFWITNESS_VIEW")
    if override:
        return normalize_view_mode(override)
    path = _preference_path(repo)
    if not path.exists():
        return DEFAULT_VIEW_MODE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_VIEW_MODE
    if not isinstance(payload, dict):
        return DEFAULT_VIEW_MODE
    return normalize_view_mode(payload.get("view"))


def set_view_mode(repo: Path, mode: str) -> str:
    normalized = normalize_view_mode(mode, default="")
    if normalized not in VIEW_MODES:
        raise ValueError(f"view must be one of: {', '.join(VIEW_MODES)}")
    path = _preference_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, object] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = dict(raw)
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing["schema"] = "diffwitness.ui-preferences.v1"
    existing["view"] = normalized
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return normalized


def view_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw view",
        description="Show or switch the local human-facing DiffWitness view without changing proof data.",
    )
    parser.add_argument("mode", nargs="?", choices=VIEW_MODES)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    mode = set_view_mode(repo, args.mode) if args.mode else get_view_mode(repo)
    if args.json:
        print(json.dumps({"schema": "diffwitness.view.v1", "view": mode}, indent=2))
        return 0
    if args.mode:
        other = "technical" if mode == "guided" else "guided"
        print(f"DiffWitness view: {mode} (saved for this repository)")
        print(f"Switch anytime with `dw view {other}`. Proof, debt, and JSON contracts are unchanged.")
    else:
        print(f"DiffWitness view: {mode}")
        print("Available views: guided, technical")
    return 0


__all__ = [
    "DEFAULT_VIEW_MODE",
    "VIEW_MODES",
    "get_view_mode",
    "normalize_view_mode",
    "set_view_mode",
    "view_cli",
]
