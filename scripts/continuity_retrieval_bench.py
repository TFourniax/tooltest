"""Fixed, synthetic FR/EN retrieval acceptance against the real context compiler."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from diffwitness.continuity_context_enriched import compile_context
from diffwitness.continuity_events import append_project_events, continuity_paths, read_project_events
from diffwitness.continuity_lifecycle import lifecycle_spec
from diffwitness.continuity_state import rebuild_state

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("objectives", "tasks", "decisions", "invariants", "failedApproaches")


def run(corpus_path: Path) -> dict:
    raw = corpus_path.read_bytes()
    corpus = json.loads(raw)
    with tempfile.TemporaryDirectory(prefix="dw-retrieval-") as directory:
        repo = Path(directory)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Retrieval Bench",
                        "-c", "user.email=retrieval@example.invalid", "commit", "--allow-empty", "-qm", "baseline"], check=True)
        distractors = [{"event_type": "objective.declared",
            "subject": {"id": f"DISTRACTOR-{i}", "kind": "objective", "label": f"Unrelated archival item {i}"},
            "epistemic_status": "DECLARED", "payload": {}}
            for i in range(corpus["distractors"])]
        append_project_events(repo=repo, events=distractors)
        created = append_project_events(repo=repo, events=corpus["memories"])
        sources = {event["subject"]["id"]: event for event, _ in created}
        for retired in corpus["retire"]:
            append_project_events(repo=repo, events=[lifecycle_spec(
                repo, retired["kind"], retired["id"], "retire", "Historical fixture no longer applicable")])
        rebuild_state(repo)
        journal = continuity_paths(repo).events.read_bytes()
        cases = []
        for case in corpus["cases"]:
            packet = compile_context(repo, case["query"], refresh_structure=False)
            items = sorted((item for category in CATEGORIES for item in packet[category]),
                           key=lambda item: (-item["relevance"], item["id"]))
            actual = [item["id"] for item in items]
            expected = set(case["expected"])
            hits = expected.intersection(actual)
            citation_errors = []
            for item in items:
                source = sources.get(item["id"])
                if source is None or item["source"] != {"kind": "project-event",
                        "eventId": source["event_id"], "eventHash": source["event_hash"]}:
                    citation_errors.append(item["id"])
                elif item["epistemicStatus"] != source["epistemic_status"]:
                    citation_errors.append(item["id"])
            precision = len(hits) / len(actual) if actual else float(not expected)
            recall = len(hits) / len(expected) if expected else float(not actual)
            rank = next((i + 1 for i, identity in enumerate(actual) if identity in expected), None)
            cases.append({**case, "actual": actual, "precision": precision, "recall": recall,
                          "first_relevant_rank": rank, "citation_errors": citation_errors,
                          "passed": set(actual) == expected and not citation_errors})
        unchanged = continuity_paths(repo).events.read_bytes() == journal
        read_project_events(continuity_paths(repo).events)  # Keep strict integrity in the exercised journey.
        metrics = {}
        for language in ("fr", "en"):
            selected = [case for case in cases if case["language"] == language]
            positive = [case for case in selected if case["expected"]]
            metrics[language] = {
                "cases": len(selected), "passed": sum(case["passed"] for case in selected),
                "macro_precision": sum(case["precision"] for case in selected) / len(selected),
                "macro_recall": sum(case["recall"] for case in selected) / len(selected),
                "mrr_positive": sum(1 / case["first_relevant_rank"] if case["first_relevant_rank"] else 0
                                    for case in positive) / len(positive),
            }
        return {"schema_version": "continuity-retrieval-bench-1", "corpus_sha256": hashlib.sha256(raw).hexdigest(),
                "scope": corpus["scope"], "distractors": len(distractors), "metrics": metrics,
                "journal_unchanged": unchanged, "cases": cases,
                "passed": unchanged and all(case["passed"] for case in cases)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "benchmarks/retrieval/fr-en-1.json")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = run(args.corpus)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(output, encoding="utf-8")
    print(output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
