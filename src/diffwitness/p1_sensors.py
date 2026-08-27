from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .debt_models import DebtSignal
from .debt_sensor import DebtSensorResult
from .diffing import is_documentation_path, is_test_path, parse_file_patches
from .gitops import diff_text, git, git_result
from .semantic_redundancy import SOURCE_SUFFIXES

PARALLEL_SOURCE_SENSOR_ID = "parallel-source-of-truth-v1"
PARALLEL_SOURCE_RULE_ID = "sensor.parallel-source-of-truth"
AGENT_EXPANSION_SENSOR_ID = "agent-expansion-v1"
AGENT_EXPANSION_RULE_ID = "sensor.agent-expansion"
SECURITY_POLICY_SENSOR_ID = "duplicate-security-policy-v1"
SECURITY_POLICY_RULE_ID = "sensor.duplicate-security-policy"

_LITERAL = r"(?:-?\d+(?:\.\d+)?|true|false|null|none|'(?:\\.|[^'\\]){1,120}'|\"(?:\\.|[^\"\\]){1,120}\")"
DECLARATION_PATTERNS = (
    re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*({_LITERAL})\s*[,;]?\s*$", re.IGNORECASE),
    re.compile(rf"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*({_LITERAL})\s*(?:#.*)?$", re.IGNORECASE),
)
GENERIC_NAME_WORDS = {
    "default", "current", "config", "configured", "constant", "setting", "settings", "value",
    "global", "local", "app", "application", "system", "internal", "public", "private",
}
COMMON_CONCEPTS = {"version", "timeout", "size", "count", "status", "name", "type", "mode"}
SECURITY_TERMS = {
    "auth", "authorize", "authorization", "permission", "permissions", "access", "role", "roles",
    "tenant", "token", "session", "credential", "credentials", "secret", "webhook", "signature",
    "csrf", "rate", "limit", "sanitize", "sanitizer", "validate", "validator", "policy", "acl", "admin",
}
DECLARATION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|interface|type|struct|enum|trait)\s+[A-Za-z_$][\w$]*"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ConstantDeclaration:
    path: str
    name: str
    concept: tuple[str, ...]
    literal: str
    line: int


def _identifier_words(identifier: str) -> tuple[str, ...]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", identifier.replace("_", " ").replace("-", " "))
    words = [word.lower() for word in re.split(r"[^A-Za-z0-9]+", expanded) if len(word) >= 3]
    return tuple(word for word in words if word not in GENERIC_NAME_WORDS)


def _meaningful_concept(name: str) -> tuple[str, ...] | None:
    words = _identifier_words(name)
    if not words:
        return None
    if len(words) == 1 and words[0] in COMMON_CONCEPTS:
        return None
    if len(words) == 1 and len(words[0]) < 6:
        return None
    return tuple(sorted(set(words)))


def _normalize_literal(raw: str) -> str | None:
    value = raw.strip().rstrip(",;")
    lowered = value.lower()
    if lowered in {"true", "false", "null", "none", "0", "1", "-1", "''", '""'}:
        return None
    if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
        inner = value[1:-1].strip()
        if len(inner) < 2:
            return None
        return f"str:{inner}"
    return f"num:{value}"


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
    if result.returncode != 0 or len(result.stdout) > 768_000:
        return None
    return result.stdout


def _declarations(repo: Path, candidate_sha: str, *, max_files: int) -> list[ConstantDeclaration]:
    declarations: list[ConstantDeclaration] = []
    for path in _source_paths(repo, candidate_sha, max_files=max_files):
        text = _blob_text(repo, candidate_sha, path)
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern in DECLARATION_PATTERNS:
                match = pattern.match(line)
                if not match:
                    continue
                name, raw_literal = match.groups()
                concept = _meaningful_concept(name)
                literal = _normalize_literal(raw_literal)
                if concept and literal:
                    declarations.append(ConstantDeclaration(path, name, concept, literal, line_number))
                break
    return declarations


def _declaration_groups(items: list[ConstantDeclaration]) -> dict[tuple[tuple[str, ...], str], list[ConstantDeclaration]]:
    groups: dict[tuple[tuple[str, ...], str], list[ConstantDeclaration]] = defaultdict(list)
    for item in items:
        groups[(item.concept, item.literal)].append(item)
    return groups


def _source_signal(group: list[ConstantDeclaration], *, candidate_sha: str, scope: str) -> DebtSignal:
    ordered = sorted(group, key=lambda item: (item.path, item.line, item.name))
    primary = ordered[0]
    concept = " ".join(primary.concept)
    anchor_raw = f"{concept}\0{primary.literal}\0" + "\0".join(sorted({item.path for item in ordered}))
    anchor = hashlib.sha256(anchor_raw.encode("utf-8")).hexdigest()[:24]
    locations = [{"path": item.path, "line": item.line, "name": item.name} for item in ordered]
    return DebtSignal(
        category="architecture",
        rule_id=PARALLEL_SOURCE_RULE_ID,
        title="Possible parallel source of truth",
        severity="medium" if len({item.path for item in ordered}) >= 3 else "low",
        measurement="heuristic",
        anchor=anchor,
        path=primary.path,
        line=primary.line,
        points=0,
        explanation=(
            f"The same {concept!r} concept and literal value are declared in {len({item.path for item in ordered})} production files. "
            "This may be intentional, but independently maintained copies can drift. Consolidate only when the declarations represent one domain truth."
        ),
        evidence={
            "sensor": PARALLEL_SOURCE_SENSOR_ID,
            "scope": scope,
            "concept": list(primary.concept),
            "literal_fingerprint": hashlib.sha256(primary.literal.encode("utf-8")).hexdigest()[:16],
            "locations": locations,
            "candidate_sha": candidate_sha,
            "source_code_exported": False,
        },
        verification={"kind": "project-rule", "sensor": PARALLEL_SOURCE_SENSOR_ID},
        tags=["debt-sensor", "parallel-source-of-truth", "advisory", scope],
    )


class ParallelSourceOfTruthSensor:
    sensor_id = PARALLEL_SOURCE_SENSOR_ID

    def __init__(self, *, max_files: int = 500, max_signals: int = 20) -> None:
        self.max_files = max_files
        self.max_signals = max_signals

    def scan_change(self, *, repo: Path, base_sha: str, candidate_sha: str) -> DebtSensorResult:
        base_groups = _declaration_groups(_declarations(repo, base_sha, max_files=self.max_files))
        candidate_groups = _declaration_groups(_declarations(repo, candidate_sha, max_files=self.max_files))
        signals: list[DebtSignal] = []
        for key, group in candidate_groups.items():
            candidate_paths = {item.path for item in group}
            if len(candidate_paths) < 2:
                continue
            base_paths = {item.path for item in base_groups.get(key, [])}
            if len(candidate_paths) <= len(base_paths):
                continue
            signals.append(_source_signal(group, candidate_sha=candidate_sha, scope="change"))
            if len(signals) >= self.max_signals:
                break
        return DebtSensorResult(
            sensor_id=self.sensor_id,
            signals=signals,
            metadata={"status": "ok", "measurement": "heuristic", "points_authoritative": False, "source_code_exported": False},
        )

    def scan_project(self, *, repo: Path, candidate_sha: str) -> DebtSensorResult:
        groups = _declaration_groups(_declarations(repo, candidate_sha, max_files=self.max_files))
        signals = [
            _source_signal(group, candidate_sha=candidate_sha, scope="project")
            for group in groups.values()
            if len({item.path for item in group}) >= 2
        ][: self.max_signals]
        return DebtSensorResult(
            sensor_id=self.sensor_id,
            signals=signals,
            metadata={"status": "ok", "measurement": "heuristic", "points_authoritative": False, "source_code_exported": False},
        )


def _security_context(signal: DebtSignal) -> bool:
    locations = signal.evidence.get("locations") if isinstance(signal.evidence, dict) else None
    haystacks: list[str] = []
    if isinstance(locations, list):
        for item in locations:
            if isinstance(item, dict):
                haystacks.extend([str(item.get("path") or ""), str(item.get("name") or "")])
    for raw in haystacks:
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw.replace("_", " ").replace("/", " ").replace("-", " ")).lower()
        words = set(re.findall(r"[a-z]+", expanded))
        if words & SECURITY_TERMS:
            return True
    return False


def security_policy_from_semantic(result: DebtSensorResult, *, max_signals: int = 20) -> DebtSensorResult:
    signals: list[DebtSignal] = []
    for source in result.signals:
        if not _security_context(source):
            continue
        evidence = dict(source.evidence)
        evidence.update({"sensor": SECURITY_POLICY_SENSOR_ID, "derived_from_sensor": result.sensor_id, "source_code_exported": False})
        signals.append(
            DebtSignal(
                category="security",
                rule_id=SECURITY_POLICY_RULE_ID,
                title="Possible duplicated security policy",
                severity="medium" if source.severity in {"medium", "high", "critical"} else "low",
                measurement="heuristic",
                anchor=source.anchor,
                path=source.path,
                line=source.line,
                end_line=source.end_line,
                points=0,
                explanation=(
                    "Two structurally similar implementations appear in security-sensitive code. This does not prove a vulnerability or that the policies should be merged; "
                    "it flags a divergence risk when authorization, validation, tenant, token, session, or related policy is maintained in more than one place."
                ),
                evidence=evidence,
                verification={"kind": "project-rule", "sensor": SECURITY_POLICY_SENSOR_ID},
                tags=["debt-sensor", "security-policy", "parallel-policy", "advisory"],
            )
        )
        if len(signals) >= max_signals:
            break
    return DebtSensorResult(
        sensor_id=SECURITY_POLICY_SENSOR_ID,
        signals=signals,
        metadata={"status": "ok", "measurement": "heuristic", "derived_from": result.sensor_id, "points_authoritative": False, "source_code_exported": False},
    )


def _added_declarations(raw_patch: str) -> int:
    count = 0
    for line in raw_patch.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if DECLARATION_RE.search(line[1:]):
            count += 1
    return count


class AgentExpansionSensor:
    sensor_id = AGENT_EXPANSION_SENSOR_ID

    def __init__(self, *, max_signals: int = 1) -> None:
        self.max_signals = max_signals

    def scan_change(self, *, repo: Path, base_sha: str, candidate_sha: str) -> DebtSensorResult:
        patches = [
            patch for patch in parse_file_patches(diff_text(repo, base_sha, candidate_sha))
            if not patch.binary and not patch.is_test and not is_documentation_path(patch.path)
        ]
        changed_files = len(patches)
        additions = sum(hunk.additions for patch in patches for hunk in patch.hunks)
        deletions = sum(hunk.deletions for patch in patches for hunk in patch.hunks)
        structural_files = sum(1 for patch in patches if patch.structural)
        new_files = sum(1 for patch in patches if "new file mode " in patch.header)
        new_declarations = sum(_added_declarations(patch.raw) for patch in patches)

        triggered = (
            (changed_files >= 8 and additions >= 250)
            or (changed_files >= 12 and additions >= 150)
            or (additions >= 600 and new_declarations >= 6)
            or (structural_files >= 6 and additions >= 200)
        )
        if not triggered or self.max_signals <= 0:
            return DebtSensorResult(sensor_id=self.sensor_id, signals=[], metadata={"status": "ok", "applicable": True, "measurement": "heuristic", "points_authoritative": False})

        paths = sorted(patch.path for patch in patches)
        anchor = hashlib.sha256("\0".join(paths).encode("utf-8")).hexdigest()[:24]
        breadth = changed_files + new_files * 2 + structural_files + new_declarations
        severity = "medium" if additions >= 600 or changed_files >= 15 or breadth >= 30 else "low"
        signal = DebtSignal(
            category="complexity",
            rule_id=AGENT_EXPANSION_RULE_ID,
            title="Large structural expansion in one change",
            severity=severity,
            measurement="heuristic",
            anchor=anchor,
            path=paths[0] if paths else None,
            points=0,
            explanation=(
                "This change expands the production surface across many files, lines, or new declarations. Large changes can be legitimate; the signal asks whether the breadth is intentional "
                "and whether a smaller implementation would preserve the same intended behavior."
            ),
            evidence={
                "sensor": self.sensor_id,
                "changed_production_files": changed_files,
                "added_lines": additions,
                "deleted_lines": deletions,
                "new_files": new_files,
                "structural_files": structural_files,
                "new_declarations": new_declarations,
                "paths": paths[:25],
                "paths_truncated": len(paths) > 25,
                "candidate_sha": candidate_sha,
                "source_code_exported": False,
            },
            verification={"kind": "change-rule", "sensor": self.sensor_id},
            tags=["debt-sensor", "agent-expansion", "scope-breadth", "advisory"],
        )
        return DebtSensorResult(sensor_id=self.sensor_id, signals=[signal], metadata={"status": "ok", "applicable": True, "measurement": "heuristic", "points_authoritative": False, "source_code_exported": False})

    def scan_project(self, *, repo: Path, candidate_sha: str) -> DebtSensorResult:
        return DebtSensorResult(sensor_id=self.sensor_id, signals=[], metadata={"status": "ok", "applicable": False, "reason": "change-scoped sensor", "points_authoritative": False})
