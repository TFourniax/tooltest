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
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


DOCUMENTATION_SUFFIXES = {".md", ".mdx", ".rst", ".adoc", ".asciidoc"}
DOCUMENTATION_BASENAMES = {
    "license",
    "license.txt",
    "copying",
    "notice",
    "authors",
    "contributors",
    "code_of_conduct.md",
    "security.md",
}


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
    return bool(extra_globs and any(fnmatch.fnmatch(path, pattern) for pattern in extra_globs))


def is_documentation_path(path: str) -> bool:
    """Conservatively identify files that should not require executable causal evidence.

    Build/configuration files are intentionally *not* excluded: they may alter runtime behavior.
    The classifier is kept narrow so unusual data/code formats stay inside the proof surface.
    """
    p = PurePosixPath(path.lower())
    name = p.name
    if p.suffix in DOCUMENTATION_SUFFIXES:
        return True
    if name in DOCUMENTATION_BASENAMES:
        return True
    if name.startswith("readme") or name.startswith("changelog") or name.startswith("contributing"):
        return True
    if p.parts and p.parts[0] in {"docs", "doc"}:
        return True
    if len(p.parts) >= 2 and p.parts[0] == ".github" and p.parts[1] in {
        "issue_template",
        "discussion_template",
    }:
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


def _hunk_range(header: str) -> tuple[int | None, int | None, int | None, int | None]:
    match = HUNK_RE.match(header)
    if not match:
        return None, None, None, None
    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_start = int(match.group(3))
    new_count = int(match.group(4) or "1")
    return old_start, old_count, new_start, new_count


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
            header_line = hunk_lines[0].rstrip("\n")
            old_start, old_count, new_start, new_count = _hunk_range(header_line)
            hunks.append(
                Hunk(
                    header=header_line,
                    text="".join(hunk_lines),
                    additions=additions,
                    deletions=deletions,
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
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
    include_docs: bool = False,
) -> list[Mutation]:
    ignore_globs = ignore_globs or []
    mutations: list[Mutation] = []
    for file in files:
        if file.is_test and not include_tests:
            continue
        if is_documentation_path(file.path) and not include_docs:
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
                    kind="binary" if file.binary else "structural",
                    additions=adds,
                    deletions=dels,
                    line=file.hunks[0].new_start if file.hunks else 1,
                    end_line=(file.hunks[0].new_start or 1) if file.hunks else 1,
                )
            )
            continue
        for index, hunk in enumerate(file.hunks, start=1):
            patch = file.header + hunk.text
            context = hunk.header.split("@@")[-1].strip()
            suffix = f" — {context}" if context else ""
            start = hunk.new_start
            count = hunk.new_count or 1
            end = (start + max(count, 1) - 1) if start is not None else None
            mutations.append(
                Mutation(
                    id=_mutation_id(file.path, patch),
                    path=file.path,
                    label=f"{file.path} hunk {index}/{len(file.hunks)}{suffix}",
                    patch=patch,
                    kind="hunk",
                    additions=hunk.additions,
                    deletions=hunk.deletions,
                    line=start,
                    end_line=end,
                )
            )
    return mutations


def test_overlay(files: list[FilePatch]) -> str:
    return "".join(file.raw for file in files if file.is_test)
