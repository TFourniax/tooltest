from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .reporting import render_markdown


def is_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_prop(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def emit_annotations(report: dict[str, Any]) -> None:
    for result in report["results"]:
        status = result["status"]
        if status == "witnessed":
            continue
        mutation = result["mutation"]
        level = "warning" if status == "unwitnessed" else "notice"
        title = "DiffWitness: no causal witness" if status == "unwitnessed" else "DiffWitness: inconclusive"
        message = (
            "Selected evidence stays green when this hunk is removed. Review for scope creep, redundancy, or missing tests."
            if status == "unwitnessed"
            else "DiffWitness could not make a stable causal claim for this hunk."
        )
        props = [f"file={_escape_prop(mutation['path'])}", f"title={_escape_prop(title)}"]
        if mutation.get("line"):
            props.append(f"line={mutation['line']}")
        if mutation.get("end_line"):
            props.append(f"endLine={mutation['end_line']}")
        print(f"::{level} {','.join(props)}::{_escape_data(message)}")


def write_step_summary(report: dict[str, Any]) -> None:
    raw = os.environ.get("GITHUB_STEP_SUMMARY")
    if not raw:
        return
    path = Path(raw)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(render_markdown(report))
        handle.write("\n")


def write_outputs(report: dict[str, Any]) -> None:
    raw = os.environ.get("GITHUB_OUTPUT")
    if not raw:
        return
    summary = report["summary"]
    values = {
        "certificate_id": report["certificate_id"],
        "contrast": report["contrast"],
        "witnessed": summary["witnessed"],
        "unwitnessed": summary["unwitnessed"],
        "inconclusive": summary["inconclusive"],
        "witness_ratio": "" if summary["witness_ratio"] is None else f"{summary['witness_ratio']:.6f}",
        "minimal_sufficient_order": summary["minimal_sufficient_order"] or "",
        "surplus_candidate_hunks": summary["surplus_candidate_hunks"],
    }
    with Path(raw).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")
