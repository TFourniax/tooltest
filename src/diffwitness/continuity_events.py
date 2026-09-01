from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .gitops import git, repo_root


class ContinuityError(RuntimeError):
    pass


SCHEMA_VERSION = "project-event-1"
EPISTEMIC_STATUSES = {"DECLARED", "INFERRED", "OBSERVED", "VERIFIED"}
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9-]{1,31}\.[a-z][a-z0-9-]{1,31}$")
_ENTITY_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/@-]{0,255}$")
_LOCK_TIMEOUT_SECONDS = 10.0
_STALE_LOCK_SECONDS = 120.0
_MAX_EVENT_BYTES = 256 * 1024
_MAX_BATCH_EVENTS = 2048


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _git_common_dir(repo: Path) -> Path:
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
    root_repo = repo_root(repo)
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
    if not isinstance(kind, str) or not re.fullmatch(r"^[a-z][a-z0-9-]{0,63}$", kind):
        raise ContinuityError(f"invalid project entity kind: {kind!r}")
    label = subject.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > 500):
        raise ContinuityError("project entity label must be a string <= 500 chars")


def _validate_relations(relations: Any) -> None:
    if not isinstance(relations, list) or len(relations) > 256:
        raise ContinuityError("project event relations must be a list with at most 256 items")
    for relation in relations:
        if not isinstance(relation, dict):
            raise ContinuityError("project relation must be an object")
        predicate = relation.get("predicate")
        if not isinstance(predicate, str) or not re.fullmatch(r"^[a-z][a-z0-9_.-]{0,63}$", predicate):
            raise ContinuityError(f"invalid project relation predicate: {predicate!r}")
        _validate_subject(relation.get("target"))
        status = relation.get("epistemic_status")
        if status is not None and status not in EPISTEMIC_STATUSES:
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
    if event.get("epistemic_status") not in EPISTEMIC_STATUSES:
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
    dedupe_key = event.get("dedupe_key")
    if dedupe_key is not None and (not isinstance(dedupe_key, str) or not dedupe_key or len(dedupe_key) > 500):
        raise ContinuityError(f"invalid dedupe key{where}")
    raw = (_canonical(event) + "\n").encode("utf-8")
    if len(raw) > _MAX_EVENT_BYTES:
        raise ContinuityError(f"project event{where} exceeds {_MAX_EVENT_BYTES} bytes")


def validate_project_events(events: list[dict[str, Any]]) -> None:
    previous: str | None = None
    dedupe: set[str] = set()
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            raise ContinuityError(f"project event line {index} is not an object")
        _validate_event_shape(event, line=index)
        if event.get("prev_hash") != previous:
            raise ContinuityError(f"project event hash chain broken at line {index}")
        if event.get("event_id") != _event_id(event):
            raise ContinuityError(f"project event id integrity failed at line {index}")
        expected_hash = _event_hash(event)
        if event.get("event_hash") != expected_hash:
            raise ContinuityError(f"project event integrity failed at line {index}")
        dedupe_key = event.get("dedupe_key")
        if dedupe_key is not None:
            if dedupe_key in dedupe:
                raise ContinuityError(f"duplicate project event dedupe key at line {index}: {dedupe_key}")
            dedupe.add(dedupe_key)
        previous = expected_hash


def read_project_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ContinuityError(f"project event line {number} is not an object")
                events.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuityError(f"cannot read project event log {path}: {exc}") from exc
    validate_project_events(events)
    return events


@contextmanager
def _event_lock(paths: ContinuityPaths, *, timeout: float = _LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    paths.root.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}:{time.time_ns()}"
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(paths.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
    return {
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


def _durable_append(paths: ContinuityPaths, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    raw = b"".join((_canonical(event) + "\n").encode("utf-8") for event in events)
    paths.root.mkdir(parents=True, exist_ok=True)
    fd = os.open(paths.events, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
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
    candidates = [_candidate_from_spec(spec) for spec in events]

    with _event_lock(paths):
        existing = read_project_events(paths.events)
        by_dedupe = {
            str(event["dedupe_key"]): event
            for event in existing
            if event.get("dedupe_key") is not None
        }
        results: list[tuple[dict[str, Any], bool]] = []
        appended: list[dict[str, Any]] = []
        previous_hash = existing[-1]["event_hash"] if existing else None

        for candidate in candidates:
            dedupe_key = candidate.get("dedupe_key")
            if dedupe_key is not None and str(dedupe_key) in by_dedupe:
                event = by_dedupe[str(dedupe_key)]
                probe = {**candidate, "timestamp": event.get("timestamp"), "prev_hash": event.get("prev_hash")}
                probe["event_id"] = _event_id(probe)
                probe["event_hash"] = _event_hash(probe)
                if _semantic_core(event) != _semantic_core(probe):
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

        # Existing history was already validated by read_project_events. One complete pass here checks
        # the batch's chain continuity and duplicate semantics before a single byte is appended.
        validate_project_events([*existing, *appended])
        _durable_append(paths, appended)
        return results


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
