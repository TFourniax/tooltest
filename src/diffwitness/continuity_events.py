from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .continuity_contract import (
    ENTITY_ID_PATTERN, ENTITY_KIND_PATTERN, EPISTEMIC_STATUSES, EVENT_TYPE_PATTERN,
    EVENT_SCHEMA_VERSION as SCHEMA_VERSION, MAX_BATCH_EVENTS as _MAX_BATCH_EVENTS,
    MAX_EVENT_BYTES as _MAX_EVENT_BYTES, MAX_LABEL_CHARS, MAX_RELATIONS,
    RELATION_PREDICATE_PATTERN, PROFILE_PROVENANCE_FIELD,
    compatible_profile_adoption, validate_admission_profile,
)
from .gitops import git, repo_root
from .json_contract import strict_json_loads
from .continuity_task_contract import TaskHistoryValidator
from .continuity_lifecycle_contract import MemoryHistoryValidator


class ContinuityError(RuntimeError):
    pass


_EVENT_TYPE = re.compile(EVENT_TYPE_PATTERN)
_ENTITY_ID = re.compile(ENTITY_ID_PATTERN)
_LOCK_TIMEOUT_SECONDS = 10.0
_STALE_LOCK_SECONDS = 120.0
_JSON_ATOMIC_TYPES = frozenset((str, int, float, bool, type(None)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContinuityError("project event cannot be represented as finite JSON") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _detach_json(value: Any, memo: dict | None = None) -> Any:
    """Deep-copy JSON containers without generic dispatch for every scalar.

    One private memo preserves aliases, cycles and deepcopy fallback behavior.
    This is an ownership boundary, never a parser or a validation shortcut.
    """
    kind = type(value)
    if kind in _JSON_ATOMIC_TYPES:
        if memo is not None and id(value) in memo:
            # Custom fallbacks may memoize a scalar. CPython versions differ
            # on whether deepcopy honors that entry; preserve this runtime's rule.
            return copy.deepcopy(value, memo)
        return value
    if memo is None:
        memo = {}
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if kind is dict:
        result = {}
        memo[identity] = result
        for key, item in value.items():
            result[_detach_json(key, memo)] = _detach_json(item, memo)
    elif kind is list:
        result = []
        memo[identity] = result
        result.extend(_detach_json(item, memo) for item in value)
    else:
        return copy.deepcopy(value, memo)
    # Match deepcopy's lifetime protection if a custom fallback mutates inputs.
    memo.setdefault(id(memo), []).append(value)
    return result


def _git_common_dir(repo: Path) -> Path:
    from .gitops import _cached_repository_path

    return _cached_repository_path("common", repo, lambda: _resolve_git_common_dir(repo))


def _resolve_git_common_dir(repo: Path) -> Path:
    raw = git(repo, "rev-parse", "--git-common-dir").strip()
    if not raw:
        raise ContinuityError("cannot resolve Git common directory")
    path = Path(raw)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


@dataclass(frozen=True, slots=True)
class ContinuityPaths:
    root: Path
    events: Path
    state: Path
    lock: Path


def continuity_paths(repo: str | Path = ".") -> ContinuityPaths:
    return _paths_for_root(repo_root(repo))


def _paths_for_root(root_repo: Path) -> ContinuityPaths:
    """Internal path resolution after the caller has already validated the Git root."""
    root = _git_common_dir(root_repo) / "diffwitness"
    return ContinuityPaths(
        root=root,
        events=root / "events.jsonl",
        state=root / "state.db",
        lock=root / "events.lock",
    )


def _event_hash(event: dict[str, Any]) -> str:
    stable = {key: value for key, value in event.items() if key != "event_hash"}
    return _sha(stable)


def _event_id(event: dict[str, Any]) -> str:
    stable = {key: value for key, value in event.items() if key not in {"event_id", "event_hash"}}
    return "dwev_" + _sha(stable)[:24]


def _validate_subject(subject: Any) -> None:
    if not isinstance(subject, dict):
        raise ContinuityError("project event subject must be an object")
    entity_id = subject.get("id")
    kind = subject.get("kind")
    if not isinstance(entity_id, str) or not _ENTITY_ID.fullmatch(entity_id):
        raise ContinuityError(f"invalid project entity id: {entity_id!r}")
    if not isinstance(kind, str) or not re.fullmatch(ENTITY_KIND_PATTERN, kind):
        raise ContinuityError(f"invalid project entity kind: {kind!r}")
    label = subject.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > MAX_LABEL_CHARS):
        raise ContinuityError(f"project entity label must be a string <= {MAX_LABEL_CHARS} chars")


def _validate_relations(relations: Any) -> None:
    if not isinstance(relations, list) or len(relations) > MAX_RELATIONS:
        raise ContinuityError(f"project event relations must be a list with at most {MAX_RELATIONS} items")
    for relation in relations:
        if not isinstance(relation, dict):
            raise ContinuityError("project relation must be an object")
        predicate = relation.get("predicate")
        if not isinstance(predicate, str) or not re.fullmatch(RELATION_PREDICATE_PATTERN, predicate):
            raise ContinuityError(f"invalid project relation predicate: {predicate!r}")
        _validate_subject(relation.get("target"))
        status = relation.get("epistemic_status")
        if status is not None and (not isinstance(status, str) or status not in EPISTEMIC_STATUSES):
            raise ContinuityError(f"invalid relation epistemic status: {status!r}")
        metadata = relation.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ContinuityError("project relation metadata must be an object")


def _validate_event_shape(event: dict[str, Any], *, line: int | None = None) -> None:
    where = f" at line {line}" if line is not None else ""
    if event.get("schema_version") != SCHEMA_VERSION:
        raise ContinuityError(f"unsupported project event schema{where}")
    event_type = event.get("event_type")
    if not isinstance(event_type, str) or not _EVENT_TYPE.fullmatch(event_type):
        raise ContinuityError(f"invalid project event type{where}: {event_type!r}")
    status = event.get("epistemic_status")
    if not isinstance(status, str) or status not in EPISTEMIC_STATUSES:
        raise ContinuityError(f"invalid epistemic status{where}")
    if not isinstance(event.get("timestamp"), str) or not event.get("timestamp"):
        raise ContinuityError(f"invalid timestamp{where}")
    actor = event.get("actor")
    if not isinstance(actor, dict) or not isinstance(actor.get("kind"), str) or not actor.get("kind"):
        raise ContinuityError(f"invalid actor{where}")
    _validate_subject(event.get("subject"))
    _validate_relations(event.get("relations", []))
    if not isinstance(event.get("payload"), dict):
        raise ContinuityError(f"invalid payload{where}")
    if not isinstance(event.get("provenance"), dict):
        raise ContinuityError(f"invalid provenance{where}")
    try:
        validate_admission_profile(event)
    except ValueError as exc:
        raise ContinuityError(f"invalid project event profile{where}: {exc}") from exc
    dedupe_key = event.get("dedupe_key")
    if dedupe_key is not None and (not isinstance(dedupe_key, str) or not dedupe_key or len(dedupe_key) > 500):
        raise ContinuityError(f"invalid dedupe key{where}")
    raw = (_canonical(event) + "\n").encode("utf-8")
    if len(raw) > _MAX_EVENT_BYTES:
        raise ContinuityError(f"project event{where} exceeds {_MAX_EVENT_BYTES} bytes")


class _ProjectEventValidator:
    """Privately owned validated chain and ordered reference state; never persisted."""

    def __init__(self) -> None:
        self.previous: str | None = None
        self.dedupe: set[str] = set()
        self.task_history = TaskHistoryValidator()
        self.memory_history = MemoryHistoryValidator()
        self.count = 0

    def admit(self, event: dict[str, Any]) -> None:
        index = self.count + 1
        if not isinstance(event, dict):
            raise ContinuityError(f"project event line {index} is not an object")
        _validate_event_shape(event, line=index)
        if event.get("prev_hash") != self.previous:
            raise ContinuityError(f"project event hash chain broken at line {index}")
        if event.get("event_id") != _event_id(event):
            raise ContinuityError(f"project event id integrity failed at line {index}")
        expected_hash = _event_hash(event)
        if event.get("event_hash") != expected_hash:
            raise ContinuityError(f"project event integrity failed at line {index}")
        dedupe_key = event.get("dedupe_key")
        if dedupe_key is not None:
            if dedupe_key in self.dedupe:
                raise ContinuityError(f"duplicate project event dedupe key at line {index}: {dedupe_key}")
            self.dedupe.add(dedupe_key)
        self.previous = expected_hash
        try:
            self.task_history.admit(event)
        except ValueError as exc:
            raise ContinuityError(f"invalid task history at line {index}: {exc}") from exc
        try:
            self.memory_history.admit(event)
        except ValueError as exc:
            raise ContinuityError(f"invalid memory history at line {index}: {exc}") from exc
        self.count = index


def validate_project_events(events: list[dict[str, Any]]) -> _ProjectEventValidator:
    validator = _ProjectEventValidator()
    for event in events:
        validator.admit(event)
    return validator


def _read_validated_snapshot(path: Path) -> tuple[list[dict[str, Any]], str, _ProjectEventValidator]:
    """Return validated events and SHA-256 of the exact bytes used to parse them.

    A later file read can observe another writer's bytes. It must never supply the
    freshness anchor for this validated snapshot. Include whitespace and original
    line endings in the digest; event-chain validation still uses canonical JSON.
    """
    digest = hashlib.sha256()
    if not path.exists():
        return [], digest.hexdigest(), _ProjectEventValidator()
    events: list[dict[str, Any]] = []
    try:
        with path.open("rb") as handle:
            for number, raw in enumerate(handle, start=1):
                digest.update(raw)
                # Retain the former text reader's support for CR-only line endings.
                for line in raw.decode("utf-8").split("\r"):
                    if not line.strip():
                        continue
                    value = strict_json_loads(line)
                    if not isinstance(value, dict):
                        raise ContinuityError(f"project event line {number} is not an object")
                    events.append(value)
    except (OSError, ValueError, RecursionError) as exc:
        raise ContinuityError(f"cannot read project event log {path}: {exc}") from exc
    validator = validate_project_events(events)
    return events, digest.hexdigest(), validator


def read_project_event_snapshot(path: Path) -> tuple[list[dict[str, Any]], str]:
    events, digest, _ = _read_validated_snapshot(path)
    return events, digest


def read_project_events(path: Path) -> list[dict[str, Any]]:
    return read_project_event_snapshot(path)[0]


@dataclass(frozen=True, slots=True)
class _AppendCheckpoint:
    path: Path
    raw: bytes
    validator: _ProjectEventValidator
    by_dedupe: dict[str, dict[str, Any]]


_APPEND_CACHE_MAX_BYTES = 128 * 1024 * 1024
_APPEND_CACHE_MAX_EVENTS = 100_000
_append_checkpoint: _AppendCheckpoint | None = None
_append_checkpoint_lock = threading.Lock()


def _append_history(path: Path) -> tuple[bytes, _ProjectEventValidator, dict[str, dict[str, Any]]]:
    """Take exclusive ownership of a byte-bound, process-private checkpoint.

    Remove it BEFORE any fallible read/admission/write. No failed operation can
    publish speculative reference or dedupe state. Other repositories may evict
    this optimization; the journal lock already serializes this repository.
    """
    global _append_checkpoint
    with _append_checkpoint_lock:
        cached, _append_checkpoint = _append_checkpoint, None
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raw = b""
    except OSError as exc:
        raise ContinuityError(f"cannot read project event log {path}: {exc}") from exc
    if (cached is not None and cached.path == path and raw.startswith(cached.raw)
            and (not cached.raw or cached.raw.endswith((b"\n", b"\r")))):
        validator, by_dedupe = cached.validator, cached.by_dedupe
        suffix = raw[len(cached.raw):]
    else:
        validator, by_dedupe = _ProjectEventValidator(), {}
        suffix = raw
    try:
        # Match the strict reader's LF/CR framing; Unicode separators are data.
        for physical_line in suffix.split(b"\n"):
            for line in physical_line.split(b"\r"):
                text = line.decode("utf-8")
                if not text.strip():
                    continue
                event = strict_json_loads(text)
                validator.admit(event)
                if event.get("dedupe_key") is not None:
                    by_dedupe[event["dedupe_key"]] = event
    except (ValueError, RecursionError) as exc:
        raise ContinuityError(f"cannot read project event log {path}: {exc}") from exc
    return raw, validator, by_dedupe


def _remember_append(path: Path, raw: bytes, validator: _ProjectEventValidator,
                     by_dedupe: dict[str, dict[str, Any]]) -> None:
    global _append_checkpoint
    if (len(raw) <= _APPEND_CACHE_MAX_BYTES and validator.count <= _APPEND_CACHE_MAX_EVENTS
            and (not raw or raw.endswith((b"\n", b"\r")))):
        with _append_checkpoint_lock:
            _append_checkpoint = _AppendCheckpoint(path, raw, validator, by_dedupe)


@contextmanager
def _event_lock(paths: ContinuityPaths, *, timeout: float = _LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    paths.root.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}:{time.time_ns()}"
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(paths.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except PermissionError as exc:
            # Windows can deny CREATE_NEW while the previous lock's deletion
            # is pending. Retry only acquisition, never bypass exclusivity or
            # remove a lock on this evidence. Persistent ACL failures still
            # fail closed within the existing acquisition deadline.
            if os.name != "nt":
                raise
            if time.monotonic() >= deadline:
                raise ContinuityError(f"cannot acquire project event lock {paths.lock}: {exc}") from exc
            time.sleep(0.05)
            continue
        except FileExistsError:
            try:
                age = time.time() - paths.lock.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > _STALE_LOCK_SECONDS:
                try:
                    paths.lock.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise ContinuityError(f"timed out waiting for project event lock {paths.lock}")
            time.sleep(0.05)
            continue
        try:
            os.write(fd, token.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        try:
            owner = paths.lock.read_text(encoding="utf-8")
        except OSError:
            owner = None
        if owner == token:
            try:
                paths.lock.unlink()
            except FileNotFoundError:
                pass


def _semantic_core(event: dict[str, Any]) -> dict[str, Any]:
    core = {
        key: event.get(key)
        for key in (
            "event_type",
            "actor",
            "epistemic_status",
            "subject",
            "relations",
            "payload",
            "provenance",
            "dedupe_key",
        )
    }
    provenance = dict(core.get("provenance") or {})
    if provenance.get("source") == "change-envelope":
        # The digest identifies one serialized envelope instance. Re-verifying the same semantic
        # change can produce another valid envelope/certificate without changing the event's
        # dedupe identity, so this transport digest must not manufacture a semantic conflict.
        provenance.pop("artifact_digest", None)
        core["provenance"] = provenance
    # A software change is identified by repository fingerprint + base/candidate trees (the
    # tree-derived ``dwchg_*`` identity), not by the temporary commit objects used to snapshot a
    # dirty worktree. Re-verifying the same trees legitimately creates fresh ephemeral commit SHAs.
    # Ignore those transport/provenance SHAs only for idempotency comparison so an existing
    # change.observed event can be reused while a new proof.completed certificate is appended.
    if event.get("event_type") == "change.observed" and str(event.get("dedupe_key") or "").startswith("change:dwchg_"):
        payload = dict(core.get("payload") or {})
        payload.pop("base_sha", None)
        payload.pop("candidate_sha", None)
        core["payload"] = payload
    return core


def _candidate_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    event_type = spec.get("event_type")
    epistemic_status = spec.get("epistemic_status")
    subject = spec.get("subject")
    actor_value = dict(spec.get("actor") or {"kind": "system", "id": "diffwitness"})
    relations_value = list(spec.get("relations") or [])
    payload_value = dict(spec.get("payload") or {})
    provenance_value = dict(spec.get("provenance") or {"producer": "diffwitness", "source": "local"})
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "timestamp": spec.get("timestamp") or _now(),
        "actor": actor_value,
        "epistemic_status": epistemic_status,
        "subject": dict(subject or {}),
        "relations": relations_value,
        "payload": payload_value,
        "provenance": provenance_value,
        "dedupe_key": spec.get("dedupe_key"),
        "prev_hash": None,
    }
    _validate_event_shape(candidate)
    return candidate


def _record_separator() -> bytes:
    return os.linesep.encode("ascii")


def _durable_append(paths: ContinuityPaths, events: list[dict[str, Any]]) -> bytes:
    if not events:
        return b""
    separator = _record_separator()
    raw = b"".join(_canonical(event).encode("utf-8") + separator for event in events)
    # A valid imported last JSON object need not end in a newline. Preserve its
    # bytes and add a record separator before appending the next event.
    try:
        with paths.events.open("rb") as handle:
            if handle.seek(0, os.SEEK_END):
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) not in (b"\n", b"\r"):
                    raw = separator + raw
    except FileNotFoundError:
        pass
    paths.root.mkdir(parents=True, exist_ok=True)
    # O_TEXT translates LF to CRLF in the Windows CRT. Format native endings
    # explicitly and write binary so the checkpoint records actual disk bytes.
    fd = os.open(paths.events, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o600)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0:
                raise ContinuityError("failed to append project event batch")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        directory_fd = os.open(paths.root, os.O_RDONLY)
    except OSError:
        directory_fd = None
    if directory_fd is not None:
        try:
            os.fsync(directory_fd)
        except OSError:
            pass
        finally:
            os.close(directory_fd)
    return raw


def append_project_events(
    *,
    repo: str | Path,
    events: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], bool]]:
    """Append a semantic batch with one lock/read/validation/write/fsync cycle.

    This is the preferred path for one software change because Proof, Debt and Understanding are one
    logical observation. It also means invalid later items cannot leave a partially imported change.
    Existing duplicate items are returned as ``created=False`` and do not consume a new hash-chain
    position.
    """
    if not isinstance(events, list) or len(events) > _MAX_BATCH_EVENTS:
        raise ContinuityError(f"project event batch must contain at most {_MAX_BATCH_EVENTS} items")
    if not events:
        return []
    root_repo = repo_root(repo)
    paths = continuity_paths(root_repo)
    # Detach nested caller data before a candidate can enter private validator
    # state. Returned objects are detached again at the public boundary below.
    candidates = [_detach_json(_candidate_from_spec(spec)) for spec in events]

    with _event_lock(paths):
        raw, validator, by_dedupe = _append_history(paths.events)
        results: list[tuple[dict[str, Any], bool]] = []
        appended: list[dict[str, Any]] = []
        previous_hash = validator.previous

        for candidate in candidates:
            dedupe_key = candidate.get("dedupe_key")
            if dedupe_key is not None and str(dedupe_key) in by_dedupe:
                event = by_dedupe[str(dedupe_key)]
                probe = {**candidate, "timestamp": event.get("timestamp"), "prev_hash": event.get("prev_hash")}
                probe["event_id"] = _event_id(probe)
                probe["event_hash"] = _event_hash(probe)
                old_core, new_core = _semantic_core(event), _semantic_core(probe)
                if compatible_profile_adoption(event, probe):
                    for core in (old_core, new_core):
                        core["provenance"] = dict(core["provenance"])
                        core["provenance"].pop(PROFILE_PROVENANCE_FIELD, None)
                # Python equality conflates JSON booleans and numbers (True == 1).
                # Canonical JSON preserves their types and ignores object key order.
                if _canonical(old_core) != _canonical(new_core):
                    raise ContinuityError(f"conflicting project event for dedupe key {dedupe_key}")
                results.append((event, False))
                continue

            candidate["prev_hash"] = previous_hash
            candidate["event_id"] = _event_id(candidate)
            candidate["event_hash"] = _event_hash(candidate)
            appended.append(candidate)
            results.append((candidate, True))
            previous_hash = candidate["event_hash"]
            if dedupe_key is not None:
                by_dedupe[str(dedupe_key)] = candidate

        # Only privately owned validation state bound to ALL prefix bytes can
        # seed these validators. Invalid suffixes discard the whole checkpoint.
        for event in appended:
            validator.admit(event)
        written = _durable_append(paths, appended)
        _remember_append(paths.events, raw + written, validator, by_dedupe)
        result_memo = {}
        return [(_detach_json(event, result_memo), created) for event, created in results]


def append_project_event(
    *,
    repo: str | Path,
    event_type: str,
    subject: dict[str, Any],
    epistemic_status: str,
    payload: dict[str, Any] | None = None,
    relations: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    timestamp: str | None = None,
) -> tuple[dict[str, Any], bool]:
    return append_project_events(
        repo=repo,
        events=[
            {
                "event_type": event_type,
                "subject": subject,
                "epistemic_status": epistemic_status,
                "payload": payload,
                "relations": relations,
                "provenance": provenance,
                "actor": actor,
                "dedupe_key": dedupe_key,
                "timestamp": timestamp,
            }
        ],
    )[0]


def event_head(repo: str | Path = ".") -> str | None:
    events = read_project_events(continuity_paths(repo).events)
    return events[-1]["event_hash"] if events else None
