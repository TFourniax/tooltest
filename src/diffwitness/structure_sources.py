"""Bounded regular source blobs from one immutable Git tree; never the working tree."""
from __future__ import annotations

import io
import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from .gitops import git_bytes

MAX_SOURCE_FILE_BYTES = 1024 * 1024
MAX_SOURCE_TOTAL_BYTES = 32 * 1024 * 1024
SNAPSHOT_VERSION = "git-tree-blobs-1"
_EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", "__pycache__"}


def tree_sources(repo: Path, tree: str, *, suffixes: tuple[str, ...], max_files: int = 2000) -> tuple[list[tuple[str, bytes]], dict[str, Any]]:
    if type(max_files) is not int or not 1 <= max_files <= 2000:
        raise ValueError("structure max_files must be an integer between 1 and 2000")
    coverage: dict[str, Any] = {"source": SNAPSHOT_VERSION, "tree": tree or None,
        "extensions": list(suffixes), "scope": "tracked regular files outside hidden/generated directories",
        "limits": {"files": max_files, "fileBytes": MAX_SOURCE_FILE_BYTES, "totalBytes": MAX_SOURCE_TOTAL_BYTES},
        "eligibleFiles": 0, "files": 0, "bytes": 0, "oversized": 0, "unsupportedPaths": 0,
        "unsupportedModes": 0, "omittedByLimit": 0, "unparsed": 0, "truncated": False, "complete": bool(tree)}
    if not tree:
        return [], coverage
    candidates = []
    manifest = git_bytes(repo, "ls-tree", "-r", "-l", "-z", "--full-tree", tree)
    for record in manifest.split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        mode, kind, oid, size = header.split()
        try:
            relative = raw_path.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            coverage["unsupportedPaths"] += 1
            continue
        parts = PurePosixPath(relative).parts
        if not relative.endswith(suffixes) or any(part in _EXCLUDED_DIRS or part.startswith(".") for part in parts[:-1]):
            continue
        if mode not in {b"100644", b"100755"} or kind != b"blob":
            coverage["unsupportedModes"] += 1
            continue
        coverage["eligibleFiles"] += 1
        length = int(size)
        if length > MAX_SOURCE_FILE_BYTES:
            coverage["oversized"] += 1
            continue
        candidates.append((relative, oid, length))
    selected = []
    for relative, oid, length in sorted(candidates):
        if len(selected) >= max_files or coverage["bytes"] + length > MAX_SOURCE_TOTAL_BYTES:
            coverage["omittedByLimit"] += 1
            continue
        selected.append((relative, oid, length))
        coverage["bytes"] += length
    result = []
    if selected:
        request = b"".join(oid + b"\n" for _, oid, _ in selected)
        stream = io.BytesIO(git_bytes(repo, "cat-file", "--batch", input_bytes=request))
        for relative, expected_oid, expected_size in selected:
            header = stream.readline().rstrip(b"\n").split()
            if header != [expected_oid, b"blob", str(expected_size).encode("ascii")]:
                raise ValueError("Git source blob does not match the captured tree manifest")
            content = stream.read(expected_size)
            if len(content) != expected_size or stream.read(1) != b"\n":
                raise ValueError("Git source blob response is truncated")
            algorithm = {40: "sha1", 64: "sha256"}.get(len(expected_oid))
            if algorithm is None or hashlib.new(algorithm, b"blob " + str(expected_size).encode("ascii") + b"\0" + content).hexdigest().encode("ascii") != expected_oid:
                raise ValueError("Git source blob content does not match its object identity")
            result.append((relative, content))
        if stream.read(1):
            raise ValueError("Git source blob response has unexpected trailing bytes")
    coverage["files"] = len(result)
    coverage["truncated"] = coverage["omittedByLimit"] > 0
    coverage["complete"] = not any(coverage[key] for key in ("oversized", "unsupportedPaths", "unsupportedModes", "omittedByLimit"))
    return result, coverage
