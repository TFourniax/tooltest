from __future__ import annotations

import fnmatch
import hashlib
import re
import shlex
from pathlib import PurePosixPath

from .models import FilePatch, Hunk, Mutation


STRUCTURAL_MARKERS = (
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "GIT binary patch",
    "Binary files ",
)


def is_test_path(path: str, extra_globs: list[str] | None = None) -> bool:
    p = PurePosixPath(path.lower())
    parts = set(p.parts)
    name = p.name
    if parts.intersection({"test", "tests", "__tests__", "spec", "specs"}):
        return True
    if name in {"conftest.py", "pytest.ini"}:
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if any(token in name for token in (".test.", ".spec.")):
        return True
    if extra_globs and any(fnmatch.fnmatch(path, pattern) for pattern in extra_globs):
        return True
    return False


def _parse_paths(first_line: str) -> tuple[str | None, str]:
    try:
        tokens = shlex.split(first_line.strip())
    except ValueError:
        tokens = first_line.strip().split()
    if len(tokens) >= 4:
        old = tokens[2]
        new = tokens[3]
        old = old[2:] if old.startswith("a/") else old
        new = new[2:] if new.startswith("b/") else new
        return old, new
    return None, "<unknown>"


def _count_hunk(lines: list[str]) -> tuple[int, int]:
    additions = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return additions, deletions


def parse_file_patches(diff: str, *, test_globs: list[str] | None = None) -> list[FilePatch]:
    if not diff.strip():
        return []
    blocks = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
    files: list[FilePatch] = []
    for block in blocks:
        if not block.startswith("diff --git "):
            continue
        lines = block.splitlines(keepends=True)
        old_path, path = _parse_paths(lines[0])
        hunk_starts = [i for i, line in enumerate(lines) if line.startswith("@@ ")]
        first_hunk = hunk_starts[0] if hunk_starts else len(lines)
        header = "".join(lines[:first_hunk])
        structural = any(marker in header or marker in block for marker in STRUCTURAL_MARKERS)
        binary = "GIT binary patch" in block or "Binary files " in block
        hunks: list[Hunk] = []
        for n, start in enumerate(hunk_starts):
            end = hunk_starts[n + 1] if n + 1 < len(hunk_starts) else len(lines)
            hunk_lines = lines[start:end]
            additions, deletions = _count_hunk(hunk_lines)
            hunks.append(
                Hunk(
                    header=hunk_lines[0].rstrip("\n"),
                    text="".join(hunk_lines),
                    additions=additions,
                    deletions=deletions,
                )
            )
        files.append(
            FilePatch(
                path=path,
                old_path=old_path,
                raw=block,
                header=header,
                hunks=hunks,
                structural=structural or not hunks,
                binary=binary,
                is_test=is_test_path(path, test_globs),
            )
        )
    return files


def _mutation_id(path: str, patch: str) -> str:
    return hashlib.sha256(f"{path}\0{patch}".encode("utf-8", errors="replace")).hexdigest()[:10]


def make_mutations(
    files: list[FilePatch],
    *,
    include_tests: bool = False,
    ignore_globs: list[str] | None = None,
) -> list[Mutation]:
    ignore_globs = ignore_globs or []
    mutations: list[Mutation] = []
    for file in files:
        if file.is_test and not include_tests:
            continue
        if any(fnmatch.fnmatch(file.path, pattern) for pattern in ignore_globs):
            continue
        if file.structural:
            adds = sum(h.additions for h in file.hunks)
            dels = sum(h.deletions for h in file.hunks)
            patch = file.raw
            mutations.append(
                Mutation(
                    id=_mutation_id(file.path, patch),
                    path=file.path,
                    label=f"{file.path} (file-level/structural)",
                    patch=patch,
                    kind="structural" if not file.binary else "binary",
                    additions=adds,
                    deletions=dels,
                )
            )
            continue
        for index, hunk in enumerate(file.hunks, start=1):
            patch = file.header + hunk.text
            context = hunk.header.split("@@")[-1].strip()
            suffix = f" — {context}" if context else ""
            mutations.append(
                Mutation(
                    id=_mutation_id(file.path, patch),
                    path=file.path,
                    label=f"{file.path} hunk {index}/{len(file.hunks)}{suffix}",
                    patch=patch,
                    kind="hunk",
                    additions=hunk.additions,
                    deletions=hunk.deletions,
                )
            )
    return mutations


def test_overlay(files: list[FilePatch]) -> str:
    return "".join(file.raw for file in files if file.is_test)
