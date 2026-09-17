from __future__ import annotations

import json
from typing import Any


def strict_json_loads(text: str) -> Any:
    """Parse JSON without silently resolving duplicate keys or numeric constants.

    Shared with local engine configuration. Numeric overflow to infinity is rejected
    by each caller's finite-value/canonical validation after parsing.
    """
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
