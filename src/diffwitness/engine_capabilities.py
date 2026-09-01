from __future__ import annotations

import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .engine_protocol import ENGINE_PLAN_SCHEMA, ENGINE_REQUEST_SCHEMA, EngineProtocolError, _strict_json_loads
from .runner import _popen_group_kwargs, _terminate_process_tree


CAPABILITIES_SCHEMA = "engine-capabilities-1"
MAX_CAPABILITIES_BYTES = 64 * 1024
MAX_STDERR_TAIL_BYTES = 2000
_CAPABILITY_KEYS = {"schema_version", "engine", "protocol", "limits", "privacy", "authority"}
_ENGINE_KEYS = {"name", "version"}
_PROTOCOL_KEYS = {"request", "plan"}
_PRIVACY_KEYS = {
    "accepts_embedded_source", "supports_metadata_only", "supports_local_candidate_object_reads"
}
_AUTHORITY_KEYS = {"advisory_only", "executes_evidence_commands", "writes_target_repository"}


class EngineCapabilityError(EngineProtocolError):
    pass


def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise EngineCapabilityError(f"{label} contains unknown field(s): {', '.join(unknown)}")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EngineCapabilityError(f"{label} must be an object")
    return value


def validate_engine_capabilities(value: Any) -> dict[str, Any]:
    capabilities = _object(value, "engine capabilities")
    _reject_unknown(capabilities, _CAPABILITY_KEYS, "engine capabilities")
    if capabilities.get("schema_version") != CAPABILITIES_SCHEMA:
        raise EngineCapabilityError("unsupported engine capabilities schema")

    engine = _object(capabilities.get("engine"), "engine capabilities.engine")
    _reject_unknown(engine, _ENGINE_KEYS, "engine capabilities.engine")
    name = engine.get("name")
    version = engine.get("version")
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise EngineCapabilityError("engine capability name must be a non-empty string <= 128 characters")
    if not isinstance(version, str) or not version.strip() or len(version) > 64:
        raise EngineCapabilityError("engine capability version must be a non-empty string <= 64 characters")

    protocol = _object(capabilities.get("protocol"), "engine capabilities.protocol")
    _reject_unknown(protocol, _PROTOCOL_KEYS, "engine capabilities.protocol")
    if protocol.get("request") != ENGINE_REQUEST_SCHEMA or protocol.get("plan") != ENGINE_PLAN_SCHEMA:
        raise EngineCapabilityError(
            f"engine protocol is incompatible; expected {ENGINE_REQUEST_SCHEMA}/{ENGINE_PLAN_SCHEMA}"
        )

    limits = _object(capabilities.get("limits"), "engine capabilities.limits")
    if len(limits) > 64:
        raise EngineCapabilityError("engine capabilities.limits is unexpectedly large")
    normalized_limits: dict[str, int] = {}
    for key, raw in limits.items():
        if not isinstance(key, str) or not key or len(key) > 128:
            raise EngineCapabilityError("engine capability limit names must be bounded strings")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise EngineCapabilityError(f"engine capability limit {key} must be a non-negative integer")
        normalized_limits[key] = raw
    if normalized_limits.get("request_bytes", 0) < 1024:
        raise EngineCapabilityError("engine request byte limit is missing or unusably small")
    if normalized_limits.get("mutations", 0) < 1:
        raise EngineCapabilityError("engine mutation limit is missing or unusably small")

    privacy = _object(capabilities.get("privacy"), "engine capabilities.privacy")
    _reject_unknown(privacy, _PRIVACY_KEYS, "engine capabilities.privacy")
    if privacy.get("accepts_embedded_source") is not False:
        raise EngineCapabilityError("engine capability boundary must refuse embedded source")
    if privacy.get("supports_metadata_only") is not True:
        raise EngineCapabilityError("engine must support metadata-only planning")
    if not isinstance(privacy.get("supports_local_candidate_object_reads"), bool):
        raise EngineCapabilityError("engine local candidate-read capability must be boolean")

    authority = _object(capabilities.get("authority"), "engine capabilities.authority")
    _reject_unknown(authority, _AUTHORITY_KEYS, "engine capabilities.authority")
    expected_authority = {
        "advisory_only": True,
        "executes_evidence_commands": False,
        "writes_target_repository": False,
    }
    if authority != expected_authority:
        raise EngineCapabilityError(
            "engine authority boundary is incompatible; advisory planners may not execute evidence or write the repository"
        )

    return {
        "schema_version": CAPABILITIES_SCHEMA,
        "engine": {"name": name.strip(), "version": version.strip()},
        "protocol": {"request": ENGINE_REQUEST_SCHEMA, "plan": ENGINE_PLAN_SCHEMA},
        "limits": normalized_limits,
        "privacy": dict(privacy),
        "authority": expected_authority,
    }


def _file_size(handle) -> int:
    handle.flush()
    return os.fstat(handle.fileno()).st_size


def _read_tail(handle, limit: int) -> str:
    size = _file_size(handle)
    handle.seek(max(0, size - limit))
    return handle.read(limit).decode("utf-8", errors="replace").strip()


def inspect_engine_capabilities(
    *,
    cwd: Path,
    command: Sequence[str],
    timeout: float = 2.0,
) -> dict[str, Any]:
    cmd = [str(item) for item in command if str(item)]
    if not cmd:
        raise EngineCapabilityError("no advisory engine command configured")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(float(timeout)) or timeout <= 0:
        raise EngineCapabilityError("engine capability timeout must be a finite number > 0")

    proc: subprocess.Popen[bytes] | None = None
    try:
        with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
            proc = subprocess.Popen(
                [*cmd, "--capabilities"],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=os.environ.copy(),
                **_popen_group_kwargs(),
            )
            try:
                proc.wait(timeout=float(timeout))
            except subprocess.TimeoutExpired as exc:
                _terminate_process_tree(proc)
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    proc.wait()
                raise EngineCapabilityError(
                    f"advisory engine capabilities exceeded {float(timeout):g}s timeout"
                ) from exc

            stderr_tail = _read_tail(stderr_file, MAX_STDERR_TAIL_BYTES)
            if proc.returncode != 0:
                raise EngineCapabilityError(
                    f"advisory engine --capabilities exited with {proc.returncode}"
                    + (f": {stderr_tail}" if stderr_tail else "")
                )
            size = _file_size(stdout_file)
            if size > MAX_CAPABILITIES_BYTES:
                raise EngineCapabilityError("advisory engine capabilities response exceeds 64 KiB")
            stdout_file.seek(0)
            try:
                text = stdout_file.read().decode("utf-8")
            except UnicodeDecodeError as exc:
                raise EngineCapabilityError("advisory engine capabilities are not UTF-8") from exc
            return validate_engine_capabilities(_strict_json_loads(text))
    except OSError as exc:
        if proc is not None and proc.poll() is None:
            _terminate_process_tree(proc)
        raise EngineCapabilityError(f"cannot execute advisory engine: {exc}") from exc
