from __future__ import annotations

import argparse
import json
from pathlib import Path

from .continuity_context_enriched import compile_context, render_context
from .gitops import repo_root


def context_command_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw context",
        description="Compile bounded local project continuity context for a human or coding agent.",
    )
    parser.add_argument("task", nargs="+")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--max-items", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--refresh-structure", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    task = " ".join(args.task).strip()
    if not task:
        parser.error("task cannot be empty")
    context = compile_context(
        args.repo,
        task,
        max_items=max(1, min(args.max_items, 50)),
        refresh_structure=bool(args.refresh_structure),
    )
    output = (
        json.dumps(context, indent=2, ensure_ascii=False) + "\n"
        if args.json
        else render_context(context, max_chars=max(1000, args.max_chars))
    )
    if args.out:
        out = args.out if args.out.is_absolute() else repo_root(args.repo) / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output, encoding="utf-8")
        print(f"Context: {out}")
    else:
        print(output, end="")
    return 0


__all__ = ["context_command_cli"]
