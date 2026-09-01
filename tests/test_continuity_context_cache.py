from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_context import compile_context
from diffwitness.continuity_events import ContinuityError, append_project_event, continuity_paths


class ContinuityContextCacheTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "context-cache@example.test")
        self.git(repo, "config", "user.name", "Context Cache Test")
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        return repo

    def add_objective(self, repo: Path, identity: str, label: str) -> None:
        append_project_event(
            repo=repo,
            event_type="objective.declared",
            subject={"id": identity, "kind": "objective", "label": label},
            epistemic_status="DECLARED",
            payload={"priority": "high"},
            provenance={"producer": "test", "source": "unit"},
            actor={"kind": "human", "id": "test"},
            dedupe_key="objective:" + identity,
        )

    def test_hot_cache_detects_historical_tampering_before_serving_context(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.add_objective(repo, "OBJ-FIRST", "Support safe refunds")
            self.add_objective(repo, "OBJ-SECOND", "Keep payments idempotent")
            first = compile_context(repo, "safe refunds", refresh_structure=True)
            self.assertIn("OBJ-FIRST", {item["id"] for item in first["objectives"]})

            events_path = continuity_paths(repo).events
            lines = events_path.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(lines[0])
            tampered["payload"]["priority"] = "critical"
            lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            # The last event text/hash is unchanged. Detection therefore proves that the hot path is
            # anchored to the full-file SHA-256, not merely the journal tail.
            with self.assertRaises(ContinuityError):
                compile_context(repo, "safe refunds", refresh_structure=True)

    def test_legitimate_append_invalidates_cache_and_rebuilds_strictly(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            self.add_objective(repo, "OBJ-ONE", "Support refunds")
            first = compile_context(repo, "refunds", refresh_structure=True)
            self.assertIn("OBJ-ONE", {item["id"] for item in first["objectives"]})

            self.add_objective(repo, "OBJ-TWO", "Preserve refund idempotency")
            second = compile_context(repo, "refund idempotency", refresh_structure=True)
            self.assertIn("OBJ-TWO", {item["id"] for item in second["objectives"]})
            self.assertNotEqual(first["state"]["eventHead"], second["state"]["eventHead"])


if __name__ == "__main__":
    unittest.main()
