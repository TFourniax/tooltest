from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.attestation import expected_certificate_id
from diffwitness.change_envelope import ChangeEnvelopeError, build_change_envelope
from diffwitness.engine_protocol import change_id, repository_fingerprint
from diffwitness.gitops import git, snapshot_worktree


class ChangeEnvelopeTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "change-envelope@example.test")
        self.git(repo, "config", "user.name", "Change Envelope Test")
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git(repo, "add", "app.py")
        self.git(repo, "commit", "-qm", "base")
        return repo

    def _fixtures(self, repo: Path) -> tuple[Path, Path, Path, str]:
        base_sha = self.git(repo, "rev-parse", "HEAD")
        base_tree = self.git(repo, "rev-parse", "HEAD^{tree}")
        (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        (repo / ".idleproof").mkdir()
        (repo / ".idleproof" / "state.json").write_text("{}\n", encoding="utf-8")
        (repo / ".claude").mkdir()
        (repo / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")

        candidate_sha = snapshot_worktree(repo)
        candidate_tree = git(repo, "rev-parse", "--verify", f"{candidate_sha}^{{tree}}").strip()
        repository = repository_fingerprint(repo)
        cid = change_id(repository=repository, base_tree=base_tree, candidate_tree=candidate_tree)

        artifact_dir = repo / ".git" / "change-envelope-test"
        artifact_dir.mkdir(parents=True)
        proof_path = artifact_dir / "proof.json"
        proof = {
            "schema_version": "noop-1",
            "tool": "diffwitness",
            "certificate_id": "dw0_" + "0" * 20,
            "outcome": "proof-not-required",
            "base": {"ref": "HEAD", "sha": base_sha, "tree": base_tree},
            "candidate": {"ref": "WORKTREE", "sha": candidate_sha, "tree": candidate_tree},
            "changed_files": ["app.py"],
            "ignored": [],
            "summary": {
                "mutations": 0,
                "witnessed": 0,
                "unwitnessed": 0,
                "inconclusive": 0,
                "surplus_candidate_hunks": 0,
            },
        }
        proof["certificate_id"] = expected_certificate_id(proof)
        proof_path.write_text(json.dumps(proof), encoding="utf-8")

        debt_path = artifact_dir / "debt.json"
        debt_path.write_text(
            json.dumps(
                {
                    "report": {
                        "schema_version": "debt-report-1",
                        "scope": "change",
                        "base_sha": base_sha,
                        "candidate_sha": candidate_sha,
                        "candidate_tree": candidate_tree,
                        "summary": {"points": 3},
                        "signals": [{"debt_id": "DW-0123456789AB"}],
                    },
                    "budget": {"passed": True},
                    "ledger": {},
                }
            ),
            encoding="utf-8",
        )

        understanding_path = repo / ".idleproof" / "receipt.json"
        understanding_path.write_text(
            json.dumps(
                {
                    "schema": "idleproof.receipt.v1",
                    "session": {
                        "id": "session-123",
                        "source": "claude",
                        "change": {
                            "available": True,
                            "schema": "change-envelope-1",
                            "changeId": cid,
                            "repository": {"fingerprint": repository},
                            "base": {"sha": base_sha, "tree": base_tree, "dirty": False},
                            "candidate": {"sha": None, "tree": candidate_tree, "dirty": True},
                        },
                    },
                    "metrics": {"coverage": 78, "debt": 4, "featureCoverage": 81, "featureDebt": 2},
                }
            ),
            encoding="utf-8",
        )
        return proof_path, debt_path, understanding_path, cid

    def test_binds_proof_debt_and_idleproof_to_one_exact_change(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            proof, debt, understanding, expected_cid = self._fixtures(repo)
            envelope = build_change_envelope(
                repo=repo,
                base_ref="HEAD",
                candidate_ref="WORKTREE",
                proof_path=proof,
                debt_path=debt,
                understanding_path=understanding,
            )
            self.assertEqual(envelope["schema_version"], "change-envelope-1")
            self.assertEqual(envelope["change_id"], expected_cid)
            self.assertEqual(envelope["proof"]["claim"], "not-required")
            self.assertTrue(envelope["proof"]["accepted"])
            self.assertEqual(envelope["debt"]["points"], 3)
            self.assertEqual(envelope["debt"]["open_lineages"], ["DW-0123456789AB"])
            self.assertTrue(envelope["debt"]["budget_passed"])
            self.assertEqual(envelope["understanding"]["coverage"], 78)
            self.assertEqual(envelope["understanding"]["knowledge_debt"], 4)
            self.assertTrue(envelope["understanding"]["receipt_digest"].startswith("sha256:"))
            self.assertFalse(envelope["privacy"]["code_uploaded"])
            self.assertFalse(envelope["privacy"]["contains_prompt_text"])

    def test_idleproof_state_and_local_hook_files_do_not_change_diffwitness_worktree_identity(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            head_tree = self.git(repo, "rev-parse", "HEAD^{tree}")
            (repo / ".idleproof").mkdir()
            (repo / ".idleproof" / "receipt.json").write_text("{}\n", encoding="utf-8")
            (repo / ".codex").mkdir()
            (repo / ".codex" / "hooks.json").write_text("{}\n", encoding="utf-8")
            snapshot = snapshot_worktree(repo)
            self.assertEqual(self.git(repo, "rev-parse", f"{snapshot}^{{tree}}"), head_tree)

    def test_mismatched_idleproof_change_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            _, _, understanding, _ = self._fixtures(repo)
            receipt = json.loads(understanding.read_text(encoding="utf-8"))
            receipt["session"]["change"]["changeId"] = "dwchg_deadbeefdeadbeefdeadbeef"
            understanding.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ChangeEnvelopeError, "change_id does not match"):
                build_change_envelope(
                    repo=repo,
                    base_ref="HEAD",
                    candidate_ref="WORKTREE",
                    understanding_path=understanding,
                )

    def test_mismatched_debt_candidate_tree_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            _, debt, _, _ = self._fixtures(repo)
            payload = json.loads(debt.read_text(encoding="utf-8"))
            payload["report"]["candidate_tree"] = "0" * 40
            debt.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ChangeEnvelopeError, "candidate tree does not match"):
                build_change_envelope(
                    repo=repo,
                    base_ref="HEAD",
                    candidate_ref="WORKTREE",
                    debt_path=debt,
                )

    def test_corrupt_evidence_and_empty_envelope_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            broken = repo / ".git" / "broken.json"
            broken.write_text('{"broken":', encoding="utf-8")
            with self.assertRaisesRegex(ChangeEnvelopeError, "not valid UTF-8 JSON"):
                build_change_envelope(
                    repo=repo,
                    base_ref="HEAD",
                    candidate_ref="WORKTREE",
                    proof_path=broken,
                )
            with self.assertRaisesRegex(ChangeEnvelopeError, "at least one"):
                build_change_envelope(repo=repo, base_ref="HEAD", candidate_ref="WORKTREE")


if __name__ == "__main__":
    unittest.main()
