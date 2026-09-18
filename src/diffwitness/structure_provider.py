from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .gitops import git, repo_root
from .structure_sources import SNAPSHOT_VERSION, tree_sources
from .structure_contract import EXTRACTION_VERSION, validate_extraction
from .structure_python import extract_python, module_name as _module_name


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _id(prefix: str, *parts: str) -> str:
    raw = "\0".join(parts).encode("utf-8")
    return f"{prefix}_" + hashlib.sha256(raw).hexdigest()[:24]


def component_id_for_path(relative_path: str) -> str:
    """Stable provider-neutral component identity for one repository path."""
    normalized = str(relative_path).replace("\\", "/").removeprefix("./")
    return _id("dwcomp", normalized)


def _head_tree(repo: Path) -> str:
    try:
        return git(repo, "rev-parse", "HEAD^{tree}").strip()
    except Exception:
        return ""


def structure_index_needs_refresh(repo: str | Path, conn: sqlite3.Connection) -> bool:
    return _structure_index_needs_refresh(repo_root(repo), conn)


def _structure_index_needs_refresh(root: Path, conn: sqlite3.Connection) -> bool:
    meta = dict(conn.execute("select key,value from meta where key in ('structure_tree','structure_snapshot_version','structure_extraction_version')"))
    return (meta.get("structure_tree") != _head_tree(root)
            or meta.get("structure_snapshot_version") != SNAPSHOT_VERSION
            or meta.get("structure_extraction_version") != EXTRACTION_VERSION)


def refresh_structure_index(repo: str | Path, *, conn: sqlite3.Connection, max_files: int = 2000) -> dict:
    root = repo_root(repo)
    tree = _head_tree(root)
    indexed_at = _now()
    files, coverage = tree_sources(root, tree, suffixes=(".py",), max_files=max_files)
    extracted = []
    # Admission finishes before any destructive write to the previous projection.
    for relative, content in files:
        result = extract_python(relative, content)
        validate_extraction(result, relative, content, language="python", provider="python-ast")
        extracted.append(result)
    conn.execute("delete from structure_edges")
    conn.execute("delete from structure_symbols")
    conn.execute("delete from structure_components")

    components = {item.path: component_id_for_path(item.path) for item in extracted}
    modules = {(item.language, item.module): components[item.path] for item in extracted if item.module}
    local_symbols = {}
    for item in extracted:
        component = components[item.path]
        conn.execute(
            "insert into structure_components(component_id,path,language,module_name,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?)",
            (component, item.path, item.language, item.module or None, "OBSERVED", item.provider, tree or None, indexed_at),
        )
        if not item.parsed:
            coverage["unparsed"] += 1
        for symbol in item.symbols:
            identity = _id("dwsym", item.language, item.path, symbol.qualified_name, symbol.kind)
            if symbol.local_call_name is not None:
                local_symbols[(component, symbol.local_call_name)] = identity
            conn.execute(
                "insert into structure_symbols(symbol_id,component_id,path,qualified_name,symbol_kind,language,line,end_line,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                (identity, component, item.path, symbol.qualified_name, symbol.kind, item.language,
                 symbol.line, symbol.end_line, symbol.epistemic_status, item.provider, tree or None, indexed_at),
            )

    edge_count = 0
    for item in extracted:
        source = components[item.path]
        for imported in item.imports:
            target = modules.get((item.language, imported.target))
            kind = "component" if target else "external-module"
            target = target or f"module:{imported.target}"
            conn.execute(
                "insert or ignore into structure_edges(edge_id,source_id,predicate,target_id,target_kind,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?,?)",
                (_id("dwedge", source, "imports", target), source, "imports", target, kind,
                 imported.epistemic_status, item.provider, tree or None, indexed_at),
            )
            edge_count += 1
        for call in item.calls:
            target = local_symbols.get((source, call.name))
            if target is None:
                continue
            conn.execute(
                "insert or ignore into structure_edges(edge_id,source_id,predicate,target_id,target_kind,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?,?)",
                (_id("dwedge", source, "calls-name", target, str(call.line)), source, "calls-name", target,
                 "symbol", call.epistemic_status, item.provider, tree or None, indexed_at),
            )
            edge_count += 1

    coverage["complete"] = coverage["complete"] and coverage["unparsed"] == 0
    coverage["extractionVersion"] = EXTRACTION_VERSION
    meta = {
        "structure_tree": tree, "structure_provider": "python-ast",
        "structure_indexed_at": indexed_at, "structure_file_count": str(len(files)),
        "structure_snapshot_version": SNAPSHOT_VERSION,
        "structure_extraction_version": EXTRACTION_VERSION,
        "structure_coverage": json.dumps(coverage, sort_keys=True),
    }
    conn.executemany("insert into meta(key,value) values(?,?) on conflict(key) do update set value=excluded.value", meta.items())
    return {**coverage, "parsed": sum(item.parsed for item in extracted), "edges": edge_count, "tree": tree}
