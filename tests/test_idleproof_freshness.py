from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.gitops import git, snapshot_worktree
from diffwitness.idleproof_explanation import build_llm_context, load_current_explanation, write_explanation_artifact


class IdleProofFreshnessTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.check_call(["git", "init", "-q"], cwd=repo)
        subprocess.check_call(["git", "config", "user.email", "freshness@example.test"], cwd=repo)
        subprocess.check_call(["git", "config", "user.name", "Freshness Test"], cwd=repo)
        (repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "calculator.py"], cwd=repo)
        subprocess.check_call(["git", "commit", "-qm", "broken baseline"], cwd=repo)
        return repo

    def test_historical_accepted_proof_cannot_claim_drifted_worktree_is_verified(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            base = snapshot_worktree(repo)
            (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            candidate = snapshot_worktree(repo)
            candidate_tree = git(repo, "rev-parse", "--verify", f"{candidate}^{{tree}}").strip()
            envelope = {
                "schema_version": "change-envelope-1",
                "change_id": "dwchg_freshness1234567890abcd",
                "base": {"sha": base, "tree": git(repo, "rev-parse", "--verify", f"{base}^{{tree}}").strip()},
                "candidate": {"sha": candidate, "tree": candidate_tree},
                "proof": {
                    "certificate_id": "dw2_freshness",
                    "claim": "causal",
                    "accepted": True,
                    "certificate_schema": 2,
                },
            }
            envelope_path = repo / ".git" / "diffwitness" / "change-envelope.json"
            envelope_path.parent.mkdir(parents=True, exist_ok=True)
            import json
            envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
            write_explanation_artifact(repo=repo, envelope=envelope)

            current = load_current_explanation(repo)
            self.assertEqual(current["confidence"], "verified")
            self.assertEqual(current["coverage"]["freshness"], "current")
            self.assertTrue(current["coverage"]["current_worktree_covered"])

            (repo / "calculator.py").write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")
            stale = load_current_explanation(repo)
            self.assertEqual(stale["confidence"], "historical")
            self.assertEqual(stale["coverage"]["scope"], "historical")
            self.assertEqual(stale["coverage"]["freshness"], "stale")
            self.assertFalse(stale["coverage"]["current_worktree_covered"])
            self.assertTrue(stale["proof"]["accepted"])
            self.assertEqual(stale["proof"]["scope"], "historical")
            self.assertIn("NOT covered", stale["why_it_matters"][0])
            self.assertIn("Verify the current worktree", stale["verify_next"][0])

            context = build_llm_context(stale)
            facts = context["facts"]
            self.assertEqual(facts["confidence"], "historical")
            self.assertFalse(facts["coverage"]["current_worktree_covered"])
            self.assertIn("never describe a historical accepted Proof", context["role"])


if __name__ == "__main__":
    unittest.main()
