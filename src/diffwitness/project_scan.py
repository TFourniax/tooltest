from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

from .debt_models import DebtReport
from .debt_sensor import merge_sensor_result
from .debt_scan import scan_project as _scan_project
from .diffing import is_test_path
from .gitops import detached_worktree, snapshot_worktree
from .semantic_redundancy import SENSOR_ID as SEMANTIC_REDUNDANCY_SENSOR_ID, SemanticRedundancySensor


def _python_top_level_targets(repo: Path, source: str) -> set[str] | None:
    """Resolve local Python imports executed during module initialization.

    The low-level cross-language scanner deliberately uses a broad regex to discover possible local
    edges. For Python health reporting we can be more precise: imports nested in a function are lazy
    and cannot form an import-initialization cycle merely by existing in the source. Returning None
    on parse failure preserves the conservative low-level result rather than inventing certainty.
    """
    path = repo / source
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return None

    parent = PurePosixPath(source).parent
    targets: set[str] = set()

    def add_candidate(base: PurePosixPath) -> None:
        module = base.as_posix()
        candidates = (module + ".py", module + "/__init__.py")
        for candidate in candidates:
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
            if isinstance(cycle, list) and len(cycle) >= 2 and all(
                PurePosixPath(str(path)).suffix.lower() == ".py" for path in cycle
            ):
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
    return report, {
        "filtered_lazy_python_cycles": removed_lazy_cycles,
        "filtered_test_fixture_duplicates": removed_test_duplicates,
    }


def _mark_sensor_degraded(report: DebtReport, exc: Exception) -> None:
    sensors = dict(report.metadata.get("debt_sensors") or {})
    sensors[SEMANTIC_REDUNDANCY_SENSOR_ID] = {
        "status": "degraded",
        "signals": 0,
        "error": f"{type(exc).__name__}: {exc}"[:240],
        "non_blocking": True,
    }
    report.metadata["debt_sensors"] = sensors


def scan_project(
    *,
    repo: Path,
    duplicate_scan: bool = True,
    max_scan_files: int = 500,
    max_duplicate_signals: int = 20,
    semantic_redundancy_scan: bool = True,
    semantic_redundancy_threshold: float = 0.85,
    semantic_redundancy_min_tokens: int = 32,
    max_semantic_redundancy_signals: int = 20,
) -> DebtReport:
    """Scan an immutable snapshot of the current worktree.

    Debt health is frequently run before a commit exists. The low-level scanner reads files from
    the repository it is given and historically labelled those bytes with that repository's HEAD.
    On a dirty worktree this could make provenance claim HEAD while actually inspecting different
    content. Snapshot first, then scan a detached worktree of exactly that snapshot so every signal
    is bound to the tree that was really analysed.

    A narrow semantic post-pass removes two known sources of project-level accounting noise without
    hiding production debt: Python imports that are lazy/function-local rather than initialization
    edges, and duplicate blocks whose every location is a test file.

    Debt Sensors run only after this deterministic scan. They are advisory extensions and cannot
    affect DiffWitness Proof classifications. Semantic redundancy findings currently carry zero debt
    points by design while precision is benchmarked on real repositories.
    """
    candidate_sha = snapshot_worktree(repo)
    with detached_worktree(repo, candidate_sha, "debt-health-snapshot") as snapshot:
        report = _scan_project(
            repo=snapshot,
            duplicate_scan=duplicate_scan,
            max_scan_files=max_scan_files,
            max_duplicate_signals=max_duplicate_signals,
        )
        report, filtered = _filter_project_noise(snapshot, report)
        if semantic_redundancy_scan:
            try:
                sensor = SemanticRedundancySensor(
                    threshold=semantic_redundancy_threshold,
                    max_files=max_scan_files,
                    max_signals=max_semantic_redundancy_signals,
                    min_tokens=semantic_redundancy_min_tokens,
                )
                merge_sensor_result(
                    report,
                    sensor.scan_project(repo=snapshot, candidate_sha=candidate_sha),
                )
            except Exception as exc:  # advisory sensor failure must not regress health/debt
                _mark_sensor_degraded(report, exc)
    report.repo = str(repo)
    report.metadata = {
        **report.metadata,
        **filtered,
        "scan_source": "worktree-snapshot",
        "snapshot_sha": candidate_sha,
    }
    return report
