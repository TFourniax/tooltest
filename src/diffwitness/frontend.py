from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .autodetect import default_evidence
from .config import load_config
from .diffing import make_mutations, parse_file_patches
from .gitops import GitError, diff_text, git, repo_root, resolve_ref, snapshot_worktree
from .ledger import LedgerError
from .proof_cli import main as proof_main
from .validation import build_validation_only, render_validation_markdown


TOP_HELP = """DiffWitness Proof + Debt Layer

Usage:
  dw guard [options] -- <agent>      Explicit fallback: run an agent inside a proof boundary
  dw gate [options]                  Validate an existing Git diff / pull request
  dw prove [options]                 Exhaustive hunk-level counterfactual evidence
  dw core [options]                  Budgeted Adaptive Core / 1-minimal reduction search
  dw debt [options]                  Measure and record debt introduced by a change
  dw health [options]                Scan current project debt and reconcile the Debt Ledger
  dw plan [options]                  Build an automatically verifiable debt-repayment plan
  dw repay [options] -- <agent>      Run a constrained repayment mission, verify, and re-measure
  dw recheck <DW-...> [options]      Replay verification for historical debt lineages
  dw ledger <action> [options]       Inspect, govern, checkpoint, and transport the Debt Ledger
  dw envelope [options]              Bind Proof + Debt + IdleProof to one exact Git change
  dw verify <certificate> [options]  Verify certificate integrity and freshness
  dw note <certificate> [options]    Attach a verified proof reference using git notes
  dw doctor [options]                Explain zero-config evidence discovery

Start here:
  dw setup                         Connect a detected Claude/Codex/Cursor provider
  dw status                        Show readiness and the next truthful action

Explicit process-boundary fallback:
  dw guard -- claude
  dw debt --base HEAD --candidate WORKTREE
  dw health
  dw plan
  dw repay -- claude

Use `dw <command> --help` for command-specific options.
"""


class FrontendError(RuntimeError):
    pass


def _value(args: list[str], name: str, default: str | None = None) -> str | None:
    for index, token in enumerate(args):
        if token == name and index + 1 < len(args):
            return args[index + 1]
        prefix = name + "="
        if token.startswith(prefix):
            return token[len(prefix) :]
    return default


def _values(args: list[str], name: str) -> list[str]:
    values: list[str] = []
    for index, token in enumerate(args):
        if token == name and index + 1 < len(args):
            values.append(args[index + 1])
        elif token.startswith(name + "="):
            values.append(token.split("=", 1)[1])
    return values


def _tree(repo: Path, sha: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{sha}^{{tree}}").strip()


def _github_mode(args: list[str]) -> bool:
    return "--github-actions" in args or (
        "--no-github-actions" not in args
        and os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    )


def _config(repo: Path, args: list[str]) -> dict[str, Any]:
    return load_config(repo, _value(args, "--config"))


def _inject_explicit_config_test(args: list[str]) -> list[str]:
    if _value(args, "--test"):
        return args
    repo = repo_root(_value(args, "--repo", ".") or ".")
    explicit = _value(args, "--config")
    if not explicit:
        return args
    config = load_config(repo, explicit)
    test = config.get("test")
    if isinstance(test, str) and test.strip():
        return [*args, "--test", test]
    return args


def _resolve_nonproduction_evidence(
    repo: Path, args: list[str], config: dict[str, Any]
) -> str:
    explicit = _value(args, "--test")
    if explicit:
        return explicit
    configured = config.get("test")
    if isinstance(configured, str) and configured.strip():
        return configured
    plan = default_evidence(repo)
    if plan is None:
        raise FrontendError(
            "this change contains tests but DiffWitness cannot determine how to execute evidence. "
            "Failing closed: pass --test or configure [diffwitness].test."
        )
    return plan.command


def _write_common_outputs(report: dict[str, Any], *, proof_mode: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    summary = report.get("summary") or {}
    with Path(output).open("a", encoding="utf-8") as handle:
        handle.write(f"certificate_id={report['certificate_id']}\n")
        handle.write("contrast=not-applicable\n")
        handle.write(f"witnessed={summary.get('witnessed', 0)}\n")
        handle.write(f"unwitnessed={summary.get('unwitnessed', 0)}\n")
        handle.write(f"inconclusive={summary.get('inconclusive', 0)}\n")
        handle.write("witness_ratio=\n")
        handle.write("minimal_sufficient_order=\n")
        handle.write(f"surplus_candidate_hunks={summary.get('surplus_candidate_hunks', 0)}\n")
        handle.write(f"proof_mode={proof_mode}\n")


def _write_json(args: list[str], report: dict[str, Any]) -> None:
    raw = _value(args, "--certificate") or _value(args, "--json")
    if not raw:
        return
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_markdown(args: list[str], markdown: str) -> None:
    raw = _value(args, "--report")
    if not raw:
        return
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def _preflight_nonproduction(args: list[str]) -> int | None:
    """Handle non-production diffs before Gate/Prove.

    This function is intentionally fail-closed. An inability to determine how changed tests should
    be executed raises FrontendError and MUST NOT fall back to a successful no-mutation Gate.
    """
    if "--include-test-changes" in args:
        return None

    repo = repo_root(_value(args, "--repo", ".") or ".")
    config = _config(repo, args)
    base_ref = _value(args, "--base", "HEAD") or "HEAD"
    candidate_ref = _value(args, "--candidate", "WORKTREE") or "WORKTREE"
    base_sha = resolve_ref(repo, base_ref)
    candidate_sha = (
        snapshot_worktree(repo)
        if candidate_ref.upper() == "WORKTREE"
        else resolve_ref(repo, candidate_ref)
    )
    test_globs = _values(args, "--test-glob") or list(config.get("test_glob", []) or [])
    ignore = _values(args, "--ignore") or list(config.get("ignore", []) or [])
    files = parse_file_patches(
        diff_text(repo, base_sha, candidate_sha), test_globs=test_globs
    )
    if make_mutations(files, ignore_globs=ignore):
        return None

    test_files = sorted(file.path for file in files if file.is_test)
    if test_files:
        test_command = _resolve_nonproduction_evidence(repo, args, config)
        prepare = _value(args, "--prepare") or config.get("prepare")
        timeout_raw: Any = _value(args, "--timeout")
        timeout = float(timeout_raw if timeout_raw is not None else config.get("timeout", 300.0))
        stability_raw: Any = _value(args, "--stability-runs")
        stability_runs = int(
            stability_raw if stability_raw is not None else config.get("stability_runs", 2)
        )
        shared = _values(args, "--share") or list(config.get("share", []) or [])
        report = build_validation_only(
            source_repo=repo,
            base_sha=base_sha,
            candidate_sha=candidate_sha,
            candidate_ref=candidate_ref,
            test_command=test_command,
            test_files=test_files,
            stability_runs=stability_runs,
            timeout=timeout,
            prepare_command=str(prepare) if prepare else None,
            shared_paths=shared,
        )
        _write_json(args, report)
        markdown = render_validation_markdown(report)
        _write_markdown(args, markdown)
        if _github_mode(args):
            _write_common_outputs(report, proof_mode="validation-only")
            summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary_path:
                with Path(summary_path).open("a", encoding="utf-8") as handle:
                    handle.write(markdown)
                    handle.write("\n")
            if not report.get("valid"):
                classification = report.get("candidate_run", {}).get("classification", "unknown")
                print(
                    "::error title=DiffWitness test-only validation::"
                    f"Changed tests are {classification} on the candidate"
                )
        print(
            f"DiffWitness: validation-only {report['candidate_run']['classification']} "
            f"({report['certificate_id']})"
        )
        return 0 if report.get("valid") else 1

    changed_files = sorted(file.path for file in files)
    base_tree = _tree(repo, base_sha)
    candidate_tree = _tree(repo, candidate_sha)
    stable = {
        "base": base_sha,
        "candidate": candidate_sha,
        "base_tree": base_tree,
        "candidate_tree": candidate_tree,
        "changed_files": changed_files,
        "ignored": sorted(ignore),
    }
    encoded = json.dumps(
        stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    certificate_id = "dw0_" + hashlib.sha256(encoded).hexdigest()[:20]
    report: dict[str, Any] = {
        "schema_version": "noop-1",
        "tool": "diffwitness",
        "certificate_id": certificate_id,
        "outcome": "proof-not-required",
        "reason": "no executable causal mutation remained after test/documentation/ignore filtering",
        "base": {"ref": base_ref, "sha": base_sha, "tree": base_tree},
        "candidate": {
            "ref": candidate_ref,
            "sha": candidate_sha,
            "tree": candidate_tree,
        },
        "changed_files": changed_files,
        "ignored": sorted(ignore),
        "summary": {
            "mutations": 0,
            "witnessed": 0,
            "unwitnessed": 0,
            "inconclusive": 0,
            "surplus_candidate_hunks": 0,
        },
        "non_claim": "No test-based causal claim was made because there was no executable production mutation to attribute.",
    }
    _write_json(args, report)
    changed = "\n".join(f"- `{item}`" for item in changed_files) or "- none"
    markdown = (
        "# DiffWitness — proof not required\n\n"
        "No executable causal mutation remained after filtering. DiffWitness deliberately does "
        "not turn unrelated green tests into a causal claim.\n\n"
        f"Certificate: `{certificate_id}`\n\n"
        "## Changed files\n\n"
        f"{changed}\n"
    )
    _write_markdown(args, markdown)
    if _github_mode(args):
        _write_common_outputs(report, proof_mode="not-required")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as handle:
                handle.write(markdown)
                handle.write("\n")
    print(
        f"DiffWitness: proof not required ({certificate_id}); "
        "no executable causal mutation detected."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(TOP_HELP)
        return 0
    if args[0] in {"-V", "--version"}:
        print(f"diffwitness {__version__}")
        return 0

    try:
        if args[0] == "verify":
            from .attestation import verify_cli

            return verify_cli(args[1:])
        if args[0] == "note":
            from .attestation import note_cli

            return note_cli(args[1:])
        if args[0] == "envelope":
            from .change_envelope import envelope_cli

            return envelope_cli(args[1:])
        if args[0] in {"debt", "health", "plan", "repay", "recheck", "ledger"}:
            from .debt_cli import health_cli, plan_cli, recheck_cli, repay_cli
            from .debt_entry import debt_entry
            from .ledger_cli import ledger_cli

            handlers = {
                "debt": debt_entry,
                "health": health_cli,
                "plan": plan_cli,
                "repay": repay_cli,
                "recheck": recheck_cli,
                "ledger": ledger_cli,
            }
            return handlers[args[0]](args[1:])
        if args[0] == "guard":
            from .guard import guard_cli

            return guard_cli(_inject_explicit_config_test(args[1:]))
        if args[0] in {"prove", "gate"}:
            prepared = (
                _inject_explicit_config_test(args[1:]) if args[0] == "gate" else args[1:]
            )
            preflight = _preflight_nonproduction(prepared)
            if preflight is not None:
                return preflight
        else:
            prepared = args[1:]
        if args[0] == "gate":
            from .gate import gate_cli

            return gate_cli(prepared)
        return proof_main(args)
    except (FrontendError, GitError, LedgerError, ValueError, OSError) as exc:
        print(f"DiffWitness: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
