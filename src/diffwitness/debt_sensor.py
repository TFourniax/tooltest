from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .debt_models import DebtReport, DebtSignal, dedupe_signals


@dataclass(slots=True)
class DebtSensorResult:
    """Normalized output contract for advisory debt sensors.

    Sensors are deliberately downstream from DiffWitness Proof: they may observe architecture,
    redundancy, dependencies, or other maintenance risks, but they cannot alter a proof verdict.
    """

    sensor_id: str
    signals: list[DebtSignal] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class DebtSensor(Protocol):
    """Small extension contract for independent debt detectors."""

    sensor_id: str

    def scan_change(self, *, repo: Any, base_sha: str, candidate_sha: str) -> DebtSensorResult: ...

    def scan_project(self, *, repo: Any, candidate_sha: str) -> DebtSensorResult: ...


def _normalize_verification(signal: DebtSignal) -> None:
    """Normalize the temporary sensor alias without widening the durable Ledger contract.

    The established Debt Ledger verification discriminator is ``type``. Early experimental sensors
    briefly emitted ``kind``. Accept that alias at the sensor boundary only, then persist/report the
    canonical form so recheck consumers never need to understand two schemas.
    """
    verification = dict(signal.verification or {})
    alias = verification.pop("kind", None)
    if alias is not None and "type" not in verification:
        verification["type"] = alias
    signal.verification = verification


def merge_sensor_result(report: DebtReport, result: DebtSensorResult) -> DebtReport:
    """Merge advisory findings without changing the report/proof identity or accounting semantics."""
    for signal in result.signals:
        _normalize_verification(signal)
    report.signals = dedupe_signals([*report.signals, *result.signals])
    sensors = dict(report.metadata.get("debt_sensors") or {})
    sensors[result.sensor_id] = {
        "signals": len(result.signals),
        **result.metadata,
    }
    report.metadata["debt_sensors"] = sensors
    return report
