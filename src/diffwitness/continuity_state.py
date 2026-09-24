from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .continuity_contract import DECLARATION_PROFILE, PROFILE_PROVENANCE_FIELD, projection_lifecycle as _lifecycle
from .continuity_events import (ContinuityPaths, _event_lock, continuity_paths,
                                read_project_event_snapshot, read_project_events)
from .continuity_task_contract import is_task_edge_event
from .continuity_lifecycle_contract import is_memory_lifecycle, lifecycle_view
from .continuity_memory_code_contract import is_memory_code
from .continuity_search import SEARCHABLE_KINDS, memory_text, tokens
from .gitops import git, repo_root

# Rebuild existing derived databases: v2 could attach an earlier assertion's authority
# to replacement content. The append-only event schema and historical Proof stay intact.
# v7 rebuilds lexical terms with accent folding. Journal identities and bytes do
# not change; v6 indexes must not be reused with the new query normalization.
# v9 stores lexical pairs once in their composite primary-key tree. Rebuild v8
# derived databases; journal bytes, identities and lexical semantics are unchanged.
STATE_SCHEMA = "continuity-state-9"
# Older stamps did not enforce explicitly selected declaration profiles.
# Only a snapshot validated under current JSON/profile rules establishes this anchor.
VALIDATED_EVENT_DIGEST_META = "memory_code_event_file_sha256"
_CANONICAL_ENCODER = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical(value: Any) -> str:
    return _CANONICAL_ENCODER.encode(value)


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys=on")
        conn.execute("pragma busy_timeout=5000")
    except BaseException:
        conn.close()
        raise
    return conn


_INDEX_STATEMENTS = (
    'create index events_type_idx on events(event_type, sequence desc)',
    'create index events_subject_idx on events(subject_id, sequence desc)',
    'create index entities_kind_idx on entities(kind, lifecycle, updated_at desc)',
    'create index entities_critical_idx on entities(critical,lifecycle)',
    'create index entity_terms_term_idx on entity_terms(term,entity_id)',
    'create index relations_source_idx on relations(source_id, predicate)',
    'create index relations_target_idx on relations(target_id, predicate)',
    'create index changes_updated_idx on changes(updated_at desc)',
    'create index proofs_change_idx on proofs(change_id, updated_at desc)',
    'create index debts_status_idx on debts(status, updated_at desc)',
    'create index debts_change_idx on debts(last_change_id)',
    'create index debts_intro_change_idx on debts(introduced_change_id)',
    'create index debts_path_idx on debts(path, status)',
    'create index structure_components_module_idx on structure_components(module_name)',
    'create index structure_symbols_name_idx on structure_symbols(qualified_name)',
    'create index structure_symbols_path_idx on structure_symbols(path)',
    'create index structure_edges_source_idx on structure_edges(source_id, predicate)',
    'create index structure_edges_target_idx on structure_edges(target_id, predicate)',
)


def _indexes(conn: sqlite3.Connection) -> None:
    # Individual execute calls preserve the schema/projection transaction.
    for statement in _INDEX_STATEMENTS:
        conn.execute(statement)


def _schema(conn: sqlite3.Connection, *, indexes: bool = True) -> None:
    # This is a fresh temporary database. Keep DDL and the subsequent event
    # projection in one durable transaction, committed by rebuild_state.
    conn.executescript(
        """
        begin;
        create table meta(key text primary key, value text not null);
        create table events(
          sequence integer primary key,
          event_id text unique not null,
          event_type text not null,
          timestamp text not null,
          epistemic_status text not null,
          subject_id text not null,
          subject_kind text not null,
          event_hash text unique not null,
          payload_json text not null,
          provenance_json text not null
        );

        create table entities(
          entity_id text primary key,
          kind text not null,
          label text,
          epistemic_status text not null,
          lifecycle text not null default 'active',
          updated_at text not null,
          payload_json text not null,
          provenance_json text not null,
          source_event_id text not null,
          critical integer not null default 0
        );
        create table entity_terms(entity_id text not null, term text not null, primary key(entity_id,term)) without rowid;

        create table memory_lifecycle(entity_id text primary key, lifecycle_json text not null);

        create table relations(
          relation_id text primary key,
          source_id text not null,
          predicate text not null,
          target_id text not null,
          target_kind text not null,
          epistemic_status text not null,
          lifecycle text not null default 'active',
          metadata_json text not null,
          source_event_id text not null,
          updated_at text not null
        );
        create view active_memory_relations as select r.* from relations r
          where r.lifecycle='active'
            and not exists(select 1 from entities e where e.entity_id=r.source_id and e.lifecycle='inactive')
            and not exists(select 1 from entities e where e.entity_id=r.target_id and e.lifecycle='inactive');

        create table changes(
          change_id text primary key,
          repository_fingerprint text not null,
          base_tree text not null,
          candidate_tree text not null,
          base_sha text,
          candidate_sha text,
          actor_json text not null,
          changed_files_json text not null,
          updated_at text not null,
          source_event_id text not null
        );

        create table proofs(
          certificate_id text primary key,
          change_id text not null,
          claim text not null,
          accepted integer not null,
          epistemic_status text not null,
          source_event_id text not null,
          updated_at text not null
        );

        create table debts(
          debt_id text primary key,
          status text not null,
          accepted integer not null default 0,
          accepted_reason text,
          category text,
          rule_id text,
          title text,
          severity text,
          measurement text,
          points integer,
          path text,
          introduced_change_id text,
          last_change_id text,
          epistemic_status text not null,
          payload_json text not null,
          source_event_id text not null,
          updated_at text not null
        );

        create table debt_snapshots(
          change_id text primary key,
          points integer not null,
          obligations integer not null,
          budget_passed integer,
          source_event_id text not null,
          updated_at text not null
        );

        create table understanding(
          change_id text primary key,
          coverage integer,
          knowledge_debt integer,
          feature_coverage integer,
          feature_debt integer,
          receipt_digest text,
          source_event_id text not null,
          updated_at text not null
        );

        create table structure_components(
          component_id text primary key,
          path text unique not null,
          language text not null,
          module_name text,
          epistemic_status text not null,
          provider text not null,
          tree_sha text,
          indexed_at text not null
        );

        create table structure_symbols(
          symbol_id text primary key,
          component_id text not null,
          path text not null,
          qualified_name text not null,
          symbol_kind text not null,
          language text not null,
          line integer,
          end_line integer,
          epistemic_status text not null,
          provider text not null,
          tree_sha text,
          indexed_at text not null
        );

        create table structure_edges(
          edge_id text primary key,
          source_id text not null,
          predicate text not null,
          target_id text not null,
          target_kind text not null,
          epistemic_status text not null,
          provider text not null,
          tree_sha text,
          indexed_at text not null
        );
        """
    )
    if indexes:
        _indexes(conn)


def _relation_id(source_id: str, predicate: str, target_id: str) -> str:
    import hashlib

    seed = f"{source_id}\0{predicate}\0{target_id}".encode("utf-8")
    return "dwrel_" + hashlib.sha256(seed).hexdigest()[:24]


_ENTITY_UPSERT = """insert into entities(entity_id,kind,label,epistemic_status,lifecycle,updated_at,payload_json,provenance_json,source_event_id,critical)
    values(?,?,?,?,?,?,?,?,?,?)
    on conflict(entity_id) do update set
      kind=excluded.kind,label=coalesce(excluded.label,entities.label),epistemic_status=excluded.epistemic_status,
      lifecycle=excluded.lifecycle,updated_at=excluded.updated_at,payload_json=excluded.payload_json,
      provenance_json=excluded.provenance_json,source_event_id=excluded.source_event_id,critical=excluded.critical"""


def _entity_row(event: dict[str, Any], payload_json: str | None = None,
                provenance_json: str | None = None) -> tuple:
    subject, payload = event["subject"], event.get("payload") or {}
    return (str(subject["id"]), subject["kind"], subject.get("label"), event["epistemic_status"],
            _lifecycle(event["event_type"], payload), event["timestamp"],
            _canonical(payload) if payload_json is None else payload_json,
            _canonical(event.get("provenance") or {}) if provenance_json is None else provenance_json,
            event["event_id"], int(subject["kind"] == "invariant" and payload.get("critical") is True))


def _entity_term_rows(conn: sqlite3.Connection, event: dict[str, Any],
                      payload_json: str | None = None) -> Iterable[tuple[str, str]]:
    subject = event["subject"]
    if subject["kind"] not in SEARCHABLE_KINDS:
        return ()
    entity_id, label = str(subject["id"]), subject.get("label")
    if label is None:
        label = conn.execute("select label from entities where entity_id=?", (entity_id,)).fetchone()[0]
    # JSON separators are not lexical tokens. Reuse the already encoded payload
    # for ordinary memory; task intent retains its narrower existing policy.
    text = (" ".join((str(label or ""), entity_id, payload_json))
            if payload_json is not None and subject["kind"] != "task"
            else memory_text(subject["kind"], entity_id, label, event.get("payload") or {}))
    values = tokens(text)
    return ((entity_id, term) for term in values)


def _upsert_entity(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    # Adding an edge does not reassert its source entity. In particular, copied
    # source payloads must not replace newer facts or their evidence provenance.
    if is_memory_lifecycle(event):
        value = lifecycle_view(event)
        conn.execute("update entities set lifecycle=? where entity_id=?", ("active" if value["active"] else "inactive", event["subject"]["id"]))
        conn.execute("insert into memory_lifecycle(entity_id,lifecycle_json) values(?,?) on conflict(entity_id) do update set lifecycle_json=excluded.lifecycle_json",
                     (event["subject"]["id"], _canonical(value)))
        return
    if event["event_type"] == "relation.declared" or is_task_edge_event(event) or is_memory_code(event):
        return
    # Authority belongs to this assertion, never to the entity ID for all time.
    conn.execute(_ENTITY_UPSERT, _entity_row(event))
    conn.execute("delete from entity_terms where entity_id=?", (str(event["subject"]["id"]),))
    conn.executemany("insert into entity_terms(entity_id,term) values(?,?)", _entity_term_rows(conn, event))


def _upsert_relations(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    source = str(event["subject"]["id"])
    for relation in event.get("relations") or []:
        target = relation["target"]
        rid = _relation_id(source, relation["predicate"], target["id"])
        status = relation.get("epistemic_status") or event["epistemic_status"]
        conn.execute(
            """insert into relations(relation_id,source_id,predicate,target_id,target_kind,epistemic_status,lifecycle,metadata_json,source_event_id,updated_at)
               values(?,?,?,?,?,?,?,?,?,?)
               on conflict(relation_id) do update set
                 target_kind=excluded.target_kind,epistemic_status=excluded.epistemic_status,lifecycle=excluded.lifecycle,
                 metadata_json=excluded.metadata_json,source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (
                rid,
                source,
                relation["predicate"],
                target["id"],
                target["kind"],
                status,
                "active",
                _canonical(relation.get("metadata") or {}),
                event["event_id"],
                event["timestamp"],
            ),
        )


def _debt_signal(payload: dict[str, Any]) -> dict[str, Any]:
    signal = payload.get("signal")
    return signal if isinstance(signal, dict) else {}


def _upsert_debt_open(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    payload = event.get("payload") or {}
    subject_id = str(event["subject"]["id"])
    signal = _debt_signal(payload)
    change_id = payload.get("change_id")
    existing = conn.execute("select * from debts where debt_id=?", (subject_id,)).fetchone()
    kind = event["event_type"]
    accepted = int(existing["accepted"]) if existing else 0
    accepted_reason = existing["accepted_reason"] if existing else None
    if kind in {"debt.introduced", "debt.reopened"}:
        accepted = 0
        accepted_reason = None
    introduced_change_id = existing["introduced_change_id"] if existing else None
    if introduced_change_id is None and change_id:
        introduced_change_id = change_id
    status = event["epistemic_status"]

    def chosen(key: str) -> Any:
        value = signal.get(key)
        if value is not None:
            return value
        return existing[key] if existing else None

    conn.execute(
        """insert into debts(
             debt_id,status,accepted,accepted_reason,category,rule_id,title,severity,measurement,points,path,
             introduced_change_id,last_change_id,epistemic_status,payload_json,source_event_id,updated_at
           ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           on conflict(debt_id) do update set
             status=excluded.status,accepted=excluded.accepted,accepted_reason=excluded.accepted_reason,
             category=excluded.category,rule_id=excluded.rule_id,title=excluded.title,severity=excluded.severity,
             measurement=excluded.measurement,points=excluded.points,path=excluded.path,
             introduced_change_id=excluded.introduced_change_id,last_change_id=excluded.last_change_id,
             epistemic_status=excluded.epistemic_status,payload_json=excluded.payload_json,
             source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
        (
            subject_id,
            "open",
            accepted,
            accepted_reason,
            chosen("category"),
            chosen("rule_id"),
            chosen("title"),
            chosen("severity"),
            chosen("measurement"),
            chosen("points"),
            chosen("path"),
            introduced_change_id,
            change_id or (existing["last_change_id"] if existing else None),
            status,
            _canonical(payload),
            event["event_id"],
            event["timestamp"],
        ),
    )


def _specialized(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    kind = event["event_type"]
    payload = event.get("payload") or {}
    subject_id = str(event["subject"]["id"])
    if kind == "change.observed":
        conn.execute(
            """insert into changes(change_id,repository_fingerprint,base_tree,candidate_tree,base_sha,candidate_sha,actor_json,changed_files_json,updated_at,source_event_id)
               values(?,?,?,?,?,?,?,?,?,?)
               on conflict(change_id) do update set actor_json=excluded.actor_json,changed_files_json=excluded.changed_files_json,
                 updated_at=excluded.updated_at,source_event_id=excluded.source_event_id""",
            (
                subject_id,
                str(payload.get("repository_fingerprint") or ""),
                str(payload.get("base_tree") or ""),
                str(payload.get("candidate_tree") or ""),
                payload.get("base_sha"),
                payload.get("candidate_sha"),
                _canonical(event.get("actor") or {}),
                _canonical(payload.get("changed_files") or []),
                event["timestamp"],
                event["event_id"],
            ),
        )
    elif kind == "proof.completed":
        cid = str(payload.get("change_id") or "")
        conn.execute(
            """insert into proofs(certificate_id,change_id,claim,accepted,epistemic_status,source_event_id,updated_at)
               values(?,?,?,?,?,?,?)
               on conflict(certificate_id) do update set change_id=excluded.change_id,claim=excluded.claim,accepted=excluded.accepted,
                 epistemic_status=excluded.epistemic_status,source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (
                subject_id,
                cid,
                str(payload.get("claim") or "unknown"),
                1 if payload.get("accepted") else 0,
                event["epistemic_status"],
                event["event_id"],
                event["timestamp"],
            ),
        )
    elif kind in {"debt.observed", "debt.introduced", "debt.refreshed", "debt.reopened"}:
        _upsert_debt_open(conn, event)
    elif kind == "debt.accepted":
        conn.execute(
            "update debts set accepted=1,accepted_reason=?,payload_json=?,source_event_id=?,updated_at=? where debt_id=?",
            (payload.get("reason"), _canonical(payload), event["event_id"], event["timestamp"], subject_id),
        )
    elif kind == "debt.unaccepted":
        conn.execute(
            "update debts set accepted=0,accepted_reason=null,payload_json=?,source_event_id=?,updated_at=? where debt_id=?",
            (_canonical(payload), event["event_id"], event["timestamp"], subject_id),
        )
    elif kind == "debt.resolved":
        conn.execute(
            "update debts set status='resolved',last_change_id=coalesce(?,last_change_id),payload_json=?,source_event_id=?,updated_at=? where debt_id=?",
            (payload.get("change_id"), _canonical(payload), event["event_id"], event["timestamp"], subject_id),
        )
    elif kind == "debt.snapshot":
        cid = str(payload.get("change_id") or subject_id)
        budget = payload.get("budget_passed")
        conn.execute(
            """insert into debt_snapshots(change_id,points,obligations,budget_passed,source_event_id,updated_at)
               values(?,?,?,?,?,?)
               on conflict(change_id) do update set points=excluded.points,obligations=excluded.obligations,
                 budget_passed=excluded.budget_passed,source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (
                cid,
                int(payload.get("points") or 0),
                int(payload.get("obligations") or 0),
                None if budget is None else (1 if budget else 0),
                event["event_id"],
                event["timestamp"],
            ),
        )
    elif kind == "understanding.recorded":
        cid = str(payload.get("change_id") or subject_id)
        conn.execute(
            """insert into understanding(change_id,coverage,knowledge_debt,feature_coverage,feature_debt,receipt_digest,source_event_id,updated_at)
               values(?,?,?,?,?,?,?,?)
               on conflict(change_id) do update set coverage=excluded.coverage,knowledge_debt=excluded.knowledge_debt,
                 feature_coverage=excluded.feature_coverage,feature_debt=excluded.feature_debt,receipt_digest=excluded.receipt_digest,
                 source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (
                cid,
                payload.get("coverage"),
                payload.get("knowledge_debt"),
                payload.get("feature_coverage"),
                payload.get("feature_debt"),
                payload.get("receipt_digest"),
                event["event_id"],
                event["timestamp"],
            ),
        )


@contextmanager
def _state_lock(paths: ContinuityPaths):
    # The journal and derived state have distinct locks. Never acquire the event
    # lock here: projection does not append, and a later append remains detectable.
    with _event_lock(replace(paths, lock=paths.root / "state.lock")):
        yield


_EVENT_INSERT = "insert into events(sequence,event_id,event_type,timestamp,epistemic_status,subject_id,subject_kind,event_hash,payload_json,provenance_json) values(?,?,?,?,?,?,?,?,?,?)"
_BATCHABLE_DECLARATIONS = frozenset(("objective.declared", "decision.recorded", "invariant.declared", "approach.failed"))


def _event_row(sequence: int, event: dict[str, Any]) -> tuple:
    return (sequence, event["event_id"], event["event_type"], event["timestamp"], event["epistemic_status"],
            event["subject"]["id"], event["subject"]["kind"], event["event_hash"],
            _canonical(event.get("payload") or {}), _canonical(event.get("provenance") or {}))


def _project_event(conn: sqlite3.Connection, sequence: int, event: dict[str, Any]) -> None:
    conn.execute(_EVENT_INSERT, _event_row(sequence, event))
    _upsert_entity(conn, event)
    _upsert_relations(conn, event)
    _specialized(conn, event)


def _project_declarations(conn: sqlite3.Connection, entries: list[tuple[int, dict[str, Any]]]) -> None:
    """Project a bounded chronological run with no specialized lifecycle effects."""
    rows = [_event_row(sequence, event) for sequence, event in entries]
    conn.executemany(_EVENT_INSERT, rows)
    # UPSERTs still run in journal order, including label coalescing and authority
    # replacement. Only the derived lexical terms wait until the final assertion.
    conn.executemany(_ENTITY_UPSERT, (_entity_row(event, row[-2], row[-1])
                                    for (_, event), row in zip(entries, rows)))
    latest = {}
    for (_, event), row in zip(entries, rows):
        _upsert_relations(conn, event)
        latest[str(event["subject"]["id"])] = event, row[-2]
    conn.executemany("delete from entity_terms where entity_id=?", ((key,) for key in latest))
    conn.executemany("insert into entity_terms(entity_id,term) values(?,?)",
                     (row for event, payload in latest.values()
                      for row in _entity_term_rows(conn, event, payload)))


def _project_history(conn: sqlite3.Connection, events: list[dict[str, Any]]) -> None:
    pending = []
    for sequence, event in enumerate(events, start=1):
        eligible = (event["event_type"] in _BATCHABLE_DECLARATIONS
                    and event["provenance"].get(PROFILE_PROVENANCE_FIELD) == DECLARATION_PROFILE)
        if pending and (not eligible or len(pending) == 2048):
            _project_declarations(conn, pending)
            pending = []
        if eligible:
            pending.append((sequence, event))
        else:
            _project_event(conn, sequence, event)
    if pending:
        _project_declarations(conn, pending)


def _stamp_snapshot(conn: sqlite3.Connection, root: Path, events: list[dict[str, Any]], digest: str) -> None:
    values = {"schema": STATE_SCHEMA, "event_count": str(len(events)),
              "event_head": events[-1]["event_hash"] if events else "",
              VALIDATED_EVENT_DIGEST_META: digest, "repository_root": str(root)}
    conn.executemany("insert into meta(key,value) values(?,?) on conflict(key) do update set value=excluded.value",
                     values.items())


def rebuild_state(repo: str | Path = ".", *, include_structure: bool = False) -> Path:
    root_repo = repo_root(repo)
    paths = continuity_paths(root_repo)
    with _state_lock(paths):
        events, digest = read_project_event_snapshot(paths.events)
        return _rebuild_snapshot(root_repo, paths, events, digest, include_structure=include_structure)


def _rebuild_snapshot(root_repo: Path, paths: ContinuityPaths, events: list[dict[str, Any]], digest: str,
                      *, include_structure: bool) -> Path:
    """Called under the state lock, only with a fully validated byte snapshot."""
    paths.root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="state-", suffix=".db", dir=paths.root)
    os.close(fd)
    temp = Path(temp_name)
    try:
        conn = _connect(temp)
        try:
            # A bounded private page cache avoids repeated dirty-page spills
            # during bulk projection. Journaling and synchronous durability stay
            # at their defaults; this database is published only after commit.
            conn.execute("pragma cache_size=-32768")
            _schema(conn, indexes=False)
            _project_history(conn, events)
            _indexes(conn)
            _stamp_snapshot(conn, root_repo, events, digest)
            conn.commit()
            if include_structure:
                from .structure_provider import refresh_structure_index

                refresh_structure_index(root_repo, conn=conn)
                conn.commit()
        finally:
            conn.close()
        os.replace(temp, paths.state)
        return paths.state
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _meta(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        conn = _connect(path)
        try:
            return {row["key"]: row["value"] for row in conn.execute("select key,value from meta")}
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return {}


def _validated_prefix_count(conn: sqlite3.Connection, events: list[dict[str, Any]]) -> int | None:
    meta = dict(conn.execute("select key,value from meta"))
    anchor = meta.get(VALIDATED_EVENT_DIGEST_META, "")
    if (meta.get("schema") != STATE_SCHEMA or not isinstance(anchor, str)
            or len(anchor) != 64 or any(c not in "0123456789abcdef" for c in anchor)):
        return None
    try:
        count = int(meta["event_count"])
    except (KeyError, TypeError, ValueError):
        return None
    if count < 0 or count > len(events):
        return None
    if meta.get("event_head") != (events[count - 1]["event_hash"] if count else ""):
        return None
    # Validate every stored sequence/hash against the strictly validated prefix,
    # not just a last-row hint. Holes, old chains and inconsistent metadata rebuild.
    seen = 0
    for seen, row in enumerate(conn.execute("select sequence,event_id,event_hash from events order by sequence"), 1):
        if (seen > count or row["sequence"] != seen or row["event_id"] != events[seen - 1]["event_id"]
                or row["event_hash"] != events[seen - 1]["event_hash"]):
            return None
    return count if seen == count else None


def ensure_state(repo: str | Path = ".", *, include_structure: bool = False) -> Path:
    root_repo = repo_root(repo)
    paths = continuity_paths(root_repo)
    with _state_lock(paths):
        # Read after acquiring the writer lock: an older waiter must never rewind
        # another materializer's newer snapshot. Hash ALL bytes and validate ALL
        # shapes, profiles, chain links, dedupe and ordered history references.
        events, digest = read_project_event_snapshot(paths.events)
        if paths.state.exists():
            conn = None
            try:
                conn = _connect(paths.state)
                # Keep lock acquisition failures visible, rather than replacing
                # a busy database behind another SQLite writer's back.
                conn.execute("begin immediate")
                count = _validated_prefix_count(conn, events)
                if count is not None:
                    for sequence in range(count, len(events)):
                        _project_event(conn, sequence + 1, events[sequence])
                    _stamp_snapshot(conn, root_repo, events, digest)
                    if include_structure:
                        from .structure_provider import refresh_structure_index, structure_index_needs_refresh

                        if structure_index_needs_refresh(root_repo, conn):
                            refresh_structure_index(root_repo, conn=conn)
                    conn.commit()
                    return paths.state
            except sqlite3.DatabaseError as exc:
                # Rebuild damaged schema/content, but never hide busy/locked,
                # disk-full or I/O errors behind an attempted file replacement.
                code = getattr(exc, "sqlite_errorcode", 0) & 0xff
                if code not in {sqlite3.SQLITE_ERROR, sqlite3.SQLITE_SCHEMA, sqlite3.SQLITE_CORRUPT,
                                sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CONSTRAINT}:
                    raise
            finally:
                if conn is not None:
                    conn.close()  # also rolls back failed suffix projection
        return _rebuild_snapshot(root_repo, paths, events, digest, include_structure=include_structure)


def state_status(repo: str | Path = ".") -> dict[str, Any]:
    root_repo = repo_root(repo)
    paths = continuity_paths(root_repo)
    events = read_project_events(paths.events)
    meta = _meta(paths.state)
    head = events[-1]["event_hash"] if events else ""
    counts: dict[str, int] = {}
    if paths.state.exists() and meta.get("schema") == STATE_SCHEMA:
        try:
            conn = _connect(paths.state)
            try:
                for table in ("entities", "relations", "changes", "proofs", "debts", "structure_symbols", "structure_edges"):
                    counts[table] = int(conn.execute(f"select count(*) from {table}").fetchone()[0])
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            counts = {}
    return {
        "schema": STATE_SCHEMA,
        "events_path": str(paths.events),
        "state_path": str(paths.state),
        "event_count": len(events),
        "event_head": head or None,
        "state_present": paths.state.exists(),
        "state_current": bool(meta) and meta.get("schema") == STATE_SCHEMA and meta.get("event_head") == head,
        "counts": counts,
        "structure_tree": meta.get("structure_tree") or None,
        "structure_dirty_warning": _working_tree_dirty(root_repo),
    }


def _working_tree_dirty(repo: Path) -> bool:
    try:
        return bool(git(repo, "--no-optional-locks", "status", "--porcelain=v1").strip())
    except Exception:
        return True


def query_rows(repo: str | Path, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    path = ensure_state(repo)
    conn = _connect(path)
    try:
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()
