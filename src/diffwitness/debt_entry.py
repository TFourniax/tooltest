from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .debt_budget import ledger_path, merged_debt_config
from .debt_certificate import validate_debt_certificate
from .debt_cli import debt_cli
from .gitops import repo_root, resolve_ref, snapshot_worktree


def debt_entry(argv: list[str]) -> int:
    """Validate a supplied proof certificate before it can affect debt accounting."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--config")
    parser.add_argument("--candidate", default="WORKTREE")
    parser.add_argument("--certificate", type=Path)
    known, _ = parser.parse_known_args(argv)
    if known.certificate is None:
        return debt_cli(argv)

    repo = repo_root(known.repo)
    config = load_config(repo, known.config)
    debt_config = merged_debt_config(config.get("debt") or {})
    ledger = ledger_path(repo, debt_config)
    exclusions: list[str] = []
    try:
        rel = ledger.resolve().relative_to(repo.resolve()).as_posix()
        if rel != ".git" and not rel.startswith(".git/"):
            exclusions.append(rel)
    except ValueError:
        pass
    candidate_sha = (
        snapshot_worktree(repo, exclude_paths=exclusions)
        if known.candidate.upper() == "WORKTREE"
        else resolve_ref(repo, known.candidate)
    )
    try:
        payload = json.loads(known.certificate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read proof certificate {known.certificate}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("proof certificate must be a JSON object")
    validate_debt_certificate(payload, repo=repo, candidate_sha=candidate_sha)
    return debt_cli(argv)
