"""Ruby/PHP source facts over the shared admitted syntax tree."""
from __future__ import annotations



def _ruby_path(node, text):
    if node is None:
        return None
    parts, pending = [], [node]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            parts.append(current)
        elif current.type == 'constant':
            parts.append(text(current))
        elif current.type == 'scope_resolution':
            scope, name = current.child_by_field_name('scope'), current.child_by_field_name('name')
            if name is None:
                return None
            pending.extend([name, '.'])
            if scope is not None:
                pending.append(scope)
        else:
            return None
    return ''.join(parts) if parts else None


def _php_path(node, text):
    if node is None:
        return None
    parts, pending = [], [node]
    while pending:
        current = pending.pop()
        if 'comment' in current.type:
            continue
        if current.type in {'name', '\\', 'namespace'}:
            parts.append(text(current))
        elif current.type in {'namespace_name', 'qualified_name', 'relative_name'}:
            pending.extend(reversed(current.children))
        else:
            return None
    return ''.join(parts) if parts else None


def _literal(node, text):
    while node is not None and node.type == 'parenthesized_expression':
        children = [child for child in node.named_children if 'comment' not in child.type]
        node = children[0] if len(children) == 1 else None
    if node is None or node.type not in {'string', 'encapsed_string'}:
        return None
    raw = text(node)
    if len(raw) < 3 or raw[0] not in {'\"', "'"} or raw[-1] != raw[0] or '\\' in raw:
        return None
    if any(child.type != 'string_content' for child in node.named_children):
        return None
    return raw[1:-1]


def dynamic_declarations(language, root, nodes, text, symbol, reference):
    pending = []

    def enqueue(children, prefix=None, in_type=False):
        batch, active = [], prefix
        for child in children:
            if language == 'php' and child.type == 'namespace_definition' and child.child_by_field_name('body') is None:
                path = _php_path(child.child_by_field_name('name'), text)
                active = path.replace('\\', '.') if path else None
            else:
                batch.append((child, active, in_type))
        pending.extend(reversed(batch))

    enqueue(root.named_children)
    while pending:
        node, prefix, in_type = pending.pop()
        name, body = node.child_by_field_name('name'), node.child_by_field_name('body')
        if language == 'ruby' and node.type in {'class', 'module'}:
            path = _ruby_path(name, text)
            if path:
                owner = path[1:] if path.startswith('.') else '.'.join(filter(None, (prefix, path)))
                symbol(node, owner, node.type)
                if body is not None:
                    enqueue(body.named_children, owner, True)
        elif language == 'ruby' and node.type in {'method', 'singleton_method'} and name is not None:
            if node.type == 'singleton_method':
                receiver = node.child_by_field_name('object')
                if receiver is None or receiver.type != 'self' or prefix is None:
                    continue
                kind = 'singleton-method'
            else:
                kind = 'method' if in_type else 'function'
            symbol(node, text(name), kind, parent=prefix, callable_name=not in_type and kind == 'function')
        elif language == 'php' and node.type == 'namespace_definition' and body is not None:
            path = _php_path(name, text)
            enqueue(body.named_children, path.replace('\\', '.') if path else None)
        elif language == 'php' and node.type in {'class_declaration', 'interface_declaration', 'trait_declaration', 'enum_declaration'} and name is not None:
            symbol(node, text(name), node.type.removesuffix('_declaration'), parent=prefix)
            if body is not None:
                enqueue(body.named_children, '.'.join(filter(None, (prefix, text(name)))), True)
        elif language == 'php' and node.type in {'function_definition', 'method_declaration'} and name is not None:
            kind = 'method' if in_type else 'function'
            if body is None:
                kind += '-signature'
            # Name-only calls carry no PHP namespace. Keep declarations/calls,
            # but do not choose one of several equally named namespace targets.
            symbol(node, text(name), kind, parent=prefix)

    imports = []
    for node in nodes:
        if language == 'ruby' and node.type == 'call' and node.child_by_field_name('receiver') is None:
            method, args = node.child_by_field_name('method'), node.child_by_field_name('arguments')
            if text(method) not in {'require', 'require_relative'} or args is None:
                continue
            values = [child for child in args.named_children if 'comment' not in child.type]
            target = _literal(values[0], text) if len(values) == 1 else None
            if target:
                if text(method) == 'require_relative' and not target.startswith(('./', '../', '/')):
                    target = './' + target
                imports.append(reference(node, target))
        elif language == 'php' and node.type == 'namespace_use_declaration':
            group = node.child_by_field_name('body')
            prefix_node = next((c for c in node.named_children if c.type == 'namespace_name'), None)
            prefix = _php_path(prefix_node, text) if group is not None else None
            for clause in (group.named_children if group is not None else node.named_children):
                if clause.type != 'namespace_use_clause':
                    continue
                target_node = next((c for c in clause.named_children if c.type in {'name', 'namespace_name', 'qualified_name', 'relative_name'}), None)
                target = _php_path(target_node, text)
                if target:
                    imports.append(reference(node, prefix + '\\' + target if prefix else target))
        elif language == 'php' and node.type in {'require_expression', 'require_once_expression', 'include_expression', 'include_once_expression'}:
            values = [child for child in node.named_children if 'comment' not in child.type]
            target = _literal(values[0], text) if len(values) == 1 else None
            if target:
                imports.append(reference(node, target))
    return imports


def dynamic_call_name(language, node, text):
    if language == 'ruby' and node.type == 'call' and node.child_by_field_name('receiver') is None:
        name = node.child_by_field_name('method')
        return text(name) if name is not None and name.type == 'identifier' else None
    if language == 'php' and node.type == 'function_call_expression':
        name = node.child_by_field_name('function')
        return text(name) if name is not None and name.type == 'name' else None
    return None
