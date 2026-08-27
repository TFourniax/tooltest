from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .debt_models import DebtSignal
from .debt_sensor import DebtSensorResult
from .diffing import is_documentation_path, is_test_path, parse_file_patches
from .gitops import diff_text, git, git_result


SENSOR_ID = "semantic-redundancy-v1"
RULE_ID = "sensor.semantic-redundancy"
SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java",
    ".kt", ".kts", ".php", ".cs", ".swift",
}
KEYWORDS = {
    "and", "as", "async", "await", "break", "case", "catch", "class", "const", "continue",
    "def", "do", "else", "elif", "except", "export", "false", "finally", "fn", "for", "from",
    "func", "function", "if", "import", "in", "interface", "let", "match", "new", "nil", "none",
    "not", "null", "or", "package", "pass", "private", "protected", "public", "raise", "return",
    "self", "static", "struct", "super", "switch", "this", "throw", "throws", "true", "try", "var",
    "while", "with", "yield",
}
CONTROL_NAMES = {"if", "for", "while", "switch", "catch", "match", "return", "new"}
TOKEN_RE = re.compile(
    r"(?:'''(?:.|\n)*?'''|\"\"\"(?:.|\n)*?\"\"\"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
    r"|(?:\b\d+(?:\.\d+)?\b)"
    r"|(?:[A-Za-z_$][A-Za-z0-9_$]*)"
    r"|(?:==|!=|<=|>=|=>|->|\+\+|--|&&|\|\||::|\?\?|\?\.|\+=|-=|\*=|/=)"
    r"|[^\s]",
    re.MULTILINE,
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")


@dataclass(frozen=True, slots=True)
class CodeUnit:
    path: str
    language: str
    kind: str
    name: str
    line: int
    end_line: int
    raw_digest: str
    structural: frozenset[str]
    vocabulary: frozenset[str]
    token_count: int
    simhash: int

    @property
    def key(self) -> str:
        return f"{self.path}::{self.kind}::{self.name}"


def _language(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".rs": "rust", ".java": "java",
        ".kt": "kotlin", ".kts": "kotlin", ".php": "php", ".cs": "csharp", ".swift": "swift",
    }.get(suffix, suffix.lstrip("."))


def _source_paths(repo: Path, candidate_sha: str, *, max_files: int) -> list[str]:
    raw = git(repo, "ls-tree", "-r", "--name-only", candidate_sha)
    result: list[str] = []
    for path in raw.splitlines():
        if PurePosixPath(path).suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if is_test_path(path) or is_documentation_path(path):
            continue
        result.append(path)
        if len(result) >= max_files:
            break
    return result


def _blob_text(repo: Path, candidate_sha: str, path: str) -> str | None:
    result = git_result(repo, "show", f"{candidate_sha}:{path}")
    if result.returncode != 0:
        return None
    if len(result.stdout) > 768_000:
        return None
    return result.stdout


def _identifier_words(identifier: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", identifier.replace("_", "-"))
    words = {word.lower() for word in re.split(r"[^A-Za-z0-9]+", expanded) if len(word) >= 3}
    return {word for word in words if word not in KEYWORDS and word not in {"get", "set", "obj", "arg", "tmp", "data", "value"}}


def _token_features(text: str) -> tuple[frozenset[str], frozenset[str], int, int, str]:
    tokens = TOKEN_RE.findall(text)
    normalized: list[str] = []
    vocabulary: set[str] = set()
    for token in tokens:
        lowered = token.lower()
        if WORD_RE.fullmatch(token):
            if lowered in KEYWORDS:
                normalized.append(lowered)
            else:
                normalized.append("ID")
                vocabulary.update(_identifier_words(token))
        elif token.startswith(("'", '"')):
            normalized.append("STR")
        elif re.fullmatch(r"\d+(?:\.\d+)?", token):
            normalized.append("NUM")
        else:
            normalized.append(token)
    structural = {
        "\x1f".join(normalized[index : index + 4])
        for index in range(max(0, len(normalized) - 3))
    }
    if not structural and normalized:
        structural = {"\x1f".join(normalized)}
    simhash = _simhash(structural)
    canonical_raw = re.sub(r"\s+", " ", text.strip())
    raw_digest = hashlib.sha256(canonical_raw.encode("utf-8", errors="replace")).hexdigest()
    return frozenset(structural), frozenset(vocabulary), len(normalized), simhash, raw_digest


def _simhash(features: Iterable[str]) -> int:
    weights = [0] * 64
    seen = False
    for feature in features:
        seen = True
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            weights[bit] += 1 if value & (1 << bit) else -1
    if not seen:
        return 0
    result = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << bit
    return result


def _unit(path: str, language: str, kind: str, name: str, line: int, end_line: int, text: str, *, min_tokens: int) -> CodeUnit | None:
    structural, vocabulary, token_count, simhash, raw_digest = _token_features(text)
    if token_count < min_tokens or len(structural) < 5:
        return None
    return CodeUnit(
        path=path,
        language=language,
        kind=kind,
        name=name,
        line=max(1, line),
        end_line=max(line, end_line),
        raw_digest=raw_digest,
        structural=structural,
        vocabulary=vocabulary,
        token_count=token_count,
        simhash=simhash,
    )


def _python_units(path: str, text: str, *, min_tokens: int) -> list[CodeUnit]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    lines = text.splitlines(keepends=True)
    result: list[CodeUnit] = []
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", None)
        if not isinstance(end, int) or end < node.lineno:
            continue
        parent = parents.get(node)
        kind = "method" if isinstance(parent, ast.ClassDef) else "function"
        source = "".join(lines[node.lineno - 1 : end])
        item = _unit(path, "python", kind, node.name, node.lineno, end, source, min_tokens=min_tokens)
        if item:
            result.append(item)
    return result


BRACED_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "javascript": (
        re.compile(r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
        re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{"),
    ),
    "typescript": (
        re.compile(r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
        re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{"),
    ),
    "go": (re.compile(r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)\s*\("),),
    "rust": (re.compile(r"\bfn\s+([A-Za-z_][\w]*)\s*(?:<[^>{}]*>)?\s*\("),),
    "php": (re.compile(r"\bfunction\s+([A-Za-z_][\w]*)\s*\("),),
    "swift": (re.compile(r"\bfunc\s+([A-Za-z_][\w]*)\s*\("),),
}
METHOD_RE = re.compile(
    r"^(?:\s*(?:public|private|protected|internal|static|final|open|override|virtual|async|synchronized|abstract)\s+)*"
    r"(?:[A-Za-z_$][\w$<>,.?\[\]]*\s+)+([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?:throws\s+[^\{]+)?\{"
)


def _brace_end(lines: list[str], start: int) -> int | None:
    depth = 0
    opened = False
    in_block_comment = False
    for index in range(start, len(lines)):
        line = lines[index]
        pos = 0
        quote: str | None = None
        escaped = False
        while pos < len(line):
            char = line[pos]
            nxt = line[pos + 1] if pos + 1 < len(line) else ""
            if in_block_comment:
                if char == "*" and nxt == "/":
                    in_block_comment = False
                    pos += 2
                    continue
                pos += 1
                continue
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                pos += 1
                continue
            if char in {"'", '"', "`"}:
                quote = char
                pos += 1
                continue
            if char == "/" and nxt == "/":
                break
            if char == "/" and nxt == "*":
                in_block_comment = True
                pos += 2
                continue
            if char == "{":
                opened = True
                depth += 1
            elif char == "}" and opened:
                depth -= 1
                if depth == 0:
                    return index
            pos += 1
    return None


def _braced_units(path: str, text: str, language: str, *, min_tokens: int) -> list[CodeUnit]:
    lines = text.splitlines(keepends=True)
    patterns = BRACED_PATTERNS.get(language, ())
    result: list[CodeUnit] = []
    consumed: set[tuple[int, str]] = set()
    for index, line in enumerate(lines):
        name: str | None = None
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                name = match.group(1)
                break
        if name is None and language in {"java", "kotlin", "csharp"}:
            match = METHOD_RE.search(line)
            if match and match.group(1).lower() not in CONTROL_NAMES:
                name = match.group(1)
        if not name or (index, name) in consumed:
            continue
        end = _brace_end(lines, index)
        if end is None or end - index > 600:
            continue
        source = "".join(lines[index : end + 1])
        item = _unit(path, language, "function", name, index + 1, end + 1, source, min_tokens=min_tokens)
        if item:
            result.append(item)
            consumed.add((index, name))
    return result


def _extract_units(path: str, text: str, *, min_tokens: int) -> list[CodeUnit]:
    language = _language(path)
    if language == "python":
        return _python_units(path, text, min_tokens=min_tokens)
    return _braced_units(path, text, language, min_tokens=min_tokens)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _similarity(left: CodeUnit, right: CodeUnit) -> tuple[float, dict[str, float]]:
    structural = _jaccard(left.structural, right.structural)
    vocabulary = _jaccard(left.vocabulary, right.vocabulary)
    size = min(left.token_count, right.token_count) / max(left.token_count, right.token_count)
    score = 0.72 * structural + 0.13 * vocabulary + 0.15 * size
    return score, {
        "structural_jaccard": round(structural, 4),
        "vocabulary_jaccard": round(vocabulary, 4),
        "size_ratio": round(size, 4),
    }


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _overlap(left: CodeUnit, right: CodeUnit) -> bool:
    if left.path != right.path:
        return False
    return not (left.end_line < right.line or right.end_line < left.line)


def _pair_anchor(left: CodeUnit, right: CodeUnit) -> str:
    raw = "\0".join(sorted((left.key, right.key)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _signal(left: CodeUnit, right: CodeUnit, *, score: float, components: dict[str, float], scope: str, candidate_sha: str) -> DebtSignal:
    ordered = sorted((left, right), key=lambda unit: (unit.path, unit.name, unit.line))
    primary = ordered[0]
    locations = [
        {
            "path": unit.path,
            "line": unit.line,
            "end_line": unit.end_line,
            "name": unit.name,
            "kind": unit.kind,
            "language": unit.language,
        }
        for unit in ordered
    ]
    severity = "medium" if score >= 0.95 else "low"
    return DebtSignal(
        category="redundancy",
        rule_id=RULE_ID,
        title="Possible semantic reimplementation",
        severity=severity,
        measurement="heuristic",
        points=0,
        anchor=_pair_anchor(left, right),
        path=primary.path,
        line=primary.line,
        end_line=primary.end_line,
        explanation=(
            "Two independently located code units have strongly overlapping normalized control/token structure. "
            "This can indicate an agent reimplemented an existing capability, but it is advisory: similarity is not "
            "proof of functional equivalence or an instruction to merge the implementations."
        ),
        evidence={
            "sensor": SENSOR_ID,
            "similarity": round(score, 4),
            "components": components,
            "locations": locations,
            "source_code_exported": False,
        },
        verification={"type": "project-rule", "rule_id": RULE_ID},
        introduced_by={"candidate_sha": candidate_sha},
        tags=["debt-sensor", "semantic-redundancy", scope, "advisory"],
    )


def _load_units(repo: Path, candidate_sha: str, *, max_files: int, min_tokens: int) -> tuple[list[CodeUnit], int]:
    units: list[CodeUnit] = []
    paths = _source_paths(repo, candidate_sha, max_files=max_files)
    for path in paths:
        text = _blob_text(repo, candidate_sha, path)
        if text is None:
            continue
        units.extend(_extract_units(path, text, min_tokens=min_tokens))
    return units, len(paths)


def _changed_added_lines(repo: Path, base_sha: str, candidate_sha: str) -> dict[str, set[int]]:
    files = parse_file_patches(diff_text(repo, base_sha, candidate_sha))
    result: dict[str, set[int]] = defaultdict(set)
    for file in files:
        if file.is_test or is_documentation_path(file.path):
            continue
        for hunk in file.hunks:
            line = hunk.new_start
            for raw in hunk.text.splitlines()[1:]:
                if raw.startswith("+") and not raw.startswith("+++"):
                    if isinstance(line, int):
                        result[file.path].add(line)
                    if isinstance(line, int):
                        line += 1
                elif raw.startswith("-") and not raw.startswith("---"):
                    continue
                elif isinstance(line, int):
                    line += 1
    return result


def _touches(unit: CodeUnit, added: dict[str, set[int]]) -> bool:
    lines = added.get(unit.path)
    return bool(lines and any(unit.line <= line <= unit.end_line for line in lines))


def _candidate_pairs(units: list[CodeUnit]) -> set[tuple[int, int]]:
    """LSH-style banding keeps project scans sub-quadratic for ordinary repositories."""
    bands: dict[tuple[int, int], list[int]] = defaultdict(list)
    pairs: set[tuple[int, int]] = set()
    mask = (1 << 16) - 1
    for index, unit in enumerate(units):
        for band in range(4):
            key = (band, (unit.simhash >> (band * 16)) & mask)
            for other in bands[key]:
                pairs.add((other, index))
            bands[key].append(index)
    return pairs


def _rank_pairs(units: list[CodeUnit], pairs: Iterable[tuple[int, int]], *, threshold: float, max_signals: int, candidate_sha: str, scope: str, changed_only: set[int] | None = None) -> list[DebtSignal]:
    ranked: list[tuple[float, CodeUnit, CodeUnit, dict[str, float]]] = []
    seen: set[str] = set()
    for left_index, right_index in pairs:
        if changed_only is not None and left_index not in changed_only and right_index not in changed_only:
            continue
        left, right = units[left_index], units[right_index]
        if left.raw_digest == right.raw_digest or _overlap(left, right):
            continue
        if _hamming(left.simhash, right.simhash) > 18:
            continue
        score, components = _similarity(left, right)
        if score < threshold or components["structural_jaccard"] < 0.72:
            continue
        anchor = _pair_anchor(left, right)
        if anchor in seen:
            continue
        seen.add(anchor)
        ranked.append((score, left, right, components))
    ranked.sort(key=lambda item: (-item[0], item[1].path, item[1].line, item[2].path, item[2].line))
    return [
        _signal(left, right, score=score, components=components, scope=scope, candidate_sha=candidate_sha)
        for score, left, right, components in ranked[:max_signals]
    ]


class SemanticRedundancySensor:
    sensor_id = SENSOR_ID

    def __init__(self, *, threshold: float = 0.88, max_files: int = 500, max_signals: int = 20, min_tokens: int = 32) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError("semantic redundancy threshold must be in (0, 1]")
        if max_files < 1 or max_signals < 1 or min_tokens < 8:
            raise ValueError("semantic redundancy limits must be positive")
        self.threshold = threshold
        self.max_files = max_files
        self.max_signals = max_signals
        self.min_tokens = min_tokens

    def scan_change(self, *, repo: Path, base_sha: str, candidate_sha: str) -> DebtSensorResult:
        units, scanned_files = _load_units(repo, candidate_sha, max_files=self.max_files, min_tokens=self.min_tokens)
        added = _changed_added_lines(repo, base_sha, candidate_sha)
        changed = {index for index, unit in enumerate(units) if _touches(unit, added)}
        if not changed:
            return DebtSensorResult(
                sensor_id=self.sensor_id,
                metadata={"mode": "change", "scanned_files": scanned_files, "units": len(units), "changed_units": 0, "threshold": self.threshold},
            )
        pairs = {
            (min(index, other), max(index, other))
            for index in changed
            for other in range(len(units))
            if index != other and _hamming(units[index].simhash, units[other].simhash) <= 18
        }
        signals = _rank_pairs(
            units,
            pairs,
            threshold=self.threshold,
            max_signals=self.max_signals,
            candidate_sha=candidate_sha,
            scope="change",
            changed_only=changed,
        )
        for signal in signals:
            signal.introduced_by.update({"base_sha": base_sha, "candidate_sha": candidate_sha, "sensor": self.sensor_id})
        return DebtSensorResult(
            sensor_id=self.sensor_id,
            signals=signals,
            metadata={
                "mode": "change",
                "scanned_files": scanned_files,
                "units": len(units),
                "changed_units": len(changed),
                "candidate_pairs": len(pairs),
                "threshold": self.threshold,
                "accounting": "advisory-zero-point",
            },
        )

    def scan_project(self, *, repo: Path, candidate_sha: str) -> DebtSensorResult:
        units, scanned_files = _load_units(repo, candidate_sha, max_files=self.max_files, min_tokens=self.min_tokens)
        pairs = _candidate_pairs(units)
        signals = _rank_pairs(
            units,
            pairs,
            threshold=self.threshold,
            max_signals=self.max_signals,
            candidate_sha=candidate_sha,
            scope="project",
        )
        return DebtSensorResult(
            sensor_id=self.sensor_id,
            signals=signals,
            metadata={
                "mode": "project",
                "scanned_files": scanned_files,
                "units": len(units),
                "candidate_pairs": len(pairs),
                "threshold": self.threshold,
                "accounting": "advisory-zero-point",
            },
        )
