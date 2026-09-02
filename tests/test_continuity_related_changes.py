from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_context_enriched import compile_context
from diffwitness.continuity_events import append_project_events


class ContinuityRelatedChangeTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.check_call(["git", "init", "-q"], cwd=repo)
        subprocess.check_call(["git", "config", "user.email", "related@example.test"], cwd=repo)
        subprocess.check_call(["git", "config", "user.name", "Related Change Test"], cwd=repo)
        (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "calculator.py"], cwd=repo)
        subprocess.check_call(["git", "commit", "-qm", "verified calculator fix"], cwd=repo)
        return repo

    @staticmethod
    def _events() -> list[dict]:
        change_id = "dwchg_related1234567890abcdef"
        provenance = {
            "producer": "diffwitness",
            "source": "change-envelope",
            "artifact_schema": "change-envelope-1",
            "artifact_digest": "sha256:related-change",
        }
        return [
            {
                "event_type": "change.observed",
                "subject": {"id": change_id, "kind": "change", "label": change_id},
                "epistemic_status": "OBSERVED",
                "payload": {
                    "repository_fingerprint": "dwrepo_related",
                    "base_tree": "tree-before",
                    "candidate_tree": "tree-after",
                    "base_sha": "base",
                    "candidate_sha": "candidate",
                    "changed_files": ["calculator.py"],
                },
                "relations": [],
                "provenance": provenance,
                "actor": {"kind": "unknown", "id": "unknown-change-actor"},
                "dedupe_key": f"change:{change_id}",
            },
            {
                "event_type": "proof.completed",
                "subject": {"id": "dw2_related", "kind": "proof-certificate", "label": "causal"},
                "epistemic_status": "VERIFIED",
                "payload": {
                    "change_id": change_id,
                    "claim": "causal",
                    "accepted": True,
                    "certificate_schema": 2,
                    "authoritative_validation": True,
                },
                "relations": [],
                "provenance": {**provenance, "producer": "diffwitness-proof", "authoritative_validation": True},
                "actor": {"kind": "unknown", "id": "unknown-change-actor"},
                "dedupe_key": "proof:dw2_related:verified",
            },
        ]

    def test_human_calcul_query_recovers_verified_calculator_change(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            append_project_events(repo=repo, events=self._events())

            context = compile_context(
                repo,
                "Corriger le bug de calcul qui faisait échouer le test",
                max_items=10,
                refresh_structure=False,
            )
            changes = context.get("recentRelatedChanges") or []
            self.assertTrue(changes, "the human-equivalent query must recover the recorded calculator change")
            first = changes[0]
            self.assertEqual(first["changeId"], "dwchg_related1234567890abcdef")
            self.assertEqual(first["files"], ["calculator.py"])
            self.assertTrue(first["proof"]["accepted"])
            self.assertEqual(first["proof"]["epistemicStatus"], "VERIFIED")
            self.assertEqual(first.get("relevanceBasis"), "bounded-file-name-overlap")

    def test_unrelated_query_does_not_return_recent_change_just_because_it_is_recent(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            append_project_events(repo=repo, events=self._events())

            context = compile_context(
                repo,
                "Mettre à jour la licence et la documentation de déploiement",
                max_items=10,
                refresh_structure=False,
            )
            self.assertEqual(context.get("recentRelatedChanges") or [], [])


if __name__ == "__main__":
    unittest.main()
