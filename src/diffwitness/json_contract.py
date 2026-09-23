from __future__ import annotations

import json
from typing import Any


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(values)
    if len(result) != len(values):
        # Decode has already produced ordinary string keys. Retain the first
        # duplicate's diagnostic without imposing a Python loop on valid objects.
        seen = set()
        for key, _ in values:
            if key in seen:
                raise ValueError(f"duplicate JSON object key: {key}")
            seen.add(key)
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


# Like the standard library's default decoder, this decoder owns configuration,
# not decoded documents. Hooks create new per-object state on every invocation.
_DECODER = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_reject_constant)


def strict_json_loads(text: str) -> Any:
    """Parse JSON without silently resolving duplicate keys or numeric constants.

    Shared with local engine configuration. Numeric overflow to infinity is rejected
    by each caller's finite-value/canonical validation after parsing.
    """
    if type(text) is str and not text.startswith('\ufeff'):
        return _DECODER.decode(text)
    # Preserve json.loads' byte encodings, BOM/type errors and nonstandard inputs.
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_reject_constant)
