"""SQL declarations and configuration key-only facts; no runtime evaluation."""
from __future__ import annotations

import json
import math
import tomllib

from .json_contract import strict_json_loads


def _pointer(parts):
    value = '/' + '/'.join(part.replace('~', '~0').replace('/', '~1') for part in parts)
    value.encode('utf-8', errors='strict')
    return value


def _yaml_key(node, text):
    while node is not None and node.type == 'flow_node':
        children = [child for child in node.named_children if 'comment' not in child.type]
        node = children[0] if len(children) == 1 else None
    if node is None:
        return None
    raw = text(node)
    if '\n' in raw or '\r' in raw:
        return None
    if node.type == 'plain_scalar':
        return raw
    if node.type == 'single_quote_scalar':
        return raw[1:-1].replace("''", "'")
    if node.type == 'double_quote_scalar':
        try:
            return json.loads(raw)
        except ValueError:
            # YAML-only escapes need a dedicated decoder; do not invent a key.
            return None
    return None


def _json_yaml(language, root, text, symbol):
    if language == 'yaml':
        pending = [(node, ('@' + str(index),)) for index, node in reversed(list(enumerate(
            child for child in root.named_children if child.type == 'document')))]
    else:
        pending = [(root, ())]
    while pending:
        node, prefix = pending.pop()
        if node.type in {'document', 'block_node', 'flow_node', 'block_sequence_item'}:
            pending.extend((child, prefix) for child in reversed(node.named_children)
                           if child.type not in {'tag', 'anchor', 'alias', 'comment'})
        elif node.type in {'object', 'block_mapping', 'flow_mapping'}:
            pending.extend((child, prefix) for child in reversed(node.named_children)
                           if child.type in {'pair', 'block_mapping_pair', 'flow_pair'})
        elif node.type in {'pair', 'block_mapping_pair', 'flow_pair'}:
            key, value = node.child_by_field_name('key'), node.child_by_field_name('value')
            name = json.loads(text(key)) if language == 'json' else _yaml_key(key, text)
            if not isinstance(name, str):
                continue
            path = (*prefix, name)
            symbol(key, _pointer(path), 'config-key')
            if value is not None:
                pending.append((value, path))
        elif node.type in {'array', 'block_sequence', 'flow_sequence'}:
            children = [child for child in node.named_children if 'comment' not in child.type]
            pending.extend((child, (*prefix, str(index))) for index, child in reversed(list(enumerate(children))))


def _toml_key(node, text):
    parts, pending = [], [node]
    while pending:
        current = pending.pop()
        if current.type == 'bare_key':
            parts.append(text(current))
        elif current.type == 'quoted_key':
            # Decode only the key token with the standard parser, not source values.
            parts.append(next(iter(tomllib.loads(text(current) + '=0'))))
        elif current.type == 'dotted_key':
            pending.extend(reversed([child for child in current.named_children if 'comment' not in child.type]))
        else:
            return None
    return tuple(parts) if parts else None


def _toml(root, text, symbol):
    current_arrays = {}
    pending = [(root, ())]

    def scope(parts, new_array=False):
        result = ()
        for index, part in enumerate(parts):
            result = (*result, part)
            if new_array and index == len(parts) - 1:
                current_arrays[result] = current_arrays.get(result, -1) + 1
            if result in current_arrays:
                result = (*result, str(current_arrays[result]))
        return result

    while pending:
        node, prefix = pending.pop()
        if node.type in {'document', 'inline_table'}:
            pending.extend((child, prefix) for child in reversed(node.named_children)
                           if child.type in {'pair', 'table', 'table_array_element'})
        elif node.type in {'table', 'table_array_element', 'pair'}:
            children = [child for child in node.named_children if 'comment' not in child.type]
            parts = _toml_key(children[0], text) if children else None
            if parts is None:
                continue
            if node.type == 'pair':
                path = (*prefix, *parts)
                symbol(children[0], _pointer(path), 'config-key')
                if len(children) == 2:
                    pending.append((children[1], path))
            else:
                path = scope(parts, node.type == 'table_array_element')
                symbol(children[0], _pointer(path), 'config-table')
                pending.extend((child, path) for child in reversed(children[1:]) if child.type == 'pair')
        elif node.type == 'array':
            children = [child for child in node.named_children if 'comment' not in child.type]
            pending.extend((child, (*prefix, str(index))) for index, child in reversed(list(enumerate(children))))


def _sql(root, text, symbol):
    kinds = {'create_table': 'table', 'create_view': 'view', 'create_index': 'index',
             'create_function': 'function', 'create_type': 'type', 'create_schema': 'schema'}
    for statement in root.named_children:
        node = statement
        while node.type == 'statement':
            children = [child for child in node.named_children if 'comment' not in child.type and child.type != 'marginalia']
            if not children:
                break
            node = children[0]
        if node.type not in kinds:
            continue
        if node.type == 'create_index':
            name = node.child_by_field_name('column')
        else:
            name = next((child for child in node.named_children if child.type == 'object_reference'), None)
            if name is None and node.type == 'create_schema':
                name = next((child for child in node.named_children if child.type == 'identifier'), None)
        if name is None:
            continue
        if name.type == 'identifier':
            target = text(name)
        elif name.type == 'object_reference':
            parts = [child for child in name.named_children if 'comment' not in child.type and child.type != 'marginalia']
            if not parts or any(child.type != 'identifier' for child in parts):
                continue
            # Keep quoting/case: removing it would conflate different SQL names.
            target = '.'.join(text(child) for child in parts)
        else:
            continue
        symbol(node, target, kinds[node.type])


def data_declarations(language, root, content, text, symbol):
    if language == 'sql':
        _sql(root, text, symbol)
    elif language == 'toml':
        tomllib.loads(content.decode('utf-8'))
        _toml(root, text, symbol)
    else:
        if language == 'json':
            pending = [strict_json_loads(content.decode('utf-8'))]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
                elif isinstance(value, float) and not math.isfinite(value):
                    raise ValueError('non-finite JSON configuration value')
        _json_yaml(language, root, text, symbol)
