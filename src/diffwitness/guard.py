from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .gate import gate_cli
from .gitops import diff_text, repo_root, snapshot_worktree


def guard_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dw guard",
        description="Run a coding agent inside a before/after DiffWitness proof boundary.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--test")
    parser.add_argument("--prepare")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--share", action="append", default=[])
    parser.add_argument("--test-glob", action="append", default=[])
    parser.add_argument("--ignore", action="append", default=[])
    parser.add_argument("--policy", choices=["observe", "balanced", "strict"], default="balanced")
    parser.add_argument("--strategy", choices=["auto", "exhaustive", "adaptive"], default="auto")
    parser.add_argument("--adaptive-threshold", type=int, default=16)
    parser.add_argument("--adaptive-budget", type=int, default=40)
    parser.add_argument("--stability-runs", type=int, default=2)
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("agent", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = list(args.agent)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("an agent command is required after -- (for example: dw guard -- claude)")

    repo = repo_root(args.repo)
    baseline = snapshot_worktree(repo)
    print(f"DiffWitness Guard armed at {baseline[:12]}")
    print(f"Agent:    {' '.join(command)}")
    print(f"Policy:   {args.policy}")
    print(f"Strategy: {args.strategy}")
    print()

    env = os.environ.copy()
    env["DIFFWITNESS_BASE"] = baseline
    try:
        proc = subprocess.run(command, cwd=repo, env=env)
    except FileNotFoundError as exc:
        print(f"DiffWitness Guard: cannot start agent command: {exc}", file=sys.stderr)
        return 127
    except OSError as exc:
        print(f"DiffWitness Guard: agent process failed to start: {exc}", file=sys.stderr)
        return 126

    if proc.returncode != 0:
        print(
            f"DiffWitness Guard: agent exited with code {proc.returncode}; proof was not attempted.",
            file=sys.stderr,
        )
        return proc.returncode

    candidate = snapshot_worktree(repo)
    if candidate == baseline:
        print("DiffWitness Guard: agent produced no repository change; proof not required.")
        return 0

    # This diagnostic is deliberately before Gate so a branch/commit-changing agent still has a
    # human-readable indication that the captured transaction is the exact before/after snapshot.
    if not diff_text(repo, baseline, candidate).strip():
        print("DiffWitness Guard: candidate tree is unchanged; proof not required.")
        return 0

    gate_args = [
        "--repo",
        str(repo),
        "--base",
        baseline,
        "--candidate",
        candidate,
        "--policy",
        args.policy,
        "--strategy",
        args.strategy,
        "--adaptive-threshold",
        str(args.adaptive_threshold),
        "--adaptive-budget",
        str(args.adaptive_budget),
        "--stability-runs",
        str(args.stability_runs),
        "--no-github-actions",
    ]
    if args.config:
        gate_args += ["--config", args.config]
    if args.test:
        gate_args += ["--test", args.test]
    if args.prepare:
        gate_args += ["--prepare", args.prepare]
    if args.timeout is not None:
        gate_args += ["--timeout", str(args.timeout)]
    for path in args.share:
        gate_args += ["--share", path]
    for pattern in args.test_glob:
        gate_args += ["--test-glob", pattern]
    for pattern in args.ignore:
        gate_args += ["--ignore", pattern]
    if args.certificate:
        gate_args += ["--certificate", str(args.certificate)]
    if args.report:
        gate_args += ["--report", str(args.report)]

    rc = gate_cli(gate_args)
    if rc == 0:
        print("\nDiffWitness Guard: PROOF ACCEPTED")
    else:
        print("\nDiffWitness Guard: PROOF REJECTED", file=sys.stderr)
    return rc
