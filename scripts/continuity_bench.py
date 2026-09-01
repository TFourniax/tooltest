from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from diffwitness.continuity_context import compile_context, render_context
from diffwitness.continuity_events import append_project_events, continuity_paths, read_project_events
from diffwitness.continuity_state import rebuild_state


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _repo(root: Path) -> Path:
    repo = root / "bench-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "continuity-bench@example.test")
    _git(repo, "config", "user.name", "Continuity Bench")
    (repo / "payments.py").write_text("def refund(amount):\n    return amount\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "bench base")
    return repo


def _event(index: int, total: int) -> dict:
    relevant = index == total - 1
    label = "Support safe partial refunds" if relevant else f"Historical objective {index:05d}"
    payload = {
        "priority": "critical" if relevant else "normal",
        "why": "refund correctness and idempotency" if relevant else f"historical project fact {index:05d}",
    }
    return {
        "event_type": "objective.declared",
        "subject": {"id": f"OBJ-BENCH-{index:05d}", "kind": "objective", "label": label},
        "epistemic_status": "DECLARED",
        "payload": payload,
        "relations": [],
        "provenance": {"producer": "continuity-bench", "source": "synthetic-scale-fixture"},
        "actor": {"kind": "human", "id": "bench"},
        "dedupe_key": f"bench-objective:{index}",
        "timestamp": f"2026-01-{1 + (index % 28):02d}T00:00:{index % 60:02d}Z",
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[position]


def _compile(repo: Path) -> dict:
    return compile_context(
        repo,
        "implement partial refunds safely in payments",
        max_items=12,
        refresh_structure=True,
    )


def _assert_recall(context: dict, events: int) -> None:
    expected = "OBJ-BENCH-" + f"{events - 1:05d}"
    if expected not in {item["id"] for item in context["objectives"]}:
        raise RuntimeError("Context Compiler failed to recall the scale fixture's relevant objective")


def run(events: int, batch_size: int, context_runs: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="diffwitness-continuity-bench-") as td:
        repo = _repo(Path(td))
        specs = [_event(index, events) for index in range(events)]

        append_started = time.perf_counter()
        for start in range(0, events, batch_size):
            append_project_events(repo=repo, events=specs[start : start + batch_size])
        append_seconds = time.perf_counter() - append_started

        verify_started = time.perf_counter()
        history = read_project_events(continuity_paths(repo).events)
        verify_seconds = time.perf_counter() - verify_started
        if len(history) != events:
            raise RuntimeError(f"event count mismatch: expected {events}, got {len(history)}")

        rebuild_started = time.perf_counter()
        state = rebuild_state(repo, include_structure=True)
        rebuild_seconds = time.perf_counter() - rebuild_started

        # Cold context includes establishing the SHA-256 anchor after a freshly rebuilt strict state.
        cold_started = time.perf_counter()
        cold_context = _compile(repo)
        cold_ms = (time.perf_counter() - cold_started) * 1000.0
        _assert_recall(cold_context, events)

        # Hot contexts represent normal consecutive UserPromptSubmit calls with no ProjectEvent change.
        hot_ms: list[float] = []
        context = cold_context
        for _ in range(context_runs):
            started = time.perf_counter()
            context = _compile(repo)
            hot_ms.append((time.perf_counter() - started) * 1000.0)
            _assert_recall(context, events)
        rendered = render_context(context, max_chars=6500)

        return {
            "schema_version": "continuity-bench-2",
            "events": events,
            "batch_size": batch_size,
            "event_log_bytes": continuity_paths(repo).events.stat().st_size,
            "state_db_bytes": state.stat().st_size,
            "append_seconds": round(append_seconds, 6),
            "full_log_verify_seconds": round(verify_seconds, 6),
            "rebuild_seconds": round(rebuild_seconds, 6),
            "context": {
                "cold_ms": round(cold_ms, 3),
                "hot_runs": context_runs,
                "hot_ms": {
                    "min": round(min(hot_ms), 3),
                    "median": round(statistics.median(hot_ms), 3),
                    "p95": round(_percentile(hot_ms, 0.95), 3),
                    "max": round(max(hot_ms), 3),
                },
            },
            "context_chars": len(rendered),
            "context_id": context["context_id"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark DiffWitness Continuity at realistic longitudinal scale.")
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=2_000)
    parser.add_argument("--context-runs", type=int, default=7)
    parser.add_argument("--max-append-seconds", type=float, default=10.0)
    parser.add_argument("--max-verify-seconds", type=float, default=2.0)
    parser.add_argument("--max-rebuild-seconds", type=float, default=5.0)
    parser.add_argument("--max-context-cold-ms", type=float, default=1000.0)
    parser.add_argument("--max-context-hot-p95-ms", type=float, default=300.0)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.events < 1 or args.batch_size < 1 or args.context_runs < 1:
        parser.error("events, batch-size and context-runs must be positive")

    result = run(args.events, min(args.batch_size, 2048), args.context_runs)
    failures = []
    if result["append_seconds"] > args.max_append_seconds:
        failures.append(f"append {result['append_seconds']}s > {args.max_append_seconds}s")
    if result["full_log_verify_seconds"] > args.max_verify_seconds:
        failures.append(f"verify {result['full_log_verify_seconds']}s > {args.max_verify_seconds}s")
    if result["rebuild_seconds"] > args.max_rebuild_seconds:
        failures.append(f"rebuild {result['rebuild_seconds']}s > {args.max_rebuild_seconds}s")
    if result["context"]["cold_ms"] > args.max_context_cold_ms:
        failures.append(f"context cold {result['context']['cold_ms']}ms > {args.max_context_cold_ms}ms")
    if result["context"]["hot_ms"]["p95"] > args.max_context_hot_p95_ms:
        failures.append(
            f"context hot p95 {result['context']['hot_ms']['p95']}ms > {args.max_context_hot_p95_ms}ms"
        )
    result["passed"] = not failures
    result["failures"] = failures

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
