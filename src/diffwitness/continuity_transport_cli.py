from __future__ import annotations

import argparse

from .continuity_state import ensure_state
from .continuity_transport import (
    DEFAULT_CONTINUITY_REF,
    checkpoint_events,
    pull_checkpoint,
    push_checkpoint,
    restore_checkpoint,
)
from .gitops import repo_root


def state_transport_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw state",
        description="Checkpoint and transport the append-only ProjectEvent history without touching HEAD.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    checkpoint = sub.add_parser("checkpoint", help="store current ProjectEvents on an isolated local Git ref")
    checkpoint.add_argument("--repo", default=".")
    checkpoint.add_argument("--ref", default=DEFAULT_CONTINUITY_REF)

    restore = sub.add_parser("restore", help="fast-forward local ProjectEvents from a local checkpoint ref")
    restore.add_argument("--repo", default=".")
    restore.add_argument("--ref", default=DEFAULT_CONTINUITY_REF)
    restore.add_argument("--missing-ok", action="store_true")

    pull = sub.add_parser("pull", help="fetch and fast-forward ProjectEvents from a remote checkpoint")
    pull.add_argument("--repo", default=".")
    pull.add_argument("--remote", default="origin")
    pull.add_argument("--ref", default=DEFAULT_CONTINUITY_REF)
    pull.add_argument("--missing-ok", action=argparse.BooleanOptionalAction, default=True)

    push = sub.add_parser("push", help="checkpoint and push ProjectEvents without force")
    push.add_argument("--repo", default=".")
    push.add_argument("--remote", default="origin")
    push.add_argument("--ref", default=DEFAULT_CONTINUITY_REF)

    args = parser.parse_args(argv)
    repo = repo_root(args.repo)

    if args.command == "checkpoint":
        commit = checkpoint_events(repo=repo, ref=args.ref)
        print(f"Project continuity checkpoint: {commit}")
        print(f"Ref: {args.ref}")
        return 0
    if args.command == "restore":
        status = restore_checkpoint(repo=repo, ref=args.ref, missing_ok=bool(args.missing_ok))
        if status == "restored":
            ensure_state(repo)
        print(f"Project continuity restore: {status}")
        return 0
    if args.command == "pull":
        status = pull_checkpoint(
            repo=repo,
            remote=args.remote,
            ref=args.ref,
            missing_ok=bool(args.missing_ok),
        )
        if status == "restored":
            ensure_state(repo)
        print(f"Project continuity pull: {status}")
        return 0
    if args.command == "push":
        result = push_checkpoint(repo=repo, remote=args.remote, ref=args.ref)
        print("Project continuity push: complete")
        if result:
            print(result)
        return 0
    return 2


__all__ = ["state_transport_cli"]
