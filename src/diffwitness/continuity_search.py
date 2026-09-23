"""Disposable lexical index using the existing context tokenization and graph scope."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Iterable

SEARCHABLE_KINDS = ("objective", "task", "decision", "invariant", "failed-approach", "component", "file")
_WORD = re.compile(r"[A-Za-z0-9]+")
_ACTIVE = "e.lifecycle='active' and e.kind in ('objective','task','decision','invariant','failed-approach','component','file')"


def tokens(value: str) -> set[str]:
    text = value or ""
    if not text.isascii():
        import unicodedata

        # Lexical recall only: stored assertions and literal entity identities
        # remain untouched. NFKD also folds compatibility forms such as full-width
        # letters; French œ/æ need explicit expansion in addition to Unicode folding.
        text = unicodedata.normalize("NFKD", text.casefold().replace("œ", "oe").replace("æ", "ae"))
        text = "".join(char for char in text if not unicodedata.combining(char))
    return {word.lower() for word in _WORD.findall(text) if len(word) >= 3}


def memory_text(kind: str, identity: str, label: str | None, payload: dict[str, Any]) -> str:
    # A native task digest is identity metadata, not searchable intent.
    detail = str(payload.get("why") or "") if kind == "task" else json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return " ".join([str(label or ""), identity, detail])


def select_context_entities(conn: sqlite3.Connection, task: str, components: Iterable[str]) -> list[sqlite3.Row]:
    # Request terms stay in this connection's memory; no user query enters durable state.
    conn.execute("pragma temp_store=memory")
    for table, column in (("_dw_terms", "term"), ("_dw_exact", "entity_id"), ("_dw_components", "entity_id"),
                          ("_dw_seeds", "entity_id"), ("_dw_candidates", "entity_id")):
        conn.execute(f"create temp table if not exists {table}({column} text primary key)")
        conn.execute(f"delete from {table}")
    conn.executemany("insert or ignore into _dw_terms(term) values(?)", ((term,) for term in tokens(task)))
    conn.executemany("insert or ignore into _dw_exact(entity_id) values(?)", ((identity,) for identity in task.split()))
    conn.executemany("insert or ignore into _dw_components(entity_id) values(?)", ((identity,) for identity in components))
    conn.execute(f"""insert or ignore into _dw_seeds
        select e.entity_id from _dw_terms q cross join entity_terms t indexed by entity_terms_term_idx
        cross join entities e where t.term=q.term and e.entity_id=t.entity_id and {_ACTIVE}""")
    conn.execute(f"insert or ignore into _dw_seeds select e.entity_id from entities e where {_ACTIVE} and e.critical=1")
    conn.execute(f"insert or ignore into _dw_seeds select e.entity_id from _dw_exact q cross join entities e where e.entity_id=q.entity_id and {_ACTIVE}")
    for source, target in (("source_id", "target_id"), ("target_id", "source_id")):
        conn.execute(f"""insert or ignore into _dw_seeds
            select e.entity_id from _dw_components c cross join active_memory_relations r
            cross join entities e where r.{target}=c.entity_id and e.entity_id=r.{source} and {_ACTIVE}""")
    # The complete two-hop neighborhood is admitted. Ranking still decides relevance/depth;
    # no arbitrary candidate truncation can erase a low lexical seed's graph connection.
    conn.execute(f"""with recursive reach(entity_id,depth) as (
        select entity_id,0 from _dw_seeds
        union
        select e.entity_id,reach.depth+1 from reach
        cross join active_memory_relations r cross join entities e
        where (r.source_id=reach.entity_id or r.target_id=reach.entity_id)
        and e.entity_id=case when r.source_id=reach.entity_id then r.target_id else r.source_id end
        and reach.depth<2 and {_ACTIVE}
        ) insert or ignore into _dw_candidates select entity_id from reach""")
    return conn.execute("""select e.*,m.lifecycle_json from _dw_candidates c
        cross join entities e left join memory_lifecycle m on m.entity_id=e.entity_id
        where e.entity_id=c.entity_id order by e.updated_at desc""").fetchall()
