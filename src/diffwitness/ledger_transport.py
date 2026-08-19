from __future__ import annotations

import hashlib
import json
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


def _tracking_ref(remote: str, ref: str) -> str:
    digest = hashlib.sha256(f"{remote}\0{ref}".encode("utf-8")).hexdigest()[:16]
    return f"refs/diffwitness/remotes/{digest}"


def _set_ref(repo: Path, ref: str, commit: str) -> None:
    git(repo, "update-ref", ref, commit)


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
        "-c",
        "user.name=DiffWitness",
        "-c",
        "user.email=diffwitness@localhost",
        "commit-tree",
        tree,
    ]
    if parent:
        # Avoid producing a new checkpoint commit when the current ref already contains the
        # exact same ledger bytes. This keeps repeated `dw ledger push` calls idempotent.
        current = read_checkpoint(repo=repo, ledger_path=ledger.path, ref=ref)
        if current is not None and current.events == ledger.events:
            return parent
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
        ledger.replace_events(checkpoint.events)
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
    target_ref: str | None = None,
    missing_ok: bool = True,
) -> bool:
    """Fetch a portable ledger ref without touching code refs.

    Callers that need to preserve a local checkpoint should provide `target_ref`; the higher-level
    `pull_checkpoint` helper always fetches into a dedicated tracking ref for this reason.
    """
    target = target_ref or ref
    # A failed fetch must not look successful merely because a previous attempt left a tracking
    # ref behind. Dedicated tracking refs are disposable, so clear them before every fetch.
    if target_ref is not None:
        git(repo, "update-ref", "-d", target, check=False)
    proc = git(
        repo,
        "fetch",
        "--no-tags",
        remote,
        f"+{ref}:{target}",
        check=False,
    )
    if _ref_commit(repo, target):
        return True
    if missing_ok:
        return False
    raise LedgerError(f"could not fetch debt ledger checkpoint {ref} from {remote}: {proc.strip()}")


def pull_checkpoint(
    *,
    repo: Path,
    ledger: DebtLedger,
    remote: str = "origin",
    ref: str = DEFAULT_LEDGER_REF,
    missing_ok: bool = True,
) -> str:
    """Fetch and fast-forward the local ledger from a remote checkpoint.

    The remote ref is first fetched into a dedicated tracking ref, so a stale remote can never
    overwrite a newer local checkpoint before ledger-history compatibility is checked.
    """
    tracking = _tracking_ref(remote, ref)
    if not fetch_checkpoint(
        repo=repo,
        remote=remote,
        ref=ref,
        target_ref=tracking,
        missing_ok=missing_ok,
    ):
        return "missing"
    remote_commit = _ref_commit(repo, tracking)
    if not remote_commit:
        if missing_ok:
            return "missing"
        raise LedgerError(f"fetched debt ledger checkpoint has no commit: {ref}")

    status = restore_checkpoint(repo=repo, ledger=ledger, ref=tracking, missing_ok=False)
    if status in {"equal", "restored"}:
        # Preserve the remote checkpoint's commit ancestry so a later push is a true fast-forward.
        _set_ref(repo, ref, remote_commit)
    elif status == "local-ahead":
        # Re-parent a fresh local checkpoint onto the remote checkpoint. The event-chain prefix
        # check above proves that the local ledger contains every remote event in order.
        _set_ref(repo, ref, remote_commit)
        checkpoint_ledger(repo=repo, ledger=ledger, ref=ref)
    return status


def push_checkpoint(
    *,
    repo: Path,
    ledger: DebtLedger,
    remote: str = "origin",
    ref: str = DEFAULT_LEDGER_REF,
) -> str:
    """Checkpoint the current ledger and push it without force.

    A concurrent remote update therefore fails as a non-fast-forward instead of silently losing
    another writer's debt history. Run `dw ledger pull` and retry after reconciling.
    """
    commit = checkpoint_ledger(repo=repo, ledger=ledger, ref=ref)
    output = git(repo, "push", remote, f"{ref}:{ref}")
    return output.strip() or commit
