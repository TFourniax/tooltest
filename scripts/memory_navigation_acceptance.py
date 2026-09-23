"""Installed CLI journey for read-only, source-cited Project Memory navigation."""
from __future__ import annotations

import json
import argparse
import subprocess
import tempfile
from pathlib import Path

from diffwitness.continuity_events import continuity_paths, read_project_events
from diffwitness.runtime_executable import resolve_dw_command, resolve_explicit_command


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dw")
    options = parser.parse_args()
    dw = resolve_explicit_command(options.dw, setting="--dw") if options.dw else resolve_dw_command()
    with tempfile.TemporaryDirectory(prefix="dw-memory-navigation-") as temporary:
        repo = Path(temporary)

        def run(*args: str, expected: int = 0) -> str:
            process = subprocess.run(args, cwd=repo, text=True, encoding="utf-8", capture_output=True,
                                     timeout=30, check=False)
            if process.returncode != expected:
                raise AssertionError(f"unexpected exit {process.returncode}: {process.stderr[:3000]}")
            return process.stdout

        for args in (("init", "-q"), ("config", "user.name", "Navigation acceptance"),
                     ("config", "user.email", "navigation@example.test")):
            run("git", *args)
        (repo / "payments.py").write_text("def refund(amount):\n    return amount\n", encoding="utf-8")
        run("git", "add", "payments.py")
        run("git", "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic navigation fixture")
        run(dw, "objective", "add", "Remboursements sûrs", "--id", "OBJ-REFUND", "--why", "Éviter les doublons")
        run(dw, "decision", "record", "Conserver une clé unique", "--id", "DEC-REFUND", "--objective", "OBJ-REFUND",
            "--why", "Une demande ne doit pas déclencher deux remboursements")
        run(dw, "failed-approach", "record", "Réessayer sans clé", "--id", "APP-RETRY", "--decision", "DEC-REFUND",
            "--reason", "Risque de doublons")
        initial = json.loads(run(dw, "state", "why", "DEC-REFUND", "--json"))
        assert {node["id"] for node in initial["nodes"]} == {"OBJ-REFUND", "DEC-REFUND", "APP-RETRY"}
        assert {edge["predicate"] for edge in initial["relationships"]} == {"motivated_by", "informed"}
        assert all(node["epistemicStatus"] == "DECLARED" for node in initial["nodes"])
        assertion = next(node["source"] for node in initial["nodes"] if node["id"] == "DEC-REFUND")
        run(dw, "decision", "confirm", "DEC-REFUND", "--reason", "Reviewed against the recorded requirement")
        page = json.loads(run(dw, "state", "history", "DEC-REFUND", "--limit", "1", "--json"))
        assert page["nextCursor"] and page["events"][0]["event"]["event_type"] == "decision.confirmed"
        run(dw, "decision", "retire", "DEC-REFUND", "--reason", "Kept only for historical context")
        paths = continuity_paths(repo)
        before = {p: p.read_bytes() for p in (paths.events, paths.state)}
        later = json.loads(run(dw, "state", "history", "DEC-REFUND", "--cursor", page["nextCursor"], "--json"))
        assert later["anchor"] == page["anchor"] and not later["hasMore"]
        assert later["events"][0]["event"]["event_id"] == assertion["eventId"]
        final = json.loads(run(dw, "state", "why", "DEC-REFUND", "--json"))
        root = next(node for node in final["nodes"] if node["id"] == "DEC-REFUND")
        assert root["source"] == assertion and not root["applicability"]["active"]
        assert root["applicability"]["source"]["eventId"] != assertion["eventId"]
        history = {event["event_id"]: event for event in read_project_events(paths.events)}
        opened = json.loads(run(dw, "state", "event", assertion["eventId"], "--hash", assertion["eventHash"], "--json"))
        assert opened["event"] == history[assertion["eventId"]]
        run(dw, "state", "event", assertion["eventId"], "--hash", "0" * 64, expected=2)
        for item in [*final["nodes"], *final["relationships"]]:
            source = item["source"]
            assert source is not None and history[source["eventId"]]["event_hash"] == source["eventHash"]
        assert json.loads(run(dw, "--language", "fr", "state", "why", "DEC-REFUND", "--json")) == final
        assert "Recorded reasons and relationships" in run(dw, "state", "why", "DEC-REFUND")
        assert "Raisons et relations enregistrées" in run(dw, "--language", "fr", "state", "why", "DEC-REFUND")
        run(dw, "state", "history", "DEC-REFUND", "--cursor", "invalid", expected=2)
        assert all(path.read_bytes() == data for path, data in before.items())
        print(json.dumps({"schema": "memory-navigation-acceptance-1", "classification": "MACHINE", "passed": True,
                          "actual_cli": True, "explicit_executable": bool(options.dw), "nodes": len(final["nodes"]),
                          "relationships": len(final["relationships"]), "history_cursor_survives_append": True,
                          "assertion_and_review_sources_distinct": True, "fr_en_json_equal": True,
                          "journal_and_index_unchanged_by_queries": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
