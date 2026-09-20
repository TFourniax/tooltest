from __future__ import annotations

import hashlib
import json
import posixpath
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .gitops import git, repo_root
from .structure_sources import SNAPSHOT_VERSION, tree_sources
from .structure_contract import EXTRACTION_VERSION
from .structure_registry import SUPPORTED_SUFFIXES, extract_structure, provider_profile


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
    meta = dict(conn.execute("select key,value from meta where key in ('structure_tree','structure_snapshot_version','structure_extraction_version','structure_provider_profile')"))
    return (meta.get("structure_tree") != _head_tree(root)
            or meta.get("structure_snapshot_version") != SNAPSHOT_VERSION
            or meta.get("structure_extraction_version") != EXTRACTION_VERSION
            or meta.get("structure_provider_profile") != provider_profile())


def _syntax_import_component(relative: str, target: str, components: dict[str, str]) -> str | None:
    if not target.startswith('.') or '\\' in target or ':' in target:
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
    if base == '..' or base.startswith('../') or base.startswith('/'):
        return None
    candidates = [base]
    suffixes = ('.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts')
    if posixpath.splitext(base)[1] not in suffixes:
        candidates += [base + suffix for suffix in suffixes]
        candidates += [base + '/index' + suffix for suffix in suffixes]
    matches = {components[path] for path in candidates
               if path in components and posixpath.splitext(path)[1] in suffixes}
    return next(iter(matches)) if len(matches) == 1 else None


def refresh_structure_index(repo: str | Path, *, conn: sqlite3.Connection, max_files: int = 2000) -> dict:
    root = repo_root(repo)
    tree = _head_tree(root)
    indexed_at = _now()
    profile = provider_profile()
    files, coverage = tree_sources(root, tree, suffixes=SUPPORTED_SUFFIXES, max_files=max_files)
    extracted = []
    # Admission finishes before any destructive write to the previous projection.
    for relative, content in files:
        result = extract_structure(relative, content)
        extracted.append(result)
    conn.execute("delete from structure_edges")
    conn.execute("delete from structure_symbols")
    conn.execute("delete from structure_components")

    components = {item.path: component_id_for_path(item.path) for item in extracted}
    modules = {}
    for item in extracted:
        if item.module:
            modules.setdefault((item.language, item.module), set()).add(components[item.path])
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
            matches = modules.get((item.language, imported.target), set())
            target = (next(iter(matches)) if item.language == 'python' and len(matches) == 1 else
                      _syntax_import_component(item.path, imported.target, components)
                      if item.language in {'javascript', 'typescript'} else None)
            authority = 'INFERRED' if target else imported.epistemic_status
            kind = "component" if target else "module-reference"
            target = target or f"module:{imported.target}"
            conn.execute(
                "insert or ignore into structure_edges(edge_id,source_id,predicate,target_id,target_kind,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?,?)",
                (_id("dwedge", source, "imports", target), source, "imports", target, kind,
                 authority, item.provider, tree or None, indexed_at),
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
    coverage["providerProfile"] = json.loads(profile)
    meta = {
        "structure_tree": tree, "structure_provider": "shared-structure",
        "structure_provider_profile": profile,
        "structure_indexed_at": indexed_at, "structure_file_count": str(len(files)),
        "structure_snapshot_version": SNAPSHOT_VERSION,
        "structure_extraction_version": EXTRACTION_VERSION,
        "structure_coverage": json.dumps(coverage, sort_keys=True),
    }
    conn.executemany("insert into meta(key,value) values(?,?) on conflict(key) do update set value=excluded.value", meta.items())
    return {**coverage, "parsed": sum(item.parsed for item in extracted), "edges": edge_count, "tree": tree}
