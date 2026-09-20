"""Bounded JS/TS literal import-call references over the existing syntax tree."""
from __future__ import annotations

from bisect import bisect_right


def _require_ambiguous(nodes, text):
    # A whole-file conservative barrier avoids claiming lexical resolution we
    # have not implemented. Merge binding/write spans once; do not recursively
    # rescan nested binding subtrees or execute default values.
    fields = {
        'variable_declarator': ('name',), 'function_declaration': ('name',),
        'function_signature': ('name',),
        'generator_function_declaration': ('name',), 'function_expression': ('name',),
        'generator_function': ('name',), 'class_declaration': ('name',),
        'abstract_class_declaration': ('name',), 'class': ('name',),
        'arrow_function': ('parameter',), 'catch_clause': ('parameter',),
        'assignment_expression': ('left',), 'augmented_assignment_expression': ('left',),
        'update_expression': ('argument',), 'for_in_statement': ('left',),
        'enum_declaration': ('name',), 'internal_module': ('name',),
    }
    spans = []
    for node in nodes:
        if node.type == 'with_statement' or (node.type == 'identifier' and text(node) == 'eval'):
            return True
        roots = [node] if node.type in {'formal_parameters', 'import_statement'} else [
            node.child_by_field_name(field) for field in fields.get(node.type, ())]
        spans.extend((root.start_byte, root.end_byte) for root in roots if root is not None)
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    starts = [start for start, _ in merged]
    for node in nodes:
        if node.type not in {'identifier', 'shorthand_property_identifier_pattern', 'type_identifier'}:
            continue
        value = text(node)
        if value != 'require' and '\\' not in value:
            continue
        index = bisect_right(starts, node.start_byte) - 1
        if index >= 0 and node.end_byte <= merged[index][1]:
            return True
    return False


def _literal_target(node, text):
    while node is not None and node.type == 'parenthesized_expression':
        children = [child for child in node.named_children if child.type != 'comment']
        node = children[0] if len(children) == 1 else None
    if node is None or node.type not in {'string', 'template_string'}:
        return None
    raw = text(node)
    if len(raw) <= 2 or '\\' in raw:
        return None
    if node.type == 'template_string' and (
            any(child.type == 'template_substitution' for child in node.named_children)
            or '\r' in raw or '\n' in raw):
        return None
    return raw[1:-1]


def javascript_import_calls(nodes, text, reference):
    ambiguous = _require_ambiguous(nodes, text)
    imports = []
    for node in nodes:
        if node.type != 'call_expression':
            continue
        function = node.child_by_field_name('function')
        arguments = node.child_by_field_name('arguments')
        if function is None or arguments is None:
            continue
        keyword = function.type == 'import'
        commonjs = function.type == 'identifier' and text(function) == 'require' and not ambiguous
        if not (keyword or commonjs) or any(child.type == 'optional_chain' for child in node.children):
            continue
        args = [child for child in arguments.named_children if child.type != 'comment']
        if len(args) not in ((1, 2) if keyword else (1,)):
            continue
        target = _literal_target(args[0], text)
        if target:
            imports.append(reference(node, target))
    return imports
