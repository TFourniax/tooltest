from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_events import append_project_events, continuity_paths, read_project_events


class ContinuityReverificationTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.check_call(["git", "init", "-q"], cwd=repo)
        subprocess.check_call(["git", "config", "user.email", "continuity@example.test"], cwd=repo)
        subprocess.check_call(["git", "config", "user.name", "Continuity Reverify"], cwd=repo)
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "app.py"], cwd=repo)
        subprocess.check_call(["git", "commit", "-qm", "base"], cwd=repo)
        return repo

    @staticmethod
    def _batch(*, cert: str, base_sha: str, candidate_sha: str, digest: str) -> list[dict]:
        change_id = "dwchg_1234567890abcdef12345678"
        provenance = {
            "producer": "diffwitness",
            "source": "change-envelope",
            "artifact_schema": "change-envelope-1",
            "artifact_digest": digest,
        }
        return [
            {
                "event_type": "change.observed",
                "subject": {"id": change_id, "kind": "change", "label": change_id},
                "epistemic_status": "OBSERVED",
                "payload": {
                    "repository_fingerprint": "dwrepo_same",
                    "base_tree": "tree-base",
                    "candidate_tree": "tree-candidate",
                    "base_sha": base_sha,
                    "candidate_sha": candidate_sha,
                    "changed_files": ["app.py"],
                },
                "relations": [],
                "provenance": provenance,
                "actor": {"kind": "unknown", "id": "unknown-change-actor"},
                "dedupe_key": "change:" + change_id,
            },
            {
                "event_type": "proof.completed",
                "subject": {"id": cert, "kind": "proof-certificate", "label": "causal"},
                "epistemic_status": "VERIFIED",
                "payload": {
                    "change_id": change_id,
                    "claim": "causal",
                    "accepted": True,
                    "certificate_schema": 2,
                    "authoritative_validation": True,
                },
                "relations": [],
                "provenance": {
                    **provenance,
                    "producer": "diffwitness-proof",
                    "authoritative_validation": True,
                    "imported_by": "diffwitness-ide-hook",
                },
                "actor": {"kind": "unknown", "id": "unknown-change-actor"},
                "dedupe_key": f"proof:{cert}:verified",
            },
            {
                "event_type": "debt.snapshot",
                "subject": {"id": change_id, "kind": "change", "label": change_id},
                "epistemic_status": "OBSERVED",
                "payload": {"change_id": change_id, "points": 0, "obligations": 0, "budget_passed": True},
                "relations": [],
                "provenance": {**provenance, "producer": "debt-ledger"},
                "actor": {"kind": "unknown", "id": "unknown-change-actor"},
                "dedupe_key": f"debt-snapshot:{change_id}:0::True",
            },
        ]

    def test_same_tree_change_accepts_new_certificate_despite_new_snapshot_shas(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            first = append_project_events(
                repo=repo,
                events=self._batch(
                    cert="dw2_first",
                    base_sha="ephemeral-base-one",
                    candidate_sha="ephemeral-candidate-one",
                    digest="sha256:first-envelope",
                ),
            )
            self.assertEqual([created for _, created in first], [True, True, True])

            second = append_project_events(
                repo=repo,
                events=self._batch(
                    cert="dw2_second",
                    base_sha="ephemeral-base-two",
                    candidate_sha="ephemeral-candidate-two",
                    digest="sha256:second-envelope",
                ),
            )
            self.assertEqual([created for _, created in second], [False, True, False])

            events = read_project_events(continuity_paths(repo).events)
            proofs = [event for event in events if event["event_type"] == "proof.completed"]
            self.assertEqual(len(events), 4)
            self.assertEqual([event["subject"]["id"] for event in proofs], ["dw2_first", "dw2_second"])
            self.assertTrue(all(event["epistemic_status"] == "VERIFIED" for event in proofs))


if __name__ == "__main__":
    unittest.main()
