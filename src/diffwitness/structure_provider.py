from __future__ import annotations

import ast
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .gitops import git, repo_root


_EXCLUDED_DIRS = {'.git','.venv','venv','node_modules','dist','build','.tox','.mypy_cache','.pytest_cache','__pycache__'}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


def _id(prefix: str, *parts: str) -> str:
    raw='\0'.join(parts).encode('utf-8')
    return f"{prefix}_" + hashlib.sha256(raw).hexdigest()[:24]


def _head_tree(repo: Path) -> str:
    try:
        return git(repo,'rev-parse','HEAD^{tree}').strip()
    except Exception:
        return ''


def _python_files(repo: Path, limit: int = 2000) -> list[Path]:
    files=[]
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS and not d.startswith('.')]
        for name in names:
            if not name.endswith('.py'):
                continue
            path=Path(root)/name
            files.append(path)
            if len(files)>=limit:
                return sorted(files)
    return sorted(files)


def _module_name(relative: str) -> str:
    p=PurePosixPath(relative)
    parts=list(p.with_suffix('').parts)
    if parts and parts[-1]=='__init__':
        parts=parts[:-1]
    return '.'.join(parts)


def structure_index_needs_refresh(repo: str | Path, conn: sqlite3.Connection) -> bool:
    root=repo_root(repo)
    row=conn.execute("select value from meta where key='structure_tree'").fetchone()
    current=_head_tree(root)
    return row is None or str(row[0]) != current


def refresh_structure_index(repo: str | Path, *, conn: sqlite3.Connection, max_files: int = 2000) -> dict[str,int|str]:
    root=repo_root(repo)
    tree=_head_tree(root)
    indexed_at=_now()
    conn.execute('delete from structure_edges')
    conn.execute('delete from structure_symbols')
    conn.execute('delete from structure_components')

    parsed: dict[str, ast.AST] = {}
    module_to_component: dict[str,str] = {}
    path_to_component: dict[str,str] = {}
    files=_python_files(root,limit=max_files)
    for path in files:
        rel=path.relative_to(root).as_posix()
        module=_module_name(rel)
        component_id=_id('dwcomp','python',rel)
        path_to_component[rel]=component_id
        if module:
            module_to_component[module]=component_id
        conn.execute(
            "insert into structure_components(component_id,path,language,module_name,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?)",
            (component_id,rel,'python',module or None,'OBSERVED','python-ast',tree or None,indexed_at),
        )
        try:
            parsed[rel]=ast.parse(path.read_text(encoding='utf-8',errors='strict'))
        except (OSError,UnicodeError,SyntaxError,ValueError):
            continue

    symbols_by_component_name: dict[tuple[str,str],str] = {}
    for rel, tree_ast in parsed.items():
        component_id=path_to_component[rel]
        module=_module_name(rel)
        for node in tree_ast.body:
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                continue
            kind='class' if isinstance(node,ast.ClassDef) else ('async-function' if isinstance(node,ast.AsyncFunctionDef) else 'function')
            qname=f"{module}.{node.name}" if module else node.name
            symbol_id=_id('dwsym','python',rel,qname,kind)
            symbols_by_component_name[(component_id,node.name)]=symbol_id
            conn.execute(
                "insert into structure_symbols(symbol_id,component_id,path,qualified_name,symbol_kind,language,line,end_line,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                (symbol_id,component_id,rel,qname,kind,'python',getattr(node,'lineno',None),getattr(node,'end_lineno',None),'OBSERVED','python-ast',tree or None,indexed_at),
            )
            if isinstance(node,ast.ClassDef):
                for child in node.body:
                    if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        ck='async-method' if isinstance(child,ast.AsyncFunctionDef) else 'method'
                        cq=f"{qname}.{child.name}"
                        cid=_id('dwsym','python',rel,cq,ck)
                        conn.execute(
                            "insert into structure_symbols(symbol_id,component_id,path,qualified_name,symbol_kind,language,line,end_line,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (cid,component_id,rel,cq,ck,'python',getattr(child,'lineno',None),getattr(child,'end_lineno',None),'OBSERVED','python-ast',tree or None,indexed_at),
                        )

    edge_count=0
    for rel, tree_ast in parsed.items():
        source=path_to_component[rel]
        current_module=_module_name(rel)
        for node in tree_ast.body:
            targets: list[str] = []
            if isinstance(node,ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node,ast.ImportFrom):
                base=''
                if node.level:
                    parts=current_module.split('.')[:-1] if current_module else []
                    keep=max(0,len(parts)-(node.level-1))
                    prefix=parts[:keep]
                    if node.module:
                        prefix.extend(node.module.split('.'))
                    base='.'.join(prefix)
                else:
                    base=node.module or ''
                if base:
                    targets.append(base)
            for target in targets:
                target_id=module_to_component.get(target)
                target_kind='component' if target_id else 'external-module'
                resolved=target_id or f"module:{target}"
                eid=_id('dwedge',source,'imports',resolved)
                conn.execute(
                    "insert or ignore into structure_edges(edge_id,source_id,predicate,target_id,target_kind,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?,?)",
                    (eid,source,'imports',resolved,target_kind,'OBSERVED','python-ast',tree or None,indexed_at),
                )
                edge_count+=1

        for node in ast.walk(tree_ast):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name):
                continue
            target_symbol=symbols_by_component_name.get((source,node.func.id))
            if not target_symbol:
                continue
            eid=_id('dwedge',source,'calls-name',target_symbol,str(getattr(node,'lineno',0)))
            conn.execute(
                "insert or ignore into structure_edges(edge_id,source_id,predicate,target_id,target_kind,epistemic_status,provider,tree_sha,indexed_at) values(?,?,?,?,?,?,?,?,?)",
                (eid,source,'calls-name',target_symbol,'symbol','INFERRED','python-ast',tree or None,indexed_at),
            )
            edge_count+=1

    conn.execute("insert into meta(key,value) values('structure_tree',?) on conflict(key) do update set value=excluded.value",(tree,))
    conn.execute("insert into meta(key,value) values('structure_provider',?) on conflict(key) do update set value=excluded.value",('python-ast',))
    conn.execute("insert into meta(key,value) values('structure_indexed_at',?) on conflict(key) do update set value=excluded.value",(indexed_at,))
    conn.execute("insert into meta(key,value) values('structure_file_count',?) on conflict(key) do update set value=excluded.value",(str(len(files)),))
    return {'files':len(files),'parsed':len(parsed),'edges':edge_count,'tree':tree}
