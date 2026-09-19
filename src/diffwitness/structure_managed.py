"""Java/Kotlin/C# facts over the shared admitted syntax tree."""
from __future__ import annotations

from .structure_contract import StructuralImport


def _qualified(node, text):
    if node is None:
        return None
    parts, pending = [], [node]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            parts.append(current)
        elif current.type in {'identifier', 'type_identifier'}:
            parts.append(text(current))
        elif current.type in {'scoped_identifier', 'qualified_name', 'alias_qualified_name'}:
            left = (current.child_by_field_name('scope') or current.child_by_field_name('qualifier')
                    or current.child_by_field_name('alias'))
            right = current.child_by_field_name('name')
            if left is None or right is None:
                return None
            pending.extend([right, '::' if current.type == 'alias_qualified_name' else '.', left])
        elif current.type == 'qualified_identifier':
            children = [child for child in current.named_children if 'comment' not in child.type]
            if not children or any(child.type != 'identifier' for child in children):
                return None
            for index, child in enumerate(reversed(children)):
                if index:
                    pending.append('.')
                pending.append(child)
        else:
            return None
    return ''.join(parts) if parts else None


def managed_declarations(language, root, text, symbol):
    imports, package = [], None
    for node in root.named_children:
        if node.type in {'package_declaration', 'package_header'}:
            package = next((_qualified(child, text) for child in node.named_children
                            if child.type in {'identifier', 'scoped_identifier', 'qualified_identifier'}), None)
        elif node.type == 'file_scoped_namespace_declaration':
            package = _qualified(node.child_by_field_name('name'), text)

    kinds = {'class_declaration': 'class', 'interface_declaration': 'interface',
             'enum_declaration': 'enum', 'record_declaration': 'record',
             'annotation_type_declaration': 'annotation', 'struct_declaration': 'struct',
             'delegate_declaration': 'delegate', 'object_declaration': 'object', 'type_alias': 'type-alias'}
    pending = [(child, package, False) for child in reversed(root.named_children)]
    while pending:
        node, prefix, in_type = pending.pop()
        name = node.child_by_field_name('name')
        if node.type == 'type_alias':
            name = node.child_by_field_name('type')
        if node.type in kinds and name is not None:
            kind = kinds[node.type]
            if language == 'kotlin' and node.type == 'class_declaration':
                tokens = {child.type for child in node.children}
                for modifiers in (child for child in node.named_children if child.type == 'modifiers'):
                    for modifier in modifiers.named_children:
                        if modifier.type == 'class_modifier':
                            tokens.update(child.type for child in modifier.children)
                kind = 'interface' if 'interface' in tokens else 'enum' if 'enum' in tokens else 'annotation' if 'annotation' in tokens else kind
            symbol(node, text(name), kind, parent=prefix)
            body = node.child_by_field_name('body')
            if body is None:
                body = next((child for child in node.named_children if child.type in
                             {'class_body', 'interface_body', 'enum_body', 'enum_class_body', 'annotation_type_body'}), None)
            if body is not None:
                owner = '.'.join(filter(None, (prefix, text(name))))
                pending.extend((child, owner, True) for child in reversed(body.named_children))
        elif node.type == 'namespace_declaration':
            namespace = _qualified(name, text)
            body = node.child_by_field_name('body')
            if namespace and body is not None:
                scope = '.'.join(filter(None, (prefix, namespace)))
                pending.extend((child, scope, False) for child in reversed(body.named_children))
        elif node.type in {'method_declaration', 'constructor_declaration', 'compact_constructor_declaration',
                           'function_declaration', 'annotation_type_element_declaration'} and name is not None:
            constructor = 'constructor' in node.type
            kind = 'constructor' if constructor else 'method' if in_type else 'function'
            modifiers = [child for child in node.named_children if child.type in {'modifier', 'modifiers'}]
            if language == 'csharp' and any(text(child) == 'async' for child in modifiers):
                kind = 'async-' + kind
            body = node.child_by_field_name('body')
            if language == 'kotlin':
                body = next((child for child in node.named_children if child.type == 'function_body'), None)
            if not constructor and body is None:
                kind += '-signature'
            symbol(node, text(name), kind, parent=prefix, callable_name=not in_type and not constructor)
        elif node.type in {'import_declaration', 'import', 'using_directive'}:
            candidates = [child for child in node.named_children if child.type in
                          {'identifier', 'scoped_identifier', 'qualified_identifier', 'qualified_name', 'alias_qualified_name'}]
            # Alias names are preceding siblings; the final qualified path is
            # the target. Never slice source text containing comment trivia.
            target = _qualified(candidates[-1], text) if candidates else None
            if language == 'kotlin' and candidates:
                target = _qualified(candidates[0], text)
            if target:
                if any(child.type in {'asterisk', '*'} for child in node.children):
                    target += '.*'
                imports.append(StructuralImport(target))
        elif node.type == 'enum_body_declarations':
            pending.extend((child, prefix, in_type) for child in reversed(node.named_children))
    return imports


def managed_call_name(language, node, text):
    if language == 'java' and node.type == 'method_invocation' and node.child_by_field_name('object') is None:
        name = node.child_by_field_name('name')
    elif language == 'csharp' and node.type == 'invocation_expression':
        name = node.child_by_field_name('function')
    elif language == 'kotlin' and node.type == 'call_expression':
        name = next((child for child in node.named_children if 'comment' not in child.type), None)
    else:
        return None
    return text(name) if name is not None and name.type == 'identifier' else None
