from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .autodetect import default_evidence, detect_evidence
from .cli import main as core_main
from .config import load_config
from .diffing import make_mutations, parse_file_patches
from .gitops import diff_text, repo_root, snapshot_worktree


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dw",
        description="DiffWitness Proof Guard: zero-friction causal validation around coding agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prove = sub.add_parser("prove", help="Run DiffWitness with automatic evidence discovery when possible")
    prove.add_argument("args", nargs=argparse.REMAINDER)

    guard = sub.add_parser("guard", help="Run any coding agent, then prove the patch it produced")
    guard.add_argument("--repo", default=".")
    guard.add_argument("--test", help="Evidence command; auto-detected when omitted")
    guard.add_argument("--policy", choices=["observe", "balanced", "strict"], default="balanced")
    guard.add_argument("--stability-runs", type=int, default=2)
    guard.add_argument("--certificate", type=Path)
    guard.add_argument("agent", nargs=argparse.REMAINDER, help="Agent command after --, e.g. -- claude")

    doctor = sub.add_parser("doctor", help="Explain zero-config evidence detection for this repository")
    doctor.add_argument("--repo", default=".")

    start = sub.add_parser("session-start", help=argparse.SUPPRESS)
    start.add_argument("--repo", default=".")
    start.add_argument("--session-id")

    stop = sub.add_parser("session-stop", help=argparse.SUPPRESS)
    stop.add_argument("--repo", default=".")
    stop.add_argument("--session-id")
    stop.add_argument("--policy", choices=["observe", "balanced", "strict"], default="balanced")
    return parser


def _repo_from_args(raw: list[str]) -> Path:
    for index, token in enumerate(raw):
        if token == "--repo" and index + 1 < len(raw):
            return repo_root(raw[index + 1])
        if token.startswith("--repo="):
            return repo_root(token.split("=", 1)[1])
    return repo_root(".")


def _inject_test(raw: list[str]) -> list[str]:
    if "--test" in raw or any(token.startswith("--test=") for token in raw):
        return raw
    repo = _repo_from_args(raw)
    config = load_config(repo, None)
    if config.get("test"):
        return raw
    plan = default_evidence(repo)
    if plan is None:
        raise RuntimeError(
            "No evidence command could be detected. Run `dw doctor`, pass --test, or create .diffwitness.toml."
        )
    print(f"DiffWitness autodetect: {plan.command} ({plan.reason})")
    return [*raw, "--test", plan.command]


def _policy_passes(report: dict[str, Any], policy: str) -> tuple[bool, str]:
    summary = report["summary"]
    if policy == "observe":
        return True, "observe policy never blocks"
    if summary.get("inconclusive", 0):
        return False, f"{summary['inconclusive']} hunk(s) have inconclusive evidence"
    if summary.get("surplus_candidate_hunks", 0):
        return False, f"{summary['surplus_candidate_hunks']} strong surplus candidate hunk(s) were found"
    if report.get("candidate_run", {}).get("classification") != "stable-pass":
        return False, "candidate is not stably green"
    if policy == "strict":
        if report.get("contrast") != "base-fail_candidate-pass":
            return False, "strict policy requires stable base-fail -> candidate-pass contrast"
        if summary.get("unwitnessed", 0):
            return False, f"strict policy rejects {summary['unwitnessed']} unwitnessed hunk(s)"
    return True, "proof policy satisfied"


def _run_proof(
    repo: Path,
    *,
    base: str,
    candidate: str,
    test: str,
    policy: str,
    stability_runs: int,
    certificate: Path | None,
    quiet: bool = False,
) -> tuple[int, dict[str, Any] | None, str]:
    temp_path: Path | None = None
    cert = certificate
    if cert is None:
        fd, raw = tempfile.mkstemp(prefix="diffwitness-", suffix=".json")
        os.close(fd)
        temp_path = Path(raw)
        cert = temp_path
    args = [
        "prove",
        "--repo",
        str(repo),
        "--base",
        base,
        "--candidate",
        candidate,
        "--test",
        test,
        "--stability-runs",
        str(stability_runs),
        "--certificate",
        str(cert),
    ]
    out = io.StringIO()
    err = io.StringIO()
    if quiet:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = core_main(args)
    else:
        rc = core_main(args)
    report = None
    if cert.exists():
        try:
            report = json.loads(cert.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = None
    details = (out.getvalue() + "\n" + err.getvalue()).strip()
    if temp_path is not None:
        try:
            temp_path.unlink()
        except OSError:
            pass
    if rc != 0:
        return rc, report, details or "DiffWitness core analysis failed"
    if report is None:
        return 2, None, details or "DiffWitness did not produce an evidence certificate"
    ok, reason = _policy_passes(report, policy)
    return (0 if ok else 1), report, reason if not details else f"{reason}\n{details}"


def _guard(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    command = list(args.agent)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise RuntimeError("guard requires an agent command, e.g. `dw guard -- claude` or `dw guard -- codex`")

    plan = default_evidence(repo) if not args.test else None
    test = args.test or (plan.command if plan else None)
    if not test:
        raise RuntimeError("No evidence command detected. Pass --test or run `dw doctor`.")

    baseline = snapshot_worktree(repo)
    print(f"DiffWitness Guard armed at {baseline[:12]}")
    print(f"Evidence: {test}")
    print(f"Policy:   {args.policy}")
    print()

    env = os.environ.copy()
    env["DIFFWITNESS_BASE"] = baseline
    proc = subprocess.run(command, cwd=repo, env=env)
    if proc.returncode != 0:
        print(f"DiffWitness Guard: agent exited with code {proc.returncode}; proof skipped.", file=sys.stderr)
        return proc.returncode

    candidate = snapshot_worktree(repo)
    if candidate == baseline:
        print("DiffWitness Guard: agent produced no repository change.")
        return 0
    files = parse_file_patches(diff_text(repo, baseline, candidate))
    mutations = make_mutations(files)
    if not mutations:
        print("DiffWitness Guard: no production-code mutation detected; nothing causal to prove.")
        return 0

    rc, report, reason = _run_proof(
        repo,
        base=baseline,
        candidate=candidate,
        test=test,
        policy=args.policy,
        stability_runs=args.stability_runs,
        certificate=args.certificate,
    )
    if rc == 0:
        cert_id = report.get("certificate_id") if report else "unknown"
        print(f"\nDiffWitness Guard: PROOF ACCEPTED ({cert_id})")
    else:
        print(f"\nDiffWitness Guard: PROOF REJECTED - {reason}", file=sys.stderr)
    return rc


def _doctor(args: argparse.Namespace) -> int:
    repo = repo_root(args.repo)
    plans = detect_evidence(repo)
    print(f"Repository: {repo}")
    if not plans:
        print("Evidence:   none detected")
        print("Action:     configure [diffwitness].test or pass --test")
        return 1
    print("Evidence candidates:")
    for index, plan in enumerate(plans, 1):
        default = "  <- default" if index == 1 else ""
        print(f"  {index}. {plan.command} [{plan.confidence}] - {plan.reason}{default}")
    print("\nAgent guard examples:")
    print("  dw guard -- claude")
    print("  dw guard -- codex")
    return 0


def _state_path(repo: Path, session_id: str) -> Path:
    digest = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:16]
    safe = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    root = Path(tempfile.gettempdir()) / "diffwitness-sessions" / digest
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{safe}.json"


def _hook_payload() -> dict[str, Any]:
    try:
        if sys.stdin.isatty():
            return {}
    except OSError:
        return {}
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}


def _session_start(args: argparse.Namespace) -> int:
    payload = _hook_payload()
    repo = repo_root(payload.get("cwd") or args.repo)
    session_id = str(payload.get("session_id") or args.session_id or "default")
    state = {"base": snapshot_worktree(repo), "retries": 0, "repo": str(repo)}
    _state_path(repo, session_id).write_text(json.dumps(state), encoding="utf-8")
    return 0


def _session_stop(args: argparse.Namespace) -> int:
    payload = _hook_payload()
    repo = repo_root(payload.get("cwd") or args.repo)
    session_id = str(payload.get("session_id") or args.session_id or "default")
    path = _state_path(repo, session_id)
    if not path.exists():
        print(json.dumps({"decision": "approve", "systemMessage": "DiffWitness was not armed at session start; use `dw guard` for guaranteed capture."}))
        return 0
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    base = state.get("base")
    if not base:
        print(json.dumps({"decision": "approve", "systemMessage": "DiffWitness session state is invalid; use `dw guard` for guaranteed capture."}))
        return 0

    candidate = snapshot_worktree(repo)
    if candidate == base:
        print(json.dumps({"decision": "approve", "systemMessage": "DiffWitness: no repository change to prove."}))
        return 0
    files = parse_file_patches(diff_text(repo, base, candidate))
    mutations = make_mutations(files)
    if not mutations:
        print(json.dumps({"decision": "approve", "systemMessage": "DiffWitness: no production-code mutation to prove."}))
        return 0

    plan = default_evidence(repo)
    config = load_config(repo, None)
    test = config.get("test") or (plan.command if plan else None)
    if not test:
        reason = "DiffWitness cannot find an evidence command. Add tests or configure [diffwitness].test before declaring the task complete."
        print(json.dumps({"decision": "block", "reason": reason, "systemMessage": reason}))
        return 0

    rc, report, reason = _run_proof(
        repo,
        base=base,
        candidate=candidate,
        test=str(test),
        policy=args.policy,
        stability_runs=int(config.get("stability_runs", 2)),
        certificate=None,
        quiet=True,
    )
    if rc == 0:
        cert_id = report.get("certificate_id") if report else "unknown"
        print(json.dumps({"decision": "approve", "systemMessage": f"DiffWitness proof accepted: {cert_id}"}))
        return 0

    retries = int(state.get("retries", 0)) + 1
    state["retries"] = retries
    path.write_text(json.dumps(state), encoding="utf-8")
    if retries > 3:
        msg = f"DiffWitness proof still fails after {retries - 1} continuation attempts: {reason}"
        print(json.dumps({"decision": "approve", "systemMessage": msg}))
        return 0
    feedback = (
        "DiffWitness rejected the current patch. Continue working until the proof passes. "
        f"Reason: {reason[-3000:]}"
    )
    print(json.dumps({"decision": "block", "reason": feedback, "systemMessage": feedback}))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "prove":
        try:
            return core_main(["prove", *_inject_test(argv[1:])])
        except RuntimeError as exc:
            print(f"DiffWitness: {exc}", file=sys.stderr)
            return 2
    args = _parser().parse_args(argv)
    try:
        if args.command == "guard":
            return _guard(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "session-start":
            return _session_start(args)
        if args.command == "session-stop":
            return _session_stop(args)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"DiffWitness: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
