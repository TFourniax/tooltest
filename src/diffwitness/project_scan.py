from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

from .debt_models import DebtReport
from .debt_scan import scan_project as _scan_project
from .diffing import is_test_path
from .gitops import detached_worktree, snapshot_worktree
from .sensor_runtime import enrich_project_with_sensors


def _python_top_level_targets(repo: Path, source: str) -> set[str] | None:
    """Resolve local Python imports executed during module initialization."""
    path = repo / source
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return None

    parent = PurePosixPath(source).parent
    targets: set[str] = set()

    def add_candidate(base: PurePosixPath) -> None:
        module = base.as_posix()
        for candidate in (module + ".py", module + "/__init__.py"):
            if (repo / candidate).is_file():
                targets.add(candidate)

    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level < 1:
            continue
        base = parent
        for _ in range(max(0, node.level - 1)):
            base = base.parent
        if node.module:
            add_candidate(base / node.module.replace(".", "/"))
        else:
            for alias in node.names:
                if alias.name != "*":
                    add_candidate(base / alias.name.replace(".", "/"))
    return targets


def _filter_project_noise(repo: Path, report: DebtReport) -> tuple[DebtReport, dict[str, int]]:
    kept = []
    removed_lazy_cycles = 0
    removed_test_duplicates = 0

    for signal in report.signals:
        if signal.rule_id == "project.exact-duplicate-block":
            locations = signal.evidence.get("locations") if isinstance(signal.evidence, dict) else None
            if isinstance(locations, list) and locations:
                paths = [str(item.get("path") or "") for item in locations if isinstance(item, dict)]
                if paths and all(is_test_path(path) for path in paths):
                    removed_test_duplicates += 1
                    continue

        if signal.rule_id == "project.local-import-cycle":
            cycle = signal.evidence.get("cycle") if isinstance(signal.evidence, dict) else None
            if isinstance(cycle, list) and len(cycle) >= 2 and all(PurePosixPath(str(path)).suffix.lower() == ".py" for path in cycle):
                parsed = True
                runtime_cycle = True
                normalized = [str(path) for path in cycle]
                for index, source in enumerate(normalized):
                    target = normalized[(index + 1) % len(normalized)]
                    targets = _python_top_level_targets(repo, source)
                    if targets is None:
                        parsed = False
                        break
                    if target not in targets:
                        runtime_cycle = False
                        break
                if parsed and not runtime_cycle:
                    removed_lazy_cycles += 1
                    continue

        kept.append(signal)

    report.signals = kept
    return report, {"filtered_lazy_python_cycles": removed_lazy_cycles, "filtered_test_fixture_duplicates": removed_test_duplicates}


def scan_project(
    *,
    repo: Path,
    duplicate_scan: bool = True,
    max_scan_files: int = 500,
    max_duplicate_signals: int = 20,
    semantic_redundancy_scan: bool = True,
    semantic_redundancy_threshold: float = 0.88,
    semantic_redundancy_min_tokens: int = 32,
    max_semantic_redundancy_signals: int = 20,
    parallel_source_scan: bool = True,
    max_parallel_source_signals: int = 20,
    duplicate_security_policy_scan: bool = True,
    max_security_policy_signals: int = 20,
) -> DebtReport:
    """Scan an immutable snapshot of the current worktree.

    The deterministic project scan remains authoritative for deterministic debt rules. Debt Sensors
    run only after that scan and are advisory extensions: they cannot affect DiffWitness Proof
    classifications. Current semantic/P1 sensor findings carry zero debt points while precision is
    benchmarked on real repositories.
    """
    candidate_sha = snapshot_worktree(repo)
    with detached_worktree(repo, candidate_sha, "debt-health-snapshot") as snapshot:
        report = _scan_project(repo=snapshot, duplicate_scan=duplicate_scan, max_scan_files=max_scan_files, max_duplicate_signals=max_duplicate_signals)
        report, filtered = _filter_project_noise(snapshot, report)
        enrich_project_with_sensors(
            report,
            repo=snapshot,
            candidate_sha=candidate_sha,
            config={
                "max_scan_files": max_scan_files,
                "semantic_redundancy_scan": semantic_redundancy_scan,
                "semantic_redundancy_threshold": semantic_redundancy_threshold,
                "semantic_redundancy_min_tokens": semantic_redundancy_min_tokens,
                "max_semantic_redundancy_signals": max_semantic_redundancy_signals,
                "parallel_source_scan": parallel_source_scan,
                "max_parallel_source_signals": max_parallel_source_signals,
                "duplicate_security_policy_scan": duplicate_security_policy_scan,
                "max_security_policy_signals": max_security_policy_signals,
            },
        )
    report.repo = str(repo)
    report.metadata = {**report.metadata, **filtered, "scan_source": "worktree-snapshot", "snapshot_sha": candidate_sha}
    return report
