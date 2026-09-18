"""Existing bounded Python AST facts, without storage, Git or identity allocation."""
from __future__ import annotations

import ast
import hashlib
from pathlib import PurePosixPath

from .structure_contract import FileExtraction, StructuralCall, StructuralImport, StructuralSymbol


def module_name(relative: str) -> str:
    parts = list(PurePosixPath(relative).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def extract_python(relative: str, content: bytes) -> FileExtraction:
    module = module_name(relative)
    source = dict(path=relative, language="python", provider="python-ast",
                  source_sha256=hashlib.sha256(content).hexdigest(), module=module)
    try:
        tree = ast.parse(content.decode("utf-8", errors="strict"))
    except (UnicodeError, SyntaxError, ValueError, RecursionError):
        return FileExtraction(**source, parsed=False)

    symbols = []
    imports = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else (
                "async-function" if isinstance(node, ast.AsyncFunctionDef) else "function")
            qname = f"{module}.{node.name}" if module else node.name
            symbols.append(StructuralSymbol(qname, kind, node.lineno, node.end_lineno,
                                            local_call_name=node.name))
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        kind = "async-method" if isinstance(child, ast.AsyncFunctionDef) else "method"
                        symbols.append(StructuralSymbol(f"{qname}.{child.name}", kind,
                                                        child.lineno, child.end_lineno))
        if isinstance(node, ast.Import):
            imports.extend(StructuralImport(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = module.split(".")[:-1] if module else []
                prefix = parts[:max(0, len(parts) - (node.level - 1))]
                if node.module:
                    prefix.extend(node.module.split("."))
                target = ".".join(prefix)
            else:
                target = node.module or ""
            if target:
                imports.append(StructuralImport(target))

    calls = tuple(StructuralCall(node.func.id, node.lineno) for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name))
    return FileExtraction(**source, parsed=True, symbols=tuple(symbols), imports=tuple(imports), calls=calls)
