"""Go/Rust declaration adapters over the shared admitted syntax tree."""
from __future__ import annotations

from .structure_contract import StructuralImport


def _path_text(node, text):
    names, pending, absolute = [], [node] if node is not None else [], False
    separator = '.' if node is not None and node.type == 'qualified_type' else '::'
    while pending:
        current = pending.pop()
        if current.type in {'identifier', 'type_identifier', 'package_identifier', 'self', 'super', 'crate'}:
            names.append(text(current))
        elif current.type in {'scoped_identifier', 'scoped_type_identifier', 'qualified_type'}:
            path = current.child_by_field_name('path') or current.child_by_field_name('package')
            name = current.child_by_field_name('name')
            if name is None:
                return None
            if path is None and current.children and current.children[0].type == '::':
                absolute = True
            pending.append(name)
            if path is not None:
                pending.append(path)
        else:
            return None
    return ('::' if absolute else '') + separator.join(names) if names else None


def _base_type(node, text):
    # Only named receivers are joined to a type name. Tuple/reference/associated
    # type resolution is not implemented and must not pick an arbitrary child.
    while node is not None:
        if node.type == 'primitive_type':
            return text(node)
        if node.type in {'type_identifier', 'identifier', 'scoped_type_identifier', 'scoped_identifier', 'qualified_type'}:
            return _path_text(node, text)
        if node.type == 'generic_type':
            node = node.child_by_field_name('type')
        elif node.type == 'pointer_type':
            node = next((child for child in node.named_children if 'comment' not in child.type), None)
        else:
            return None
    return None


def _rust_use_paths(argument, text):
    result, pending = [], [(argument, '')] if argument is not None else []
    while pending:
        node, prefix = pending.pop()
        if node.type == 'use_as_clause':
            path = node.child_by_field_name('path')
            if path is not None:
                pending.append((path, prefix))
        elif node.type == 'scoped_use_list':
            path, group = node.child_by_field_name('path'), node.child_by_field_name('list')
            part = _path_text(path, text) if path is not None else ''
            if part is None:
                continue
            joined = '::'.join(filter(None, (prefix, part)))
            if group is not None:
                pending.append((group, joined))
        elif node.type == 'use_list':
            pending.extend((child, prefix) for child in reversed(node.named_children))
        elif node.type in {'identifier', 'scoped_identifier', 'self', 'super', 'crate', 'use_wildcard'}:
            if node.type == 'use_wildcard':
                path = next((child for child in node.named_children if 'comment' not in child.type), None)
                base = _path_text(path, text) if path is not None else ''
                part = (base + '::' if base else '') + '*' if base is not None else None
            else:
                part = _path_text(node, text)
            if part is None:
                continue
            result.append(prefix if part == 'self' and prefix else '::'.join(filter(None, (prefix, part))))
    return result


def native_declarations(language, root, text, symbol):
    imports = []
    if language == 'go':
        for node in root.named_children:
            name = node.child_by_field_name('name')
            if node.type == 'function_declaration' and name is not None:
                symbol(node, text(name), 'function', callable_name=True)
            elif node.type == 'method_declaration' and name is not None:
                receiver = node.child_by_field_name('receiver')
                parameter = next((child for child in receiver.named_children
                                  if child.type == 'parameter_declaration'), None) if receiver is not None else None
                parent = _base_type(parameter.child_by_field_name('type'), text) if parameter is not None else None
                if parent:
                    symbol(node, text(name), 'method', parent=parent)
            elif node.type == 'type_declaration':
                for item in node.named_children:
                    name, value = item.child_by_field_name('name'), item.child_by_field_name('type')
                    if name is not None and item.type in {'type_spec', 'type_alias'}:
                        kind = 'type-alias' if item.type == 'type_alias' else {
                            'struct_type': 'struct', 'interface_type': 'interface',
                        }.get(value.type if value is not None else '', 'type')
                        symbol(item, text(name), kind)
            elif node.type == 'import_declaration':
                pending = list(reversed(node.named_children))
                while pending:
                    item = pending.pop()
                    if item.type == 'import_spec':
                        path = item.child_by_field_name('path')
                        raw = text(path)
                        if path is not None and len(raw) > 2 and '\\' not in raw:
                            imports.append(StructuralImport(raw[1:-1]))
                    else:
                        pending.extend(reversed(item.named_children))
        return imports

    kinds = {'struct_item': 'struct', 'enum_item': 'enum', 'trait_item': 'trait',
             'type_item': 'type-alias', 'mod_item': 'module', 'union_item': 'union'}
    pending = [(node, None, False) for node in reversed(root.named_children)]
    while pending:
        node, prefix, method = pending.pop()
        name = node.child_by_field_name('name')
        if node.type in {'function_item', 'function_signature_item'} and name is not None:
            async_ = any(child.type == 'function_modifiers' and 'async' in text(child).split()
                         for child in node.named_children)
            kind = 'method' if method else 'function'
            if async_:
                kind = 'async-' + kind
            if node.type == 'function_signature_item':
                kind += '-signature'
            symbol(node, text(name), kind, parent=prefix, callable_name=not prefix and not method)
        elif node.type in kinds and name is not None:
            symbol(node, text(name), kinds[node.type], parent=prefix)
            if node.type in {'mod_item', 'trait_item'}:
                body = node.child_by_field_name('body')
                qualified = '.'.join(filter(None, (prefix, text(name))))
                if body is not None:
                    pending.extend((child, qualified, node.type == 'trait_item')
                                   for child in reversed(body.named_children))
        elif node.type == 'impl_item':
            parent = _base_type(node.child_by_field_name('type'), text)
            trait = node.child_by_field_name('trait')
            if parent and trait is not None:
                trait_name = _base_type(trait, text)
                parent = parent + ' as ' + trait_name if trait_name else None
            body = node.child_by_field_name('body')
            if parent and body is not None:
                qualified = '.'.join(filter(None, (prefix, parent)))
                pending.extend((child, qualified, True) for child in reversed(body.named_children))
        elif node.type == 'use_declaration':
            imports.extend(StructuralImport(path) for path in _rust_use_paths(node.child_by_field_name('argument'), text))
        elif node.type == 'extern_crate_declaration' and name is not None:
            imports.append(StructuralImport(text(name)))
    return imports
