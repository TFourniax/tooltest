from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .continuity_events import continuity_paths, read_project_events
from .gitops import git, repo_root

STATE_SCHEMA = "continuity-state-1"
_STATUS_RANK = {"DECLARED": 1, "INFERRED": 2, "OBSERVED": 3, "VERIFIED": 4}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys=on")
    conn.execute("pragma busy_timeout=5000")
    return conn


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
        create index events_type_idx on events(event_type, sequence desc);
        create index events_subject_idx on events(subject_id, sequence desc);

        create table entities(
          entity_id text primary key,
          kind text not null,
          label text,
          epistemic_status text not null,
          lifecycle text not null default 'active',
          updated_at text not null,
          payload_json text not null,
          provenance_json text not null,
          source_event_id text not null
        );
        create index entities_kind_idx on entities(kind, lifecycle, updated_at desc);

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
        create index relations_source_idx on relations(source_id, predicate);
        create index relations_target_idx on relations(target_id, predicate);

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
        create index changes_updated_idx on changes(updated_at desc);

        create table proofs(
          certificate_id text primary key,
          change_id text not null,
          claim text not null,
          accepted integer not null,
          epistemic_status text not null,
          source_event_id text not null,
          updated_at text not null
        );
        create index proofs_change_idx on proofs(change_id, updated_at desc);

        create table debts(
          debt_id text primary key,
          status text not null,
          introduced_change_id text,
          last_change_id text,
          epistemic_status text not null,
          source_event_id text not null,
          updated_at text not null
        );
        create index debts_status_idx on debts(status, updated_at desc);
        create index debts_change_idx on debts(last_change_id);

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
        create index structure_components_module_idx on structure_components(module_name);

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
        create index structure_symbols_name_idx on structure_symbols(qualified_name);
        create index structure_symbols_path_idx on structure_symbols(path);

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
        create index structure_edges_source_idx on structure_edges(source_id, predicate);
        create index structure_edges_target_idx on structure_edges(target_id, predicate);
        """
    )


def _relation_id(source_id: str, predicate: str, target_id: str) -> str:
    import hashlib
    seed = f"{source_id}\0{predicate}\0{target_id}".encode("utf-8")
    return "dwrel_" + hashlib.sha256(seed).hexdigest()[:24]


def _lifecycle(event_type: str, payload: dict[str, Any]) -> str:
    if event_type.endswith((".superseded", ".retired", ".resolved")):
        return "inactive"
    explicit = payload.get("lifecycle")
    return explicit if explicit in {"active", "inactive"} else "active"


def _upsert_entity(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    subject = event["subject"]
    entity_id = str(subject["id"])
    existing = conn.execute("select epistemic_status from entities where entity_id=?", (entity_id,)).fetchone()
    status = event["epistemic_status"]
    if existing and _STATUS_RANK.get(existing["epistemic_status"], 0) > _STATUS_RANK.get(status, 0):
        status = existing["epistemic_status"]
    payload = event.get("payload") or {}
    conn.execute(
        """insert into entities(entity_id,kind,label,epistemic_status,lifecycle,updated_at,payload_json,provenance_json,source_event_id)
           values(?,?,?,?,?,?,?,?,?)
           on conflict(entity_id) do update set
             kind=excluded.kind,label=coalesce(excluded.label,entities.label),epistemic_status=excluded.epistemic_status,
             lifecycle=excluded.lifecycle,updated_at=excluded.updated_at,payload_json=excluded.payload_json,
             provenance_json=excluded.provenance_json,source_event_id=excluded.source_event_id""",
        (
            entity_id, subject["kind"], subject.get("label"), status,
            _lifecycle(event["event_type"], payload), event["timestamp"], _canonical(payload),
            _canonical(event.get("provenance") or {}), event["event_id"],
        ),
    )


def _upsert_relations(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    source = str(event["subject"]["id"])
    for relation in event.get("relations") or []:
        target = relation["target"]
        rid = _relation_id(source, relation["predicate"], target["id"])
        status = relation.get("epistemic_status") or event["epistemic_status"]
        existing = conn.execute("select epistemic_status from relations where relation_id=?", (rid,)).fetchone()
        if existing and _STATUS_RANK.get(existing["epistemic_status"], 0) > _STATUS_RANK.get(status, 0):
            status = existing["epistemic_status"]
        conn.execute(
            """insert into relations(relation_id,source_id,predicate,target_id,target_kind,epistemic_status,lifecycle,metadata_json,source_event_id,updated_at)
               values(?,?,?,?,?,?,?,?,?,?)
               on conflict(relation_id) do update set
                 target_kind=excluded.target_kind,epistemic_status=excluded.epistemic_status,lifecycle=excluded.lifecycle,
                 metadata_json=excluded.metadata_json,source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (rid, source, relation["predicate"], target["id"], target["kind"], status, "active",
             _canonical(relation.get("metadata") or {}), event["event_id"], event["timestamp"]),
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
            (subject_id, str(payload.get("repository_fingerprint") or ""), str(payload.get("base_tree") or ""),
             str(payload.get("candidate_tree") or ""), payload.get("base_sha"), payload.get("candidate_sha"),
             _canonical(event.get("actor") or {}), _canonical(payload.get("changed_files") or []), event["timestamp"], event["event_id"]),
        )
    elif kind == "proof.completed":
        change_id = str(payload.get("change_id") or "")
        conn.execute(
            """insert into proofs(certificate_id,change_id,claim,accepted,epistemic_status,source_event_id,updated_at)
               values(?,?,?,?,?,?,?)
               on conflict(certificate_id) do update set change_id=excluded.change_id,claim=excluded.claim,accepted=excluded.accepted,
                 epistemic_status=excluded.epistemic_status,source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (subject_id, change_id, str(payload.get("claim") or "unknown"), 1 if payload.get("accepted") else 0,
             event["epistemic_status"], event["event_id"], event["timestamp"]),
        )
    elif kind == "debt.observed":
        change_id = payload.get("change_id")
        conn.execute(
            """insert into debts(debt_id,status,introduced_change_id,last_change_id,epistemic_status,source_event_id,updated_at)
               values(?,?,?,?,?,?,?)
               on conflict(debt_id) do update set status='open',last_change_id=excluded.last_change_id,
                 epistemic_status=excluded.epistemic_status,source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (subject_id, "open", change_id, change_id, event["epistemic_status"], event["event_id"], event["timestamp"]),
        )
    elif kind == "debt.resolved":
        conn.execute("update debts set status='resolved',last_change_id=?,source_event_id=?,updated_at=? where debt_id=?",
                     (payload.get("change_id"), event["event_id"], event["timestamp"], subject_id))
    elif kind == "debt.snapshot":
        change_id = str(payload.get("change_id") or subject_id)
        budget = payload.get("budget_passed")
        conn.execute(
            """insert into debt_snapshots(change_id,points,obligations,budget_passed,source_event_id,updated_at)
               values(?,?,?,?,?,?)
               on conflict(change_id) do update set points=excluded.points,obligations=excluded.obligations,
                 budget_passed=excluded.budget_passed,source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (change_id, int(payload.get("points") or 0), int(payload.get("obligations") or 0),
             None if budget is None else (1 if budget else 0), event["event_id"], event["timestamp"]),
        )
    elif kind == "understanding.recorded":
        change_id = str(payload.get("change_id") or subject_id)
        conn.execute(
            """insert into understanding(change_id,coverage,knowledge_debt,feature_coverage,feature_debt,receipt_digest,source_event_id,updated_at)
               values(?,?,?,?,?,?,?,?)
               on conflict(change_id) do update set coverage=excluded.coverage,knowledge_debt=excluded.knowledge_debt,
                 feature_coverage=excluded.feature_coverage,feature_debt=excluded.feature_debt,receipt_digest=excluded.receipt_digest,
                 source_event_id=excluded.source_event_id,updated_at=excluded.updated_at""",
            (change_id, payload.get("coverage"), payload.get("knowledge_debt"), payload.get("feature_coverage"),
             payload.get("feature_debt"), payload.get("receipt_digest"), event["event_id"], event["timestamp"]),
        )


def rebuild_state(repo: str | Path = ".", *, include_structure: bool = False) -> Path:
    root_repo = repo_root(repo)
    paths = continuity_paths(root_repo)
    events = read_project_events(paths.events)
    paths.root.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="state-", suffix=".db", dir=paths.root)
    os.close(fd)
    temp = Path(temp_name)
    try:
        conn = _connect(temp)
        try:
            _schema(conn)
            for sequence, event in enumerate(events, start=1):
                conn.execute(
                    "insert into events(sequence,event_id,event_type,timestamp,epistemic_status,subject_id,subject_kind,event_hash,payload_json,provenance_json) values(?,?,?,?,?,?,?,?,?,?)",
                    (sequence, event["event_id"], event["event_type"], event["timestamp"], event["epistemic_status"],
                     event["subject"]["id"], event["subject"]["kind"], event["event_hash"],
                     _canonical(event.get("payload") or {}), _canonical(event.get("provenance") or {})),
                )
                _upsert_entity(conn, event)
                _upsert_relations(conn, event)
                _specialized(conn, event)
            conn.execute("insert into meta(key,value) values('schema',?)", (STATE_SCHEMA,))
            conn.execute("insert into meta(key,value) values('event_count',?)", (str(len(events)),))
            conn.execute("insert into meta(key,value) values('event_head',?)", (events[-1]["event_hash"] if events else "",))
            conn.execute("insert into meta(key,value) values('repository_root',?)", (str(root_repo),))
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


def ensure_state(repo: str | Path = ".", *, include_structure: bool = False) -> Path:
    root_repo = repo_root(repo)
    paths = continuity_paths(root_repo)
    events = read_project_events(paths.events)
    expected_head = events[-1]["event_hash"] if events else ""
    meta = _meta(paths.state)
    if meta.get("schema") != STATE_SCHEMA or meta.get("event_head") != expected_head:
        return rebuild_state(root_repo, include_structure=include_structure)
    if include_structure:
        conn = _connect(paths.state)
        try:
            from .structure_provider import structure_index_needs_refresh, refresh_structure_index
            if structure_index_needs_refresh(root_repo, conn):
                refresh_structure_index(root_repo, conn=conn)
                conn.commit()
        finally:
            conn.close()
    return paths.state


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
        return bool(git(repo, "status", "--porcelain=v1").strip())
    except Exception:
        return True


def query_rows(repo: str | Path, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    path = ensure_state(repo)
    conn = _connect(path)
    try:
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()
