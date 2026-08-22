from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .autodetect import detect_evidence
from .config import load_config
from .engine_capabilities import EngineCapabilityError, inspect_engine_capabilities
from .engine_protocol import EngineProtocolError
from .gitops import GitError, repo_root


DEFAULT_ENGINE_TIMEOUT_SECONDS = 2.0


def doctor_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw doctor",
        description="Preflight evidence discovery and an optional advisory engine without executing project tests.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument(
        "--engine",
        help="Optional advisory engine executable; overrides configured engine.command for this preflight",
    )
    parser.add_argument("--engine-timeout", type=float, default=None)
    args = parser.parse_args(argv)

    try:
        repo = repo_root(args.repo)
        config = load_config(repo, args.config)
        configured_test = config.get("test")
        plans = detect_evidence(repo)

        print(f"Repository: {repo}")
        evidence_ok = False
        if isinstance(configured_test, str) and configured_test.strip():
            evidence_ok = True
            print(f"Evidence:   configured - {configured_test}")
        elif plans:
            evidence_ok = True
            print("Evidence candidates:")
            for index, plan in enumerate(plans, 1):
                default = "  <- default" if index == 1 else ""
                print(
                    f"  {index}. {plan.command} [{plan.confidence}] - {plan.reason}{default}"
                )
        else:
            print("Evidence:   none detected")
            print("Action:     configure [diffwitness].test or pass --test")

        engine_config: dict[str, Any] = dict(config.get("engine") or {})
        engine_command = [args.engine] if args.engine else list(engine_config.get("command") or [])
        engine_timeout = float(
            args.engine_timeout
            if args.engine_timeout is not None
            else engine_config.get("timeout", DEFAULT_ENGINE_TIMEOUT_SECONDS)
        )
        engine_ok = True
        if not engine_command:
            print("Advisory:   Community planner only (no external engine configured)")
        else:
            try:
                capabilities = inspect_engine_capabilities(
                    cwd=repo,
                    command=engine_command,
                    timeout=engine_timeout,
                )
            except (EngineCapabilityError, EngineProtocolError) as exc:
                engine_ok = False
                print(f"Advisory:   INVALID - {exc}")
                if engine_config.get("required"):
                    print("Action:     required advisory engine must pass preflight before Gate can run")
                else:
                    print("Action:     fix or remove the configured advisory engine before relying on it")
            else:
                engine = capabilities["engine"]
                limits = capabilities["limits"]
                privacy = capabilities["privacy"]
                print(
                    f"Advisory:   compatible - {engine['name']} {engine['version']} "
                    f"({capabilities['protocol']['request']} -> {capabilities['protocol']['plan']})"
                )
                print(
                    "Boundary:   advisory-only; no evidence execution; no repository writes; "
                    "embedded source refused"
                )
                print(
                    f"Capacity:   {limits.get('mutations', '?')} mutations; "
                    f"{limits.get('request_bytes', '?')} request bytes; "
                    f"metadata-only={'yes' if privacy.get('supports_metadata_only') else 'no'}"
                )

        if evidence_ok:
            print("\nAgent guard examples:")
            print("  dw guard -- claude")
            print("  dw guard -- codex")
        return 0 if evidence_ok and engine_ok else 1
    except (GitError, ValueError, OSError) as exc:
        print(f"DiffWitness doctor: {exc}")
        return 2


__all__ = ["doctor_cli"]
