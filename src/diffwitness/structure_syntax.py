"""Optional bounded syntax adapters; no project imports, execution, Git or storage."""
from __future__ import annotations

from bisect import bisect_right
import hashlib
import importlib
from importlib import metadata
import re
import time
import warnings

from .structure_contract import FileExtraction, StructuralCall, StructuralImport, StructuralSymbol
from .structure_sources import MAX_SOURCE_FILE_BYTES

PINNED = {'tree-sitter': '0.25.2', 'tree-sitter-javascript': '0.25.0', 'tree-sitter-typescript': '0.23.2',
          'tree-sitter-go': '0.25.0', 'tree-sitter-rust': '0.24.2'}
SPECS = {
    **{suffix: ('javascript', 'tree-sitter-javascript', 'tree_sitter_javascript', 'language')
       for suffix in ('.js', '.jsx', '.mjs', '.cjs')},
    **{suffix: ('typescript', 'tree-sitter-typescript', 'tree_sitter_typescript', 'language_typescript')
       for suffix in ('.ts', '.mts', '.cts')},
    '.tsx': ('typescript', 'tree-sitter-typescript', 'tree_sitter_typescript', 'language_tsx'),
    '.go': ('go', 'tree-sitter-go', 'tree_sitter_go', 'language'),
    '.rs': ('rust', 'tree-sitter-rust', 'tree_sitter_rust', 'language'),
}
MAX_NODES = 100000
MAX_PARSE_SECONDS = 0.25
MAX_PARSE_MICROS = 250000


def installed_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except (metadata.PackageNotFoundError, OSError, ValueError):
        return None


def extract_syntax(relative: str, content: bytes, spec: tuple[str, str, str, str]) -> FileExtraction:
    language, provider, package, entrypoint = spec
    source = dict(path=relative, language=language, provider=provider,
                  source_sha256=hashlib.sha256(content).hexdigest(), module=relative)
    empty = FileExtraction(**source, parsed=False)
    if len(content) > MAX_SOURCE_FILE_BYTES:
        return empty
    try:
        content.decode('utf-8', errors='strict')
        if any(installed_version(name) != PINNED[name] for name in ('tree-sitter', provider)):
            return empty
        runtime = importlib.import_module('tree_sitter')
        grammar = importlib.import_module(package)
        # 0.25.2 retains the native timeout API. Its deprecated callback
        # replacement crashes on supported older Python runtimes; do not invoke
        # a Python progress callback or remove the native parse-time bound.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            parser = runtime.Parser(runtime.Language(getattr(grammar, entrypoint)()),
                                    timeout_micros=MAX_PARSE_MICROS)
        deadline = time.monotonic() + MAX_PARSE_SECONDS
        tree = parser.parse(content)
        if tree is None or tree.root_node.has_error or time.monotonic() >= deadline:
            return empty
    except (ImportError, AttributeError, OSError, UnicodeError, ValueError, TypeError, RecursionError):
        return empty

    # Count named syntax nodes before retaining facts; malformed/error-recovered
    # trees never supply a partially successful result.
    nodes, pending = [], [tree.root_node]
    while pending:
        node = pending.pop()
        nodes.append(node)
        if len(nodes) > MAX_NODES:
            return empty
        pending.extend(reversed(node.named_children))
    starts = [0] + [match.end() for match in re.finditer(b'\r\n|\r|\n', content)]

    def text(node):
        return content[node.start_byte:node.end_byte].decode('utf-8') if node is not None else ''

    def line(offset):
        return bisect_right(starts, offset)

    symbols, imports, calls = [], [], []

    def symbol(node, name, kind, *, parent=None, callable_name=False):
        qualified = relative + '::' + (parent + '.' if parent else '') + name
        symbols.append(StructuralSymbol(qualified, kind, line(node.start_byte),
                                        line(max(node.start_byte, node.end_byte - 1)),
                                        local_call_name=name if callable_name else None))

    if language in {'go', 'rust'}:
        from .structure_native import native_declarations
        imports.extend(native_declarations(language, tree.root_node, text, symbol))
    else:
        declarations = {
            'function_declaration': 'function', 'generator_function_declaration': 'generator-function',
            'function_signature': 'function-signature',
            'class_declaration': 'class', 'abstract_class_declaration': 'class',
            'interface_declaration': 'interface', 'type_alias_declaration': 'type-alias',
            'enum_declaration': 'enum',
        }
        for statement in tree.root_node.named_children:
            declaration = statement
            while declaration is not None and declaration.type in {'export_statement', 'ambient_declaration'}:
                if declaration.type == 'export_statement':
                    declaration = declaration.child_by_field_name('declaration')
                else:
                    declaration = next((child for child in declaration.named_children if child.type != 'comment'), None)
            if declaration is not None:
                name = declaration.child_by_field_name('name')
                if declaration.type in declarations and name is not None:
                    kind = declarations[declaration.type]
                    if kind == 'function' and any(child.type == 'async' for child in declaration.children):
                        kind = 'async-function'
                    symbol(declaration, text(name), kind,
                           callable_name=kind in {'function', 'async-function', 'generator-function'})
                    if kind == 'class':
                        body = declaration.child_by_field_name('body')
                        for member in body.named_children if body is not None else ():
                            member_name = member.child_by_field_name('name')
                            if (member.type in {'method_definition', 'method_signature', 'abstract_method_signature'} and member_name is not None
                                    and member_name.type in {'property_identifier', 'private_property_identifier'}):
                                member_kind = 'async-method' if any(child.type == 'async' for child in member.children) else 'method'
                                if member.type != 'method_definition':
                                    member_kind += '-signature'
                                symbol(member, text(member_name), member_kind, parent=text(name))
                elif declaration.type in {'lexical_declaration', 'variable_declaration'}:
                    for variable in declaration.named_children:
                        name, value = variable.child_by_field_name('name'), variable.child_by_field_name('value')
                        if (name is not None and name.type == 'identifier' and value is not None
                                and value.type in {'arrow_function', 'function_expression', 'generator_function'}):
                            kind = 'async-function' if any(child.type == 'async' for child in value.children) else 'function'
                            symbol(variable, text(name), kind, callable_name=True)
            if statement.type in {'import_statement', 'export_statement'}:
                target = statement.child_by_field_name('source')
                if target is None and statement.type == 'import_statement':
                    clause = next((n for n in statement.named_children if n.type == 'import_require_clause'), None)
                    target = clause.child_by_field_name('source') if clause is not None else None
                raw = text(target)
                # Escaped module specifiers need language-specific decoding. Leave
                # them unresolved rather than inventing a normalized dependency.
                if target is not None and target.type == 'string' and len(raw) > 2 and '\\' not in raw:
                    imports.append(StructuralImport(raw[1:-1]))
    for node in nodes:
        if node.type == 'call_expression':
            function = node.child_by_field_name('function')
            if function is not None and function.type == 'identifier':
                calls.append(StructuralCall(text(function), line(node.start_byte)))
    if any(len(value) > 8192 for value in
           [s.qualified_name for s in symbols] + [i.target for i in imports] + [c.name for c in calls]):
        return empty
    if len({(symbol.qualified_name, symbol.kind) for symbol in symbols}) != len(symbols):
        # Existing materialized identities have one row per qualified name/kind.
        # Do not silently pick a binding when the syntax declares that key twice.
        return empty
    return FileExtraction(**source, parsed=True, symbols=tuple(symbols), imports=tuple(imports), calls=tuple(calls))
