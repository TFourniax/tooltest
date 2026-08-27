from __future__ import annotations

from pathlib import Path
from typing import Any

from .debt_models import DebtReport
from .debt_sensor import DebtSensorResult, merge_sensor_result
from .p1_sensors import (
    AGENT_EXPANSION_SENSOR_ID,
    PARALLEL_SOURCE_SENSOR_ID,
    SECURITY_POLICY_SENSOR_ID,
    AgentExpansionSensor,
    ParallelSourceOfTruthSensor,
    security_policy_from_semantic,
)
from .semantic_redundancy import RULE_ID as SEMANTIC_RULE_ID
from .semantic_redundancy import SENSOR_ID as SEMANTIC_SENSOR_ID
from .semantic_redundancy import SemanticRedundancySensor


def _already(report: DebtReport, sensor_id: str) -> bool:
    return sensor_id in (report.metadata.get("debt_sensors") or {})


def _mark_degraded(report: DebtReport, sensor_id: str, exc: Exception) -> None:
    sensors = dict(report.metadata.get("debt_sensors") or {})
    sensors[sensor_id] = {"status": "degraded", "signals": 0, "error": f"{type(exc).__name__}: {exc}"[:240], "non_blocking": True}
    report.metadata["debt_sensors"] = sensors


def _mark_skipped(report: DebtReport, sensor_id: str, reason: str) -> None:
    sensors = dict(report.metadata.get("debt_sensors") or {})
    sensors[sensor_id] = {"status": "skipped", "signals": 0, "reason": reason, "non_blocking": True}
    report.metadata["debt_sensors"] = sensors


def _semantic_from_report(report: DebtReport) -> DebtSensorResult:
    return DebtSensorResult(sensor_id=SEMANTIC_SENSOR_ID, signals=[signal for signal in report.signals if signal.rule_id == SEMANTIC_RULE_ID], metadata={"reused_from_report": True})


def enrich_change_with_sensors(report: DebtReport, config: dict[str, Any]) -> None:
    """Run advisory sensors after the authoritative proof/debt report exists.

    Every sensor is isolated: failure degrades that sensor only. Current sensor findings are
    heuristic zero-point observations, so they cannot alter proof verdicts or debt admission budgets.
    """
    if report.scope != "change" or not report.repo or not report.base_sha or not report.candidate_sha:
        return
    repo = Path(report.repo)
    semantic_result: DebtSensorResult | None = None

    if bool(config.get("semantic_redundancy_scan", True)):
        if _already(report, SEMANTIC_SENSOR_ID):
            semantic_result = _semantic_from_report(report)
        else:
            try:
                semantic_result = SemanticRedundancySensor(
                    threshold=float(config.get("semantic_redundancy_threshold", 0.88)),
                    max_files=int(config.get("max_scan_files", 500)),
                    max_signals=int(config.get("max_semantic_redundancy_signals", 20)),
                    min_tokens=int(config.get("semantic_redundancy_min_tokens", 32)),
                ).scan_change(repo=repo, base_sha=report.base_sha, candidate_sha=report.candidate_sha)
                merge_sensor_result(report, semantic_result)
            except Exception as exc:
                _mark_degraded(report, SEMANTIC_SENSOR_ID, exc)

    if bool(config.get("duplicate_security_policy_scan", True)) and not _already(report, SECURITY_POLICY_SENSOR_ID):
        if semantic_result is None:
            _mark_skipped(report, SECURITY_POLICY_SENSOR_ID, "semantic redundancy dependency unavailable")
        else:
            try:
                merge_sensor_result(report, security_policy_from_semantic(semantic_result, max_signals=int(config.get("max_security_policy_signals", 20))))
            except Exception as exc:
                _mark_degraded(report, SECURITY_POLICY_SENSOR_ID, exc)

    if bool(config.get("parallel_source_scan", True)) and not _already(report, PARALLEL_SOURCE_SENSOR_ID):
        try:
            merge_sensor_result(
                report,
                ParallelSourceOfTruthSensor(max_files=int(config.get("max_scan_files", 500)), max_signals=int(config.get("max_parallel_source_signals", 20))).scan_change(
                    repo=repo, base_sha=report.base_sha, candidate_sha=report.candidate_sha
                ),
            )
        except Exception as exc:
            _mark_degraded(report, PARALLEL_SOURCE_SENSOR_ID, exc)

    if bool(config.get("agent_expansion_scan", True)) and not _already(report, AGENT_EXPANSION_SENSOR_ID):
        try:
            merge_sensor_result(
                report,
                AgentExpansionSensor(max_signals=int(config.get("max_agent_expansion_signals", 1))).scan_change(
                    repo=repo, base_sha=report.base_sha, candidate_sha=report.candidate_sha
                ),
            )
        except Exception as exc:
            _mark_degraded(report, AGENT_EXPANSION_SENSOR_ID, exc)


def enrich_project_with_sensors(report: DebtReport, *, repo: Path, candidate_sha: str, config: dict[str, Any]) -> None:
    semantic_result: DebtSensorResult | None = None

    if bool(config.get("semantic_redundancy_scan", True)):
        if _already(report, SEMANTIC_SENSOR_ID):
            semantic_result = _semantic_from_report(report)
        else:
            try:
                semantic_result = SemanticRedundancySensor(
                    threshold=float(config.get("semantic_redundancy_threshold", 0.88)),
                    max_files=int(config.get("max_scan_files", 500)),
                    max_signals=int(config.get("max_semantic_redundancy_signals", 20)),
                    min_tokens=int(config.get("semantic_redundancy_min_tokens", 32)),
                ).scan_project(repo=repo, candidate_sha=candidate_sha)
                merge_sensor_result(report, semantic_result)
            except Exception as exc:
                _mark_degraded(report, SEMANTIC_SENSOR_ID, exc)

    if bool(config.get("duplicate_security_policy_scan", True)) and not _already(report, SECURITY_POLICY_SENSOR_ID):
        if semantic_result is None:
            _mark_skipped(report, SECURITY_POLICY_SENSOR_ID, "semantic redundancy dependency unavailable")
        else:
            try:
                merge_sensor_result(report, security_policy_from_semantic(semantic_result, max_signals=int(config.get("max_security_policy_signals", 20))))
            except Exception as exc:
                _mark_degraded(report, SECURITY_POLICY_SENSOR_ID, exc)

    if bool(config.get("parallel_source_scan", True)) and not _already(report, PARALLEL_SOURCE_SENSOR_ID):
        try:
            merge_sensor_result(
                report,
                ParallelSourceOfTruthSensor(max_files=int(config.get("max_scan_files", 500)), max_signals=int(config.get("max_parallel_source_signals", 20))).scan_project(
                    repo=repo, candidate_sha=candidate_sha
                ),
            )
        except Exception as exc:
            _mark_degraded(report, PARALLEL_SOURCE_SENSOR_ID, exc)
