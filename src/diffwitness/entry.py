from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .config import load_config
from .diffing import make_mutations, parse_file_patches
from .gitops import diff_text, repo_root, resolve_ref, snapshot_worktree
from .proof_cli import main as proof_main


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


def _write_github_noop(report: dict[str, Any]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"certificate_id={report['certificate_id']}\n")
            handle.write("contrast=not-applicable\n")
            handle.write("witnessed=0\n")
            handle.write("unwitnessed=0\n")
            handle.write("inconclusive=0\n")
            handle.write("witness_ratio=\n")
            handle.write("minimal_sufficient_order=\n")
            handle.write("surplus_candidate_hunks=0\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("## DiffWitness — proof not required\n\n")
            handle.write(
                "No executable causal mutation remained after test/documentation/ignore filtering. "
                "DiffWitness intentionally did not manufacture a test-based proof for this change.\n\n"
            )
            handle.write(f"Certificate: `{report['certificate_id']}`\n")


def _write_noop_artifacts(args: list[str], report: dict[str, Any]) -> None:
    json_path = _value(args, "--certificate") or _value(args, "--json")
    if json_path:
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path = _value(args, "--report")
    if markdown_path:
        path = Path(markdown_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        changed = "\n".join(f"- `{item}`" for item in report["changed_files"]) or "- none"
        path.write_text(
            "# DiffWitness — proof not required\n\n"
            "No executable causal mutation remained after filtering. DiffWitness deliberately "
            "does not turn unrelated green tests into a causal claim.\n\n"
            f"Certificate: `{report['certificate_id']}`\n\n"
            "## Changed files\n\n"
            f"{changed}\n",
            encoding="utf-8",
        )


def _noop_prove_if_applicable(args: list[str]) -> int | None:
    # If the caller explicitly asks to analyze tests themselves, let the full engine decide.
    if "--include-test-changes" in args:
        return None

    repo = repo_root(_value(args, "--repo", ".") or ".")
    base_ref = _value(args, "--base", "HEAD") or "HEAD"
    candidate_ref = _value(args, "--candidate", "WORKTREE") or "WORKTREE"
    base_sha = resolve_ref(repo, base_ref)
    candidate_sha = (
        snapshot_worktree(repo)
        if candidate_ref.upper() == "WORKTREE"
        else resolve_ref(repo, candidate_ref)
    )

    config = load_config(repo, _value(args, "--config"))
    test_globs = _values(args, "--test-glob") or list(config.get("test_glob", []) or [])
    ignore = _values(args, "--ignore") or list(config.get("ignore", []) or [])
    files = parse_file_patches(diff_text(repo, base_sha, candidate_sha), test_globs=test_globs)
    mutations = make_mutations(files, ignore_globs=ignore)
    if mutations:
        return None

    changed_files = sorted(file.path for file in files)
    stable = json.dumps(
        {
            "base": base_sha,
            "candidate": candidate_sha,
            "changed_files": changed_files,
            "ignored": sorted(ignore),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    certificate_id = "dw0_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]
    report: dict[str, Any] = {
        "schema_version": "noop-1",
        "tool": "diffwitness",
        "certificate_id": certificate_id,
        "outcome": "proof-not-required",
        "reason": "no executable causal mutation remained after test/documentation/ignore filtering",
        "base": {"ref": base_ref, "sha": base_sha},
        "candidate": {"ref": candidate_ref, "sha": candidate_sha},
        "changed_files": changed_files,
        "summary": {
            "mutations": 0,
            "witnessed": 0,
            "unwitnessed": 0,
            "inconclusive": 0,
            "surplus_candidate_hunks": 0,
        },
        "non_claim": "No test-based causal claim was made because there was no executable production mutation to attribute.",
    }
    _write_noop_artifacts(args, report)

    github_mode = "--github-actions" in args or (
        "--no-github-actions" not in args and os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    )
    if github_mode:
        _write_github_noop(report)
    print(f"DiffWitness: proof not required ({certificate_id}); no executable causal mutation detected.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "prove":
        try:
            noop = _noop_prove_if_applicable(args[1:])
        except Exception:
            # The full parser/engine owns normal error reporting. The preflight must never mask it.
            noop = None
        if noop is not None:
            return noop
    return proof_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
