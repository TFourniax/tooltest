from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .gitops import git
from .ledger import DebtLedger, LedgerError

DEFAULT_LEDGER_REF = "refs/diffwitness/debt-ledger"
LEDGER_OBJECT_PATH = "ledger.jsonl"


def _serialize(events: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n" for event in events)


def _parse(text: str, *, path: Path) -> DebtLedger:
    events: list[dict[str, Any]] = []
    try:
        for number, raw in enumerate(text.splitlines(), start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise LedgerError(f"checkpoint line {number} is not a JSON object")
            events.append(value)
    except json.JSONDecodeError as exc:
        raise LedgerError(f"invalid debt-ledger checkpoint JSON: {exc}") from exc
    return DebtLedger(path, events)


def _ref_commit(repo: Path, ref: str) -> str | None:
    value = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False).strip()
    return value or None


def _write_local_ledger(ledger: DebtLedger, events: list[dict[str, Any]]) -> None:
    # Validate the complete hash chain before replacing the local file.
    DebtLedger(ledger.path, events)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    temp = ledger.path.with_name(ledger.path.name + ".restore.tmp")
    temp.write_text(_serialize(events), encoding="utf-8")
    os.replace(temp, ledger.path)
    ledger.events = list(events)


def checkpoint_ledger(
    *,
    repo: Path,
    ledger: DebtLedger,
    ref: str = DEFAULT_LEDGER_REF,
) -> str:
    """Store a ledger snapshot on a Git ref without changing the code tree or HEAD."""
    body = _serialize(ledger.events)
    blob = git(repo, "hash-object", "-w", "--stdin", input_text=body).strip()
    tree = git(
        repo,
        "mktree",
        input_text=f"100644 blob {blob}\t{LEDGER_OBJECT_PATH}\n",
    ).strip()
    parent = _ref_commit(repo, ref)
    args = [
        "-c", "user.name=DiffWitness",
        "-c", "user.email=diffwitness@localhost",
        "commit-tree", tree,
    ]
    if parent:
        args += ["-p", parent]
    message = (
        "DiffWitness debt ledger checkpoint\n\n"
        f"events: {len(ledger.events)}\n"
        f"last-hash: {ledger.last_hash or 'none'}\n"
    )
    commit = git(repo, *args, input_text=message).strip()
    if parent:
        git(repo, "update-ref", ref, commit, parent)
    else:
        git(repo, "update-ref", ref, commit)
    return commit


def read_checkpoint(
    *,
    repo: Path,
    ledger_path: Path,
    ref: str = DEFAULT_LEDGER_REF,
) -> DebtLedger | None:
    commit = _ref_commit(repo, ref)
    if not commit:
        return None
    text = git(repo, "show", f"{commit}:{LEDGER_OBJECT_PATH}")
    return _parse(text, path=ledger_path)


def restore_checkpoint(
    *,
    repo: Path,
    ledger: DebtLedger,
    ref: str = DEFAULT_LEDGER_REF,
    missing_ok: bool = False,
) -> str:
    """Fast-forward a local ledger from a checkpoint; divergent histories fail closed."""
    checkpoint = read_checkpoint(repo=repo, ledger_path=ledger.path, ref=ref)
    if checkpoint is None:
        if missing_ok:
            return "missing"
        raise LedgerError(f"debt ledger checkpoint ref does not exist: {ref}")

    local_hashes = [str(event.get("event_hash")) for event in ledger.events]
    remote_hashes = [str(event.get("event_hash")) for event in checkpoint.events]
    if local_hashes == remote_hashes:
        return "equal"
    if local_hashes == remote_hashes[: len(local_hashes)]:
        _write_local_ledger(ledger, checkpoint.events)
        return "restored"
    if remote_hashes == local_hashes[: len(remote_hashes)]:
        return "local-ahead"
    raise LedgerError(
        "local and checkpoint debt ledgers diverged; refusing to merge two hash-chain histories automatically"
    )


def fetch_checkpoint(
    *,
    repo: Path,
    remote: str = "origin",
    ref: str = DEFAULT_LEDGER_REF,
    missing_ok: bool = True,
) -> bool:
    """Fetch the portable ledger ref without touching code refs."""
    target = ref
    proc = git(
        repo,
        "fetch",
        "--no-tags",
        remote,
        f"+{ref}:{target}",
        check=False,
    )
    if _ref_commit(repo, ref):
        return True
    if missing_ok:
        return False
    raise LedgerError(f"could not fetch debt ledger checkpoint {ref} from {remote}: {proc.strip()}")
