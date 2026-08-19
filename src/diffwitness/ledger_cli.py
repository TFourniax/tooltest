from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import load_config
from .debt_budget import ledger_path, merged_debt_config
from .gitops import repo_root
from .ledger import DebtLedger, LedgerError
from .ledger_transport import (
    DEFAULT_LEDGER_REF,
    checkpoint_ledger,
    pull_checkpoint,
    push_checkpoint,
    read_checkpoint,
)


def _context(repo: Path, explicit_config: str | None) -> tuple[dict[str, Any], DebtLedger]:
    config = load_config(repo, explicit_config)
    debt_config = merged_debt_config(config.get("debt") or {})
    return debt_config, DebtLedger.load(ledger_path(repo, debt_config))


def _print_item(item: Any) -> None:
    print(
        f"{item.debt_id} {item.status}{' accepted' if item.accepted else ''} "
        f"+{item.points} {item.category}/{item.measurement} — {item.title}"
    )


def _portable_status(repo: Path, ledger: DebtLedger, ref: str) -> dict[str, Any]:
    checkpoint = read_checkpoint(repo=repo, ledger_path=ledger.path, ref=ref)
    return {
        "ledger": ledger.export_state(),
        "checkpoint_ref": ref,
        "checkpoint_present": checkpoint is not None,
        "checkpoint_events": len(checkpoint.events) if checkpoint is not None else 0,
        "checkpoint_last_hash": checkpoint.last_hash if checkpoint is not None else None,
        "checkpoint_relation": (
            "equal"
            if checkpoint is not None and checkpoint.events == ledger.events
            else "checkpoint-prefix"
            if checkpoint is not None and checkpoint.events == ledger.events[: len(checkpoint.events)]
            else "local-prefix"
            if checkpoint is not None and ledger.events == checkpoint.events[: len(ledger.events)]
            else "diverged"
            if checkpoint is not None
            else "missing"
        ),
    }


def ledger_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw ledger",
        description="Inspect, govern, checkpoint, and safely transport Debt Ledger obligations.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    sub = parser.add_subparsers(dest="action", required=True)

    listing = sub.add_parser("list", help="List active debt, or all historical items")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--json", action="store_true")

    history = sub.add_parser("history", help="Show append-only events for one debt identity")
    history.add_argument("debt_id")

    show = sub.add_parser("show", help="Explain one debt obligation, its provenance, and replay path")
    show.add_argument("debt_id")
    show.add_argument("--json", action="store_true")

    accept = sub.add_parser("accept", help="Acknowledge debt without deleting or resolving it")
    accept.add_argument("debt_id")
    accept.add_argument("--reason", required=True)

    unaccept = sub.add_parser("unaccept", help="Remove an explicit debt acceptance")
    unaccept.add_argument("debt_id")

    resolve = sub.add_parser("resolve", help="Manual last-resort resolution override")
    resolve.add_argument("debt_id")
    resolve.add_argument("--reason", required=True)
    resolve.add_argument(
        "--force",
        action="store_true",
        help="Explicit manual override; automatic resolution always requires verification",
    )

    status = sub.add_parser("status", help="Inspect local ledger and Git checkpoint relationship")
    status.add_argument("--ref", default=DEFAULT_LEDGER_REF)
    status.add_argument("--json", action="store_true")

    checkpoint = sub.add_parser("checkpoint", help="Store the current ledger on a local Git ref")
    checkpoint.add_argument("--ref", default=DEFAULT_LEDGER_REF)

    pull = sub.add_parser("pull", help="Fetch and fast-forward the ledger from a remote Git ref")
    pull.add_argument("--remote", default="origin")
    pull.add_argument("--ref", default=DEFAULT_LEDGER_REF)
    pull.add_argument(
        "--required",
        action="store_true",
        help="Fail if the remote checkpoint does not exist instead of treating first use as empty",
    )

    push = sub.add_parser("push", help="Checkpoint and push the ledger without force")
    push.add_argument("--remote", default="origin")
    push.add_argument("--ref", default=DEFAULT_LEDGER_REF)

    args = parser.parse_args(argv)
    repo = repo_root(args.repo)
    _, ledger = _context(repo, args.config)

    if args.action == "list":
        values = list(ledger.items().values()) if args.all else ledger.active_items()
        if args.json:
            print(json.dumps([item.to_dict() for item in values], indent=2, ensure_ascii=False))
        else:
            for item in sorted(
                values,
                key=lambda value: (value.status != "open", -value.points, value.debt_id),
            ):
                _print_item(item)
        return 0

    if args.action == "show":
        item = ledger.items().get(args.debt_id)
        if item is None:
            raise LedgerError(f"unknown debt id: {args.debt_id}")
        payload = {"item": item.to_dict(), "history": ledger.history(args.debt_id)}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            location = item.path or "project"
            if item.line:
                location += f":{item.line}"
            print(f"{item.debt_id} — {item.title}")
            print(f"Status:      {item.status}{' (accepted)' if item.accepted else ''}")
            print(f"Debt:        +{item.points} {item.category}/{item.measurement}")
            print(f"Location:    {location}")
            print(f"Why open:    {item.explanation}")
            if item.introduced_by:
                print("Introduced:  " + json.dumps(item.introduced_by, sort_keys=True, ensure_ascii=False))
            print("Verification: " + json.dumps(item.verification, sort_keys=True, ensure_ascii=False))
            if item.accepted_reason:
                print(f"Accepted because: {item.accepted_reason}")
            print(f"History:     {len(payload['history'])} event(s)")
            print(f"Next action: run `dw recheck {item.debt_id}` or include it in `dw repay`.")
        return 0

    if args.action == "history":
        print(json.dumps(ledger.history(args.debt_id), indent=2, ensure_ascii=False))
        return 0

    if args.action == "accept":
        ledger.accept(args.debt_id, reason=args.reason)
        print(f"Accepted {args.debt_id}: {args.reason}")
        return 0

    if args.action == "unaccept":
        ledger.unaccept(args.debt_id)
        print(f"Unaccepted {args.debt_id}")
        return 0

    if args.action == "resolve":
        if not args.force:
            raise LedgerError("manual resolution requires --force; prefer `dw recheck` for evidence-backed closure")
        ledger.resolve(
            args.debt_id,
            reason=args.reason,
            verification={"type": "manual-override"},
            actor="user",
            force=True,
        )
        print(f"Manually resolved {args.debt_id}")
        return 0

    if args.action == "status":
        payload = _portable_status(repo, ledger, args.ref)
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"Ledger:      {ledger.path}")
            print(f"Events:      {len(ledger.events)}")
            print(f"Active debt: {ledger.active_points()}")
            print(f"Last hash:   {ledger.last_hash or 'none'}")
            print(f"Checkpoint:  {args.ref}")
            print(f"Relation:    {payload['checkpoint_relation']}")
        return 0 if payload["checkpoint_relation"] != "diverged" else 1

    if args.action == "checkpoint":
        commit = checkpoint_ledger(repo=repo, ledger=ledger, ref=args.ref)
        print(f"Debt Ledger checkpointed: {args.ref} @ {commit[:12]} ({len(ledger.events)} events)")
        return 0

    if args.action == "pull":
        result = pull_checkpoint(
            repo=repo,
            ledger=ledger,
            remote=args.remote,
            ref=args.ref,
            missing_ok=not args.required,
        )
        if result == "missing":
            print(f"Debt Ledger checkpoint not found on {args.remote}; starting from local/empty ledger.")
        else:
            print(
                f"Debt Ledger pull: {result} — {len(ledger.events)} event(s), "
                f"last hash {ledger.last_hash or 'none'}"
            )
        return 0

    if args.action == "push":
        result = push_checkpoint(repo=repo, ledger=ledger, remote=args.remote, ref=args.ref)
        print(f"Debt Ledger pushed to {args.remote}:{args.ref} ({result})")
        return 0

    return 2
