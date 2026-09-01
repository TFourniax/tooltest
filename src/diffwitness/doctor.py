from __future__ import annotations

import argparse
from typing import Any

from .autodetect import detect_evidence
from .config import load_config
from .continuity_events import ContinuityError
from .continuity_state import state_status
from .engine_capabilities import EngineCapabilityError, inspect_engine_capabilities
from .engine_protocol import EngineProtocolError
from .gitops import GitError, repo_root
from .protect import ProtectError, protect_status


DEFAULT_ENGINE_TIMEOUT_SECONDS = 2.0


def doctor_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw doctor",
        description="Preflight evidence, optional runtime protection, advisory engine, and local project continuity without executing tests.",
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
                print(f"  {index}. {plan.command} [{plan.confidence}] - {plan.reason}{default}")
        else:
            print("Evidence:   none detected")
            print("Action:     configure [diffwitness].test or pass --test")

        protect_ok = True
        try:
            protection = protect_status(repo)
        except ProtectError as exc:
            protect_ok = False
            print(f"Protect:    INVALID - {exc}")
            print("Action:     inspect or reset local Protect state with `dw protect status` / `dw protect disable`")
        else:
            mode = protection.get("mode")
            health = protection.get("health")
            policy = protection.get("policy")
            receipts = protection.get("receipts") or {}
            if mode == "builtin":
                adapters = ", ".join(protection.get("adapters") or {}) or "none"
                print(f"Protect:    builtin - {health} · policy {policy} · adapters {adapters}")
                if health != "ready":
                    protect_ok = False
                    print("Action:     repair installed runtime hooks with `dw protect disable` then `dw protect enable`")
            elif mode == "external":
                print("Protect:    external - delegated; Proof/Debt remain DiffWitness-owned")
            else:
                print("Protect:    off - optional; Proof/Debt remain fully available")
            if receipts.get("integrity") is False:
                protect_ok = False
                print("Receipts:   INVALID - local protection receipt integrity check failed")
            elif int(receipts.get("count") or 0):
                print(f"Receipts:   {int(receipts.get('count') or 0)} bounded runtime observation(s); integrity ok")
            print("Boundary:   Protect observations never become VERIFIED software behavior without executable evidence")

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
                capabilities = inspect_engine_capabilities(cwd=repo, command=engine_command, timeout=engine_timeout)
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

        continuity_ok = True
        try:
            continuity = state_status(repo)
        except ContinuityError as exc:
            continuity_ok = False
            print(f"Continuity: INVALID - {exc}")
            print("Action:     repair/restore the append-only ProjectEvent journal before trusting project memory")
        else:
            event_count = int(continuity.get("event_count") or 0)
            if event_count == 0:
                print("Continuity: ready - no project memory recorded yet")
            else:
                current = bool(continuity.get("state_current"))
                print(
                    f"Continuity: {event_count} ProjectEvent(s); "
                    f"derived state {'current' if current else 'rebuild-on-demand'}"
                )
                counts = continuity.get("counts") or {}
                if counts:
                    print(
                        "Memory:     "
                        f"{counts.get('entities', 0)} entities / {counts.get('relations', 0)} relations / "
                        f"{counts.get('changes', 0)} changes / {counts.get('debts', 0)} debts"
                    )
            print("Context:    local + bounded + advisory; `dw context <task>`")
            print("Trust:      DECLARED/INFERRED/OBSERVED never auto-upgrade to VERIFIED")
            print("Privacy:    ProjectEvent and Protect history exclude raw prompts, raw diffs and raw commands")

        if evidence_ok:
            print("\nAgent workflow examples:")
            print("  dw protect enable                    # optional builtin live guard")
            print("  dw protect use external              # keep your existing harness")
            print("  dw guard --policy strict -- claude   # independent before/after proof boundary")
            print("  dw guard --policy strict -- codex")
            print("Claude/Codex plugins can inject task-specific Project Continuity at UserPromptSubmit.")
        return 0 if evidence_ok and protect_ok and engine_ok and continuity_ok else 1
    except (GitError, ValueError, OSError) as exc:
        print(f"DiffWitness doctor: {exc}")
        return 2


__all__ = ["doctor_cli"]
