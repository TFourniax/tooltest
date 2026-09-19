"""Read-only, bounded source-byte adapter for existing structure providers."""
from __future__ import annotations

import base64
import binascii
import json
import sys
from dataclasses import asdict

from .json_contract import strict_json_loads
from .structure_registry import extract_structure
from .structure_sources import MAX_SOURCE_FILE_BYTES

REQUEST_SCHEMA = "structure-request-1"
RESPONSE_SCHEMA = "structure-response-1"
MAX_FILES = 64
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_WIRE_BYTES = 6 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _source(item: object) -> tuple[str, bytes]:
    if not isinstance(item, dict) or set(item) != {"path", "content_base64"}:
        raise ValueError("each source must contain exactly path and content_base64")
    path, encoded = item["path"], item["content_base64"]
    if (not isinstance(path, str) or not 1 <= len(path) <= 4096
            or "\\" in path or ":" in path or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or any(part in {"", ".", ".."} for part in path.split("/"))):
        raise ValueError("source path must be an unambiguous relative path")
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_SOURCE_FILE_BYTES + 2) // 3):
        raise ValueError("source base64 exceeds the per-file bound or is not a string")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("source must use canonical base64") from exc
    if len(content) > MAX_SOURCE_FILE_BYTES or base64.b64encode(content).decode("ascii") != encoded:
        raise ValueError("source must use canonical base64 within the per-file bound")
    return path, content


def extract_request(request: object) -> dict:
    if (not isinstance(request, dict) or set(request) != {"schema_version", "files"}
            or request["schema_version"] != REQUEST_SCHEMA
            or not isinstance(request["files"], list) or len(request["files"]) > MAX_FILES):
        raise ValueError("unsupported or malformed bounded structure request")
    sources = [_source(item) for item in request["files"]]
    if len({path for path, _ in sources}) != len(sources):
        raise ValueError("source paths must be unique")
    if sum(len(content) for _, content in sources) > MAX_TOTAL_BYTES:
        raise ValueError("structure request exceeds total source-byte bound")
    files = []
    coverage = {"files": len(sources), "parsed": 0, "unsupported": 0, "unparsed": 0}
    for path, content in sources:
        result = extract_structure(path, content)
        coverage['unsupported' if result.provider == 'file-only' else 'parsed' if result.parsed else 'unparsed'] += 1
        files.append(asdict(result))
    return {"schema_version": RESPONSE_SCHEMA, "files": files, "coverage": coverage}


def extraction_cli() -> int:
    """No repository discovery, path opens, environment execution or persistence."""
    try:
        raw = sys.stdin.buffer.read(MAX_WIRE_BYTES + 1)
        if len(raw) > MAX_WIRE_BYTES:
            raise ValueError("structure request exceeds wire-byte bound")
        request = strict_json_loads(raw.decode("utf-8"))
        response = json.dumps(extract_request(request), ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(response.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError("structure response exceeds wire-byte bound")
    except (ValueError, UnicodeError, RecursionError) as exc:
        print("Structure extraction rejected: " + str(exc), file=sys.stderr)
        return 2
    print(response)
    return 0
