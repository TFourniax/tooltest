from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import (
    engine_config_source,
    load_project_config,
    remove_local_engine_profile,
    write_local_engine_profile,
)
from .engine_capabilities import EngineCapabilityError, inspect_engine_capabilities
from .gitops import GitError, repo_root


def _repo(value: str) -> Path:
    try:
        return repo_root(value)
    except GitError as exc:
        raise ValueError(str(exc)) from exc


def _status(repo: Path, *, explicit: str | None = None, as_json: bool = False) -> int:
    try:
        source, engine = engine_config_source(repo, explicit)
    except ValueError as exc:
        if as_json:
            print(json.dumps({"schema":"diffwitness.engine-status.v1","ok":False,"source":"invalid","error":str(exc)}, sort_keys=True))
        else:
            print(f"DiffWitness advisory engine: INVALID — {exc}")
        return 1

    if source == "community":
        payload = {
            "schema":"diffwitness.engine-status.v1",
            "ok":True,
            "source":"community",
            "required":False,
            "command":None,
            "engine":None,
        }
        if as_json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("DiffWitness advisory engine: Community planner only")
            print("Activate an installed private engine with: dw engine enable")
        return 0

    command = list(engine.get("command") or [])
    timeout = float(engine.get("timeout", 2.0))
    required = bool(engine.get("required", False))
    try:
        capabilities = inspect_engine_capabilities(cwd=repo, command=command, timeout=timeout)
    except EngineCapabilityError as exc:
        payload = {
            "schema":"diffwitness.engine-status.v1",
            "ok":False,
            "source":source,
            "required":required,
            "command":command,
            "engine":None,
            "error":str(exc),
        }
        if as_json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"DiffWitness advisory engine: INVALID ({source})")
            print(f"  {exc}")
        return 1

    payload = {
        "schema":"diffwitness.engine-status.v1",
        "ok":True,
        "source":source,
        "required":required,
        "command":command,
        "engine":capabilities["engine"],
        "protocol":capabilities["protocol"],
        "privacy":capabilities["privacy"],
        "authority":capabilities["authority"],
    }
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        info = capabilities["engine"]
        print(f"DiffWitness advisory engine: {info['name']} {info['version']} — compatible")
        print(f"  Source:    {source}")
        print(f"  Required:  {'yes' if required else 'no; Community fallback allowed'}")
        print("  Authority: advisory-only; evidence still executes in Community DiffWitness")
        print("  Privacy:   embedded source refused; metadata-only supported")
    return 0


def engine_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw engine",
        description="Manage the machine-local advisory engine without changing the repository's committed policy.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config", help="Optional project config used only for precedence/status checks")
    sub = parser.add_subparsers(dest="command_name")

    enable = sub.add_parser("enable", help="Preflight and activate an advisory engine in Git-local state")
    enable.add_argument("--command", default="dw-private-engine", help="Engine executable (default: dw-private-engine)")
    enable.add_argument("--arg", action="append", default=[], help="Additional fixed engine argv item; repeat as needed")
    enable.add_argument("--timeout", type=float, default=2.0)
    enable.add_argument(
        "--required",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail adaptive proof instead of silently falling back if this engine becomes unavailable (default: required)",
    )

    status = sub.add_parser("status", help="Show active engine source and run compatibility preflight")
    status.add_argument("--json", action="store_true")

    sub.add_parser("disable", help="Remove only the Git-local advisory-engine activation")
    args = parser.parse_args(argv)

    if not args.command_name:
        parser.print_help()
        return 0

    try:
        repo = _repo(args.repo)
    except ValueError as exc:
        parser.error(str(exc))

    if args.command_name == "status":
        return _status(repo, explicit=args.config, as_json=args.json)

    if args.command_name == "disable":
        removed = remove_local_engine_profile(repo)
        project = load_project_config(repo, args.config)
        if removed:
            print("✓ Removed the Git-local DiffWitness advisory-engine activation.")
        else:
            print("DiffWitness advisory engine: no Git-local activation was present.")
        if project.get("engine"):
            print("Project policy still defines [engine] in .diffwitness.toml; that engine remains active.")
        else:
            print("DiffWitness will use the Community planner unless --engine is supplied explicitly.")
        return 0

    project = load_project_config(repo, args.config)
    if project.get("engine"):
        parser.error(
            "this repository already defines [engine] in project config; local activation intentionally cannot override committed engine policy"
        )
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")
    command = [args.command, *args.arg]
    try:
        capabilities = inspect_engine_capabilities(cwd=repo, command=command, timeout=args.timeout)
    except EngineCapabilityError as exc:
        print(f"DiffWitness advisory engine activation refused: {exc}")
        return 1

    write_local_engine_profile(
        repo,
        {"command":command, "timeout":args.timeout, "required":bool(args.required)},
    )
    engine = capabilities["engine"]
    print(f"✓ Activated {engine['name']} {engine['version']} for this Git checkout.")
    print("  Stored under Git metadata, not in the software change or committed project config.")
    print(f"  Mode: {'required' if args.required else 'optional; Community fallback allowed'}")
    print("  Run `dw doctor` or `dw engine status` for a fresh compatibility preflight.")
    return 0
