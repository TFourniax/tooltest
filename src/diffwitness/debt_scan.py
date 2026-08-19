from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .debt_models import DebtReport, DebtSignal, dedupe_signals
from .diffing import (
    FilePatch,
    is_documentation_path,
    is_test_path,
    make_mutations,
    parse_file_patches,
)
from .gitops import diff_text, git, git_result
from .security_scan import scan_security_text


SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java",
    ".kt", ".kts", ".rb", ".php", ".cs", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".vue", ".svelte",
}
MANIFEST_NAMES = {
    "package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "poetry.lock",
    "pdm.lock", "uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "composer.json",
}
MIGRATION_PARTS = {"migration", "migrations", "migrate", "alembic", "flyway", "liquibase"}
SENSITIVE_TOKENS = {
    "auth", "session", "permission", "permissions", "billing", "payment", "payments", "webhook",
    "secret", "token", "crypto", "oauth", "sso", "password", "admin", "rbac", "acl",
}
CONTROL_FLOW_RE = re.compile(r"\b(if|elif|else|for|while|case|switch|catch|except|try|match)\b|&&|\|\|")
IMPORT_RE = re.compile(
    r"^\s*(?:"
    r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|"
    r"export\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|"
    r"from\s+([\.\w]+)\s+import|"
    r"import\s+([\.\w]+)|"
    r"(?:const|let|var)\s+.*?=\s*require\(['\"]([^'\"]+)['\"]\)"
    r")",
    re.MULTILINE,
)


def _load_certificate(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read DiffWitness certificate {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("DiffWitness certificate must be a JSON object")
    return value


def _candidate_tree(repo: Path, candidate_sha: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{candidate_sha}^{{tree}}").strip()


def _is_source(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES


def _is_migration(path: str) -> bool:
    parts = {part.lower() for part in PurePosixPath(path).parts}
    name = PurePosixPath(path).name.lower()
    return bool(parts.intersection(MIGRATION_PARTS)) or name.startswith(("migration_", "migrate_"))


def _sensitive(path: str) -> bool:
    lowered = path.lower().replace("-", "_")
    tokens = set(re.split(r"[/_.]+", lowered))
    return bool(tokens.intersection(SENSITIVE_TOKENS))


def _added_lines(file: FilePatch) -> list[tuple[int | None, str]]:
    result: list[tuple[int | None, str]] = []
    for hunk in file.hunks:
        line = hunk.new_start
        for raw in hunk.text.splitlines()[1:]:
            if raw.startswith("+") and not raw.startswith("+++"):
                result.append((line, raw[1:]))
                if line is not None:
                    line += 1
            elif raw.startswith("-") and not raw.startswith("---"):
                continue
            elif line is not None:
                line += 1
    return result


def _proof_backing(certificate: dict[str, Any] | None) -> tuple[bool, str | None]:
    if not certificate:
        return False, None
    cid = str(certificate.get("certificate_id") or "")
    if cid.startswith("dw2_") and certificate.get("contrast") == "base-fail_candidate-pass":
        return True, cid
    if cid.startswith("dwac1_") and certificate.get("contrast"):
        return True, cid
    if cid.startswith("dwa1_") and certificate.get("classification") == "preservation-evidence":
        return True, cid
    return False, cid or None


def _proof_signals(
    certificate: dict[str, Any] | None, *, base_sha: str, candidate_sha: str
) -> list[DebtSignal]:
    if not certificate:
        return []
    cid = str(certificate.get("certificate_id") or "")
    signals: list[DebtSignal] = []
    introduced_by = {
        "base_sha": base_sha,
        "candidate_sha": candidate_sha,
        "certificate_id": cid,
    }
    if cid.startswith("dw2_"):
        surplus_ids = set(certificate.get("surplus_candidate_mutation_ids") or [])
        for result in certificate.get("results") or []:
            if not isinstance(result, dict):
                continue
            mutation = result.get("mutation") or {}
            status = result.get("status")
            mutation_id = str(mutation.get("id") or "unknown")
            path = mutation.get("path")
            line = mutation.get("line")
            end_line = mutation.get("end_line")
            if status == "unwitnessed":
                strong = mutation_id in surplus_ids
                signals.append(
                    DebtSignal(
                        category="redundancy" if strong else "evidence",
                        rule_id="proof.strong-surplus" if strong else "proof.unwitnessed-mutation",
                        title="Strong surplus candidate" if strong else "Behaviorally unwitnessed change",
                        severity="high" if strong else "medium",
                        measurement="causal",
                        anchor=mutation_id,
                        path=str(path) if path else None,
                        line=int(line) if isinstance(line, int) else None,
                        end_line=int(end_line) if isinstance(end_line, int) else None,
                        explanation=(
                            "The selected evidence stayed stably green without this mutation and exhaustive sufficient-set search did not need it at the proven order."
                            if strong
                            else "Removing this exact mutation left the selected evidence stably green. The change may still serve an untested requirement, so this is evidence debt rather than a deletion order."
                        ),
                        evidence={"certificate_id": cid, "status": status, "mutation": mutation},
                        verification={
                            "type": "mutation-necessity",
                            "origin_base_sha": base_sha,
                            "origin_candidate_sha": candidate_sha,
                            "mutation_patch": mutation.get("patch"),
                            "mutation_id": mutation_id,
                        },
                        introduced_by=introduced_by,
                    )
                )
            elif status == "inconclusive":
                signals.append(
                    DebtSignal(
                        category="evidence",
                        rule_id="proof.inconclusive-mutation",
                        title="Mutation evidence is inconclusive",
                        severity="medium",
                        measurement="causal",
                        anchor=mutation_id,
                        path=str(path) if path else None,
                        line=int(line) if isinstance(line, int) else None,
                        end_line=int(end_line) if isinstance(end_line, int) else None,
                        explanation="Patch application, timeout, or unstable execution prevented DiffWitness from establishing necessity for this mutation.",
                        evidence={"certificate_id": cid, "status": status, "mutation": mutation},
                        verification={
                            "type": "rerun-proof",
                            "origin_base_sha": base_sha,
                            "origin_candidate_sha": candidate_sha,
                        },
                        introduced_by=introduced_by,
                    )
                )
        for pair in (certificate.get("interaction_search") or {}).get("results") or []:
            if isinstance(pair, dict) and pair.get("status") == "mutual-backup":
                ids = [str(value) for value in pair.get("mutation_ids") or []]
                labels = [str(value) for value in pair.get("mutation_labels") or []]
                signals.append(
                    DebtSignal(
                        category="redundancy",
                        rule_id="proof.mutual-backup",
                        title="Hidden mutual-backup implementation",
                        severity="medium",
                        measurement="causal",
                        anchor="+".join(sorted(ids)),
                        explanation="Each mutation can disappear individually while the evidence stays green, but removing the pair together breaks the evidence. The behavior has redundant implementation paths.",
                        evidence={"certificate_id": cid, "mutation_ids": ids, "labels": labels},
                        verification={
                            "type": "rerun-proof",
                            "origin_base_sha": base_sha,
                            "origin_candidate_sha": candidate_sha,
                        },
                        introduced_by=introduced_by,
                    )
                )
    elif cid.startswith("dwac1_"):
        mutations = certificate.get("mutations") or {}
        for mutation_id in certificate.get("removable_mutation_ids") or []:
            meta = mutations.get(mutation_id) or {}
            signals.append(
                DebtSignal(
                    category="redundancy",
                    rule_id="proof.adaptive-removable",
                    title="Evidence-removable mutation",
                    severity="medium",
                    measurement="causal",
                    anchor=str(mutation_id),
                    path=str(meta.get("path")) if meta.get("path") else None,
                    line=meta.get("line") if isinstance(meta.get("line"), int) else None,
                    end_line=meta.get("end_line") if isinstance(meta.get("end_line"), int) else None,
                    explanation="Adaptive Core found a stable-passing real-patch core that excludes this mutation. This is budgeted evidence of removability, not proof of a global minimum patch.",
                    evidence={"certificate_id": cid, "mutation": meta},
                    verification={
                        "type": "mutation-necessity",
                        "origin_base_sha": base_sha,
                        "origin_candidate_sha": candidate_sha,
                        "mutation_patch": meta.get("patch"),
                        "mutation_id": str(mutation_id),
                    },
                    introduced_by=introduced_by,
                )
            )
        if not certificate.get("one_minimal"):
            signals.append(
                DebtSignal(
                    category="evidence",
                    rule_id="proof.adaptive-budget-incomplete",
                    title="Adaptive proof did not establish 1-minimality",
                    severity="medium",
                    measurement="causal",
                    anchor=cid,
                    explanation="The configured Adaptive Core budget ended before 1-minimality was established, leaving part of the causal surface unknown.",
                    evidence={
                        "certificate_id": cid,
                        "attempts": certificate.get("attempts"),
                        "budget": certificate.get("budget"),
                    },
                    verification={
                        "type": "rerun-proof",
                        "origin_base_sha": base_sha,
                        "origin_candidate_sha": candidate_sha,
                    },
                    introduced_by=introduced_by,
                )
            )
    elif cid.startswith("dwa1_") and certificate.get("classification") == "non-discriminating-change":
        paths = sorted(str(path) for path in certificate.get("changed_test_files") or [])
        signals.append(
            DebtSignal(
                category="test",
                rule_id="proof.non-discriminating-tests",
                title="Changed tests do not prove the production change",
                severity="high",
                measurement="causal",
                anchor="|".join(paths) or cid,
                explanation="The candidate tests are stably green on the historical base as well as the candidate. They therefore do not discriminate the production change.",
                evidence={"certificate_id": cid, "test_files": paths},
                verification={
                    "type": "historical-discrimination",
                    "origin_base_sha": base_sha,
                    "origin_candidate_sha": candidate_sha,
                },
                introduced_by=introduced_by,
            )
        )
    return signals


def _candidate_text(repo: Path, candidate_sha: str, path: str) -> str | None:
    result = git_result(repo, "show", f"{candidate_sha}:{path}")
    return result.stdout if result.returncode == 0 else None


def _security_signals(
    repo: Path,
    candidate_sha: str,
    files: Iterable[FilePatch],
    *,
    introduced_by: dict[str, Any],
) -> list[DebtSignal]:
    signals: list[DebtSignal] = []
    for file in files:
        if file.is_test or is_documentation_path(file.path):
            continue
        added = {line for line, _ in _added_lines(file) if isinstance(line, int)}
        if not added:
            continue
        text = _candidate_text(repo, candidate_sha, file.path)
        if text is None:
            continue
        for hit in scan_security_text(file.path, text):
            if hit.line not in added:
                continue
            anchor = hashlib.sha256(
                f"{file.path}\0{hit.rule_id}\0{hit.match}".encode("utf-8")
            ).hexdigest()[:16]
            signals.append(
                DebtSignal(
                    category="security",
                    rule_id=hit.rule_id,
                    title=hit.title,
                    severity=hit.severity,
                    measurement="deterministic",
                    anchor=anchor,
                    path=file.path,
                    line=hit.line,
                    explanation=hit.explanation,
                    evidence={"match": hit.match},
                    verification={"type": "project-rule", "rule_id": hit.rule_id},
                    introduced_by=introduced_by,
                )
            )
    return signals


def _change_review(rule_id: str, introduced_by: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "change-review",
        "rule_id": rule_id,
        "origin_base_sha": introduced_by.get("base_sha"),
        "origin_candidate_sha": introduced_by.get("candidate_sha"),
    }


def _change_complexity_signals(
    files: list[FilePatch], *, introduced_by: dict[str, Any]
) -> list[DebtSignal]:
    signals: list[DebtSignal] = []
    production = [file for file in files if not file.is_test and not is_documentation_path(file.path)]
    total_adds = sum(hunk.additions for file in production for hunk in file.hunks)
    total_dels = sum(hunk.deletions for file in production for hunk in file.hunks)
    if total_adds + total_dels >= 700:
        signals.append(
            DebtSignal(
                category="complexity",
                rule_id="change.large-surface",
                title="Very large implementation change",
                severity="medium",
                measurement="deterministic",
                anchor=f"change:{introduced_by.get('candidate_sha')}",
                explanation=f"The executable production diff changes {total_adds + total_dels} lines. Large change surface raises review and rollback cost; this does not by itself mean the code is incorrect.",
                evidence={
                    "additions": total_adds,
                    "deletions": total_dels,
                    "production_files": len(production),
                },
                verification=_change_review("change.large-surface", introduced_by),
                introduced_by=introduced_by,
            )
        )
    for file in production:
        adds = sum(hunk.additions for hunk in file.hunks)
        dels = sum(hunk.deletions for hunk in file.hunks)
        control = len(CONTROL_FLOW_RE.findall("\n".join(text for _, text in _added_lines(file))))
        if adds + dels >= 300:
            signals.append(
                DebtSignal(
                    category="complexity",
                    rule_id="change.concentrated-churn",
                    title="Large change concentrated in one file",
                    severity="medium",
                    measurement="deterministic",
                    anchor=file.path,
                    path=file.path,
                    explanation=f"This file absorbs {adds + dels} changed lines in one change, concentrating review and rollback risk.",
                    evidence={"additions": adds, "deletions": dels},
                    verification=_change_review("change.concentrated-churn", introduced_by),
                    introduced_by=introduced_by,
                )
            )
        if control >= 14:
            signals.append(
                DebtSignal(
                    category="complexity",
                    rule_id="change.control-flow-growth",
                    title="Control-flow surface grew sharply",
                    severity="low" if control < 25 else "medium",
                    measurement="heuristic",
                    anchor=file.path,
                    path=file.path,
                    explanation=f"The added lines contain {control} control-flow operators/keywords. This is a review heuristic, not a cyclomatic-complexity proof.",
                    evidence={"control_flow_tokens_added": control},
                    verification=_change_review("change.control-flow-growth", introduced_by),
                    introduced_by=introduced_by,
                )
            )
    return signals


def _manifest_dependency_signals(
    files: list[FilePatch], *, introduced_by: dict[str, Any]
) -> list[DebtSignal]:
    signals: list[DebtSignal] = []
    for file in files:
        name = PurePosixPath(file.path).name
        if name not in MANIFEST_NAMES or name.endswith("lock") or "lock." in name:
            continue
        additions = [text.strip() for _, text in _added_lines(file) if text.strip()]
        depish = [line for line in additions if re.search(r"[=:]\s*['\"]?[\w@./-]+", line)]
        if not depish:
            continue
        signals.append(
            DebtSignal(
                category="dependency",
                rule_id="dependency.surface-growth",
                title="Dependency surface expanded",
                severity="low" if len(depish) <= 2 else "medium",
                measurement="heuristic",
                anchor=file.path + ":" + hashlib.sha256("\n".join(depish).encode()).hexdigest()[:10],
                path=file.path,
                explanation=f"The manifest adds {len(depish)} dependency-like declaration(s). DiffWitness does not claim they are unused; it records new external maintenance/supply-chain surface for review.",
                evidence={"lines": depish[:20], "count": len(depish)},
                verification=_change_review("dependency.surface-growth", introduced_by),
                introduced_by=introduced_by,
            )
        )
    return signals


def _architecture_change_signals(
    files: list[FilePatch], *, introduced_by: dict[str, Any]
) -> list[DebtSignal]:
    signals: list[DebtSignal] = []
    for file in files:
        if not _is_source(file.path) or file.is_test:
            continue
        imports = [
            next(value for value in match.groups() if value)
            for match in IMPORT_RE.finditer("\n".join(text for _, text in _added_lines(file)))
            if any(match.groups())
        ]
        imports = [value for value in imports if value.startswith((".", "../", "./"))]
        if len(imports) >= 6:
            signals.append(
                DebtSignal(
                    category="architecture",
                    rule_id="architecture.import-fanout-growth",
                    title="Module coupling expanded sharply",
                    severity="medium",
                    measurement="heuristic",
                    anchor=file.path,
                    path=file.path,
                    explanation=f"The change adds {len(imports)} relative/local import edges to this module. It is a coupling heuristic, not proof of an architectural violation.",
                    evidence={"imports": imports[:30]},
                    verification=_change_review("architecture.import-fanout-growth", introduced_by),
                    introduced_by=introduced_by,
                )
            )
    return signals


def _migration_signals(
    files: list[FilePatch], *, introduced_by: dict[str, Any]
) -> list[DebtSignal]:
    signals: list[DebtSignal] = []
    for file in files:
        if not _is_migration(file.path):
            continue
        text = file.raw.lower()
        rollback_markers = ("downgrade", "down(", "rollback", "reverse", "revert", "undo")
        if any(marker in text for marker in rollback_markers):
            continue
        signals.append(
            DebtSignal(
                category="migration",
                rule_id="migration.no-obvious-rollback",
                title="Migration has no obvious rollback path",
                severity="high",
                measurement="heuristic",
                anchor=file.path,
                path=file.path,
                explanation="This migration change contains no rollback/down/reverse marker recognized by DiffWitness. That does not prove rollback is impossible; it records an operational obligation to verify recovery explicitly.",
                verification=_change_review("migration.no-obvious-rollback", introduced_by),
                introduced_by=introduced_by,
            )
        )
    return signals


def scan_change(
    *,
    repo: Path,
    base_sha: str,
    candidate_sha: str,
    certificate_path: Path | None = None,
    test_globs: list[str] | None = None,
    ignore_globs: list[str] | None = None,
) -> DebtReport:
    certificate = _load_certificate(certificate_path)
    files = parse_file_patches(diff_text(repo, base_sha, candidate_sha), test_globs=test_globs or [])
    mutations = make_mutations(files, ignore_globs=ignore_globs or [])
    candidate_tree = _candidate_tree(repo, candidate_sha)
    introduced_by = {
        "base_sha": base_sha,
        "candidate_sha": candidate_sha,
        "candidate_tree": candidate_tree,
        "certificate_id": certificate.get("certificate_id") if certificate else None,
    }
    signals: list[DebtSignal] = []
    signals.extend(_proof_signals(certificate, base_sha=base_sha, candidate_sha=candidate_sha))
    signals.extend(_security_signals(repo, candidate_sha, files, introduced_by=introduced_by))
    signals.extend(_change_complexity_signals(files, introduced_by=introduced_by))
    signals.extend(_manifest_dependency_signals(files, introduced_by=introduced_by))
    signals.extend(_architecture_change_signals(files, introduced_by=introduced_by))
    signals.extend(_migration_signals(files, introduced_by=introduced_by))

    production_files = [
        file for file in files if not file.is_test and not is_documentation_path(file.path)
    ]
    test_files = [file for file in files if file.is_test]
    behavior_backed, certificate_id = _proof_backing(certificate)
    if mutations and not behavior_backed:
        signals.append(
            DebtSignal(
                category="unverified_change",
                rule_id="change.no-proof-certificate",
                title="Executable change lacks accepted DiffWitness behavioral evidence",
                severity="high",
                measurement="deterministic",
                anchor=f"{base_sha[:12]}..{candidate_sha[:12]}",
                explanation="Executable production mutations are present without a causal or preservation certificate accepted by DiffWitness. A certificate file that is merely present, validation-only, inconclusive, or non-discriminating cannot waive this obligation.",
                evidence={
                    "mutations": len(mutations),
                    "production_files": len(production_files),
                    "certificate_id": certificate_id,
                },
                verification={
                    "type": "rerun-proof",
                    "origin_base_sha": base_sha,
                    "origin_candidate_sha": candidate_sha,
                },
                introduced_by=introduced_by,
            )
        )
    if mutations and not test_files and not behavior_backed:
        signals.append(
            DebtSignal(
                category="test",
                rule_id="change.no-changed-test-surface",
                title="Production change has no changed test surface",
                severity="medium",
                measurement="deterministic",
                anchor=f"{base_sha[:12]}..{candidate_sha[:12]}",
                explanation="Production code changed without a changed test file and without a supplied causal/preservation certificate. Existing tests may still cover it; DiffWitness records the missing change-specific regression evidence rather than claiming zero coverage.",
                evidence={"production_files": [file.path for file in production_files]},
                verification={
                    "type": "historical-discrimination",
                    "origin_base_sha": base_sha,
                    "origin_candidate_sha": candidate_sha,
                },
                introduced_by=introduced_by,
            )
        )
    if production_files and not any(is_documentation_path(file.path) for file in files):
        churn = sum(hunk.additions + hunk.deletions for file in production_files for hunk in file.hunks)
        if churn >= 450:
            signals.append(
                DebtSignal(
                    category="knowledge",
                    rule_id="knowledge.large-change-no-doc-update",
                    title="Large change without knowledge artifact update",
                    severity="low",
                    measurement="heuristic",
                    anchor=f"{base_sha[:12]}..{candidate_sha[:12]}",
                    explanation=f"A {churn}-line production change does not include documentation/ADR-like files. This is a knowledge-transfer heuristic, not proof that documentation is required.",
                    evidence={"changed_lines": churn},
                    verification=_change_review("knowledge.large-change-no-doc-update", introduced_by),
                    introduced_by=introduced_by,
                )
            )
    if production_files and any(_sensitive(file.path) for file in production_files):
        paths = sorted(file.path for file in production_files if _sensitive(file.path))
        if behavior_backed:
            signals.append(
                DebtSignal(
                    category="security",
                    rule_id="security.sensitive-surface-change",
                    title="Security-sensitive surface changed",
                    severity="low",
                    measurement="heuristic",
                    anchor="|".join(paths),
                    explanation="Auth/billing/secret/permission-like paths changed. Behavioral evidence is present, so DiffWitness records only a light security-review obligation; the behavioral proof is not itself a security proof.",
                    evidence={"paths": paths, "certificate_id": certificate_id},
                    verification=_change_review("security.sensitive-surface-change", introduced_by),
                    introduced_by=introduced_by,
                )
            )
        else:
            signals.append(
                DebtSignal(
                    category="security",
                    rule_id="security.sensitive-surface-unproven",
                    title="Sensitive surface changed without accepted behavioral evidence",
                    severity="high",
                    measurement="heuristic",
                    anchor="|".join(paths),
                    explanation="Auth/billing/secret/permission-like paths changed without a supplied causal or preservation certificate. The path classifier is heuristic; the obligation is to make the behavioral claim explicit.",
                    evidence={"paths": paths, "certificate_id": certificate_id},
                    verification={
                        "type": "rerun-proof",
                        "origin_base_sha": base_sha,
                        "origin_candidate_sha": candidate_sha,
                    },
                    introduced_by=introduced_by,
                )
            )
    return DebtReport(
        scope="change",
        signals=dedupe_signals(signals),
        repo=str(repo),
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        candidate_tree=candidate_tree,
        certificate_id=certificate_id,
        metadata={
            "changed_files": len(files),
            "production_files": len(production_files),
            "test_files": len(test_files),
            "production_mutations": len(mutations),
            "behavior_backed": behavior_backed,
        },
    )


def _iter_project_files(repo: Path, *, max_files: int) -> list[Path]:
    result: list[Path] = []
    for raw in git(repo, "ls-files").splitlines():
        path = repo / raw
        if not path.is_file() or path.stat().st_size > 512_000 or not _is_source(raw):
            continue
        result.append(path)
        if len(result) >= max_files:
            break
    return result


def _normalized_blocks(path: Path, *, block_size: int = 8) -> list[tuple[str, int, str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    compact = [
        (index + 1, re.sub(r"\s+", " ", line.strip())) for index, line in enumerate(lines)
    ]
    compact = [
        (line, text)
        for line, text in compact
        if text and not text.startswith(("#", "//", "/*", "*"))
    ]
    blocks: list[tuple[str, int, str]] = []
    for index in range(0, max(0, len(compact) - block_size + 1)):
        group = compact[index : index + block_size]
        text = "\n".join(value for _, value in group)
        if len(text) < 180:
            continue
        blocks.append((hashlib.sha256(text.encode("utf-8")).hexdigest(), group[0][0], text))
    return blocks


def _project_duplicate_signals(
    repo: Path, files: list[Path], *, limit: int
) -> list[DebtSignal]:
    seen: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for path in files:
        rel = path.relative_to(repo).as_posix()
        for digest, line, text in _normalized_blocks(path):
            seen[digest].append((rel, line, text))
    signals: list[DebtSignal] = []
    for digest, locations in seen.items():
        unique_files = {path for path, _, _ in locations}
        if len(unique_files) < 2:
            continue
        locs = sorted({(path, line) for path, line, _ in locations})
        signals.append(
            DebtSignal(
                category="redundancy",
                rule_id="project.exact-duplicate-block",
                title="Exact normalized code block duplicated across files",
                severity="low" if len(locs) == 2 else "medium",
                measurement="deterministic",
                anchor=digest[:20],
                path=locs[0][0],
                line=locs[0][1],
                explanation=f"An 8-line normalized code block appears at {len(locs)} locations across {len(unique_files)} files. This is exact textual redundancy after whitespace normalization; consolidation may or may not be architecturally desirable.",
                evidence={"locations": [{"path": path, "line": line} for path, line in locs[:20]]},
                verification={"type": "project-rule", "rule_id": "project.exact-duplicate-block"},
                tags=["project-scan"],
            )
        )
        if len(signals) >= limit:
            break
    return signals


def _relative_import_target(source: str, target: str) -> str | None:
    if target.startswith(".") and not target.startswith(("./", "../")):
        dots = len(target) - len(target.lstrip("."))
        rest = target[dots:].replace(".", "/")
        parent = PurePosixPath(source).parent
        for _ in range(max(0, dots - 1)):
            parent = parent.parent
        return (parent / rest).as_posix() if rest else parent.as_posix()
    if target.startswith(("./", "../")):
        parts = list(PurePosixPath(source).parent.parts)
        for part in PurePosixPath(target).parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        return PurePosixPath(*parts).as_posix()
    return None


def _project_import_cycle_signals(repo: Path, files: list[Path]) -> list[DebtSignal]:
    rels = {path.relative_to(repo).as_posix() for path in files}
    stems: dict[str, str] = {}
    for rel in rels:
        path = PurePosixPath(rel)
        stems[path.with_suffix("").as_posix()] = rel
        stems[(path.parent / "index").with_suffix("").as_posix()] = rel
    graph: dict[str, set[str]] = defaultdict(set)
    for path in files:
        rel = path.relative_to(repo).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in IMPORT_RE.finditer(text):
            raw = next((value for value in match.groups() if value), None)
            if not raw:
                continue
            target = _relative_import_target(rel, raw)
            if not target:
                continue
            resolved = next(
                (stems[candidate] for candidate in (target, target + "/index") if candidate in stems),
                None,
            )
            if resolved and resolved != rel:
                graph[rel].add(resolved)
    cycles: set[tuple[str, ...]] = set()
    visiting: list[str] = []
    in_stack: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in done:
            return
        if node in in_stack:
            start = visiting.index(node)
            cycle = visiting[start:]
            cycles.add(min(tuple(cycle[index:] + cycle[:index]) for index in range(len(cycle))))
            return
        in_stack.add(node)
        visiting.append(node)
        for nxt in sorted(graph.get(node, set())):
            visit(nxt)
        visiting.pop()
        in_stack.remove(node)
        done.add(node)

    for node in sorted(graph):
        visit(node)
    return [
        DebtSignal(
            category="architecture",
            rule_id="project.local-import-cycle",
            title="Local module import cycle detected",
            severity="medium",
            measurement="deterministic",
            anchor="->".join(cycle),
            path=cycle[0],
            explanation="DiffWitness resolved a cycle through local relative imports. Dynamic/runtime import behavior can differ, but the static local dependency graph is cyclic.",
            evidence={"cycle": list(cycle)},
            verification={"type": "project-rule", "rule_id": "project.local-import-cycle"},
            tags=["project-scan"],
        )
        for cycle in sorted(cycles)[:20]
    ]


def _project_file_signals(repo: Path, files: list[Path]) -> list[DebtSignal]:
    signals: list[DebtSignal] = []
    rels = {path.relative_to(repo).as_posix() for path in files}
    for path in files:
        rel = path.relative_to(repo).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        test_file = is_test_path(rel)
        if len(lines) >= 900:
            signals.append(
                DebtSignal(
                    category="complexity",
                    rule_id="project.large-source-file",
                    title="Very large source file",
                    severity="medium" if len(lines) < 1500 else "high",
                    measurement="deterministic",
                    anchor=rel,
                    path=rel,
                    explanation=f"This tracked source file contains {len(lines)} lines. File size is a maintenance-cost signal, not proof that the design should be split.",
                    evidence={"lines": len(lines)},
                    verification={"type": "project-rule", "rule_id": "project.large-source-file"},
                    tags=["project-scan"],
                )
            )
        if not test_file and _sensitive(rel):
            p = PurePosixPath(rel)
            stem = p.stem.lower()
            candidates = (
                (p.parent / f"test_{p.name}").as_posix(),
                (p.parent / f"{stem}_test{p.suffix}").as_posix(),
                (p.parent / f"{stem}.test{p.suffix}").as_posix(),
                (p.parent / f"{stem}.spec{p.suffix}").as_posix(),
                (PurePosixPath("tests") / p).as_posix(),
            )
            if not any(candidate in rels for candidate in candidates):
                signals.append(
                    DebtSignal(
                        category="test",
                        rule_id="project.sensitive-file-no-obvious-test-companion",
                        title="Sensitive module has no obvious test companion",
                        severity="low",
                        measurement="heuristic",
                        anchor=rel,
                        path=rel,
                        explanation="A path classified as auth/billing/permission/secret-sensitive has no conventionally named test companion. Tests may exist elsewhere; this is intentionally only a discoverability heuristic.",
                        verification={
                            "type": "project-rule",
                            "rule_id": "project.sensitive-file-no-obvious-test-companion",
                        },
                        tags=["project-scan"],
                    )
                )
        if test_file:
            continue
        for hit in scan_security_text(rel, text):
            anchor = hashlib.sha256(
                f"{rel}\0{hit.rule_id}\0{hit.match}".encode("utf-8")
            ).hexdigest()[:16]
            signals.append(
                DebtSignal(
                    category="security",
                    rule_id=hit.rule_id,
                    title=hit.title,
                    severity=hit.severity,
                    measurement="deterministic",
                    anchor=anchor,
                    path=rel,
                    line=hit.line,
                    explanation=hit.explanation,
                    evidence={"match": hit.match},
                    verification={"type": "project-rule", "rule_id": hit.rule_id},
                    tags=["project-scan"],
                )
            )
    return signals


def scan_project(
    *,
    repo: Path,
    duplicate_scan: bool = True,
    max_scan_files: int = 500,
    max_duplicate_signals: int = 20,
) -> DebtReport:
    files = _iter_project_files(repo, max_files=max_scan_files)
    signals = _project_file_signals(repo, files)
    signals.extend(_project_import_cycle_signals(repo, files))
    if duplicate_scan:
        signals.extend(_project_duplicate_signals(repo, files, limit=max_duplicate_signals))
    head = git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip()
    tree = _candidate_tree(repo, head)
    return DebtReport(
        scope="project",
        signals=dedupe_signals(signals),
        repo=str(repo),
        candidate_sha=head,
        candidate_tree=tree,
        metadata={"scanned_source_files": len(files), "scan_file_limit": max_scan_files},
    )
