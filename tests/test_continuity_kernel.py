from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_bridge import record_change_envelope
from diffwitness.continuity_cli import decision_cli, failed_approach_cli, invariant_cli, objective_cli
from diffwitness.continuity_context import compile_context
from diffwitness.continuity_events import ContinuityError, append_project_event, continuity_paths, read_project_events
from diffwitness.continuity_state import STATE_SCHEMA, ensure_state, rebuild_state, state_status
from diffwitness.engine_protocol import change_id, repository_fingerprint
from diffwitness.structure_provider import component_id_for_path


class ContinuityKernelTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "continuity@example.test")
        self.git(repo, "config", "user.name", "Continuity Test")
        (repo / "payments").mkdir()
        (repo / "payments" / "refund.py").write_text(
            "from . import rules\n\ndef normalize(amount):\n    return max(0, amount)\n\ndef refund(amount):\n    return normalize(amount)\n",
            encoding="utf-8",
        )
        (repo / "payments" / "rules.py").write_text("MAX_REFUND = 100\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        return repo

    def envelope(self, repo: Path) -> tuple[dict, str]:
        base_sha = self.git(repo, "rev-parse", "HEAD")
        base_tree = self.git(repo, "rev-parse", "HEAD^{tree}")
        changed = repo / "payments" / "refund path.py"
        changed.write_text("def partial_refund(amount):\n    return amount\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "partial refund")
        candidate_sha = self.git(repo, "rev-parse", "HEAD")
        candidate_tree = self.git(repo, "rev-parse", "HEAD^{tree}")
        repository = repository_fingerprint(repo)
        cid = change_id(repository=repository, base_tree=base_tree, candidate_tree=candidate_tree)
        envelope = {
            "schema_version": "change-envelope-1",
            "change_id": cid,
            "repository": {"fingerprint": repository, "vcs": "git"},
            "base": {"sha": base_sha, "tree": base_tree, "dirty": False},
            "candidate": {"sha": candidate_sha, "tree": candidate_tree, "dirty": False},
            "privacy": {"code_uploaded": False, "contains_paths": False, "contains_prompt_text": False},
            "proof": {
                "tool": "diffwitness",
                "certificate_id": "dw2_0123456789abcdef01234567",
                "claim": "causal",
                "accepted": True,
                "certificate_schema": 2,
            },
            "debt": {
                "report_schema": "debt-report-1",
                "points": 7,
                "open_lineages": ["DW-0123456789AB"],
                "budget_passed": True,
            },
            "understanding": {
                "tool": "idleproof",
                "receipt_schema": "idleproof.receipt.v1",
                "receipt_digest": "sha256:" + "1" * 64,
                "coverage": 82,
                "knowledge_debt": 3,
                "feature_coverage": 75,
                "feature_debt": 2,
            },
        }
        return envelope, cid

    def test_project_event_log_is_hash_chained_and_tamper_evident(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            for number in range(2):
                append_project_event(
                    repo=repo,
                    event_type="objective.declared",
                    subject={"id": f"OBJ-{number}", "kind": "objective", "label": f"Objective {number}"},
                    epistemic_status="DECLARED",
                    payload={"priority": "normal"},
                    actor={"kind": "human", "id": "test"},
                    provenance={"producer": "test", "source": "unit"},
                )
            path = continuity_paths(repo).events
            events = read_project_events(path)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[1]["prev_hash"], events[0]["event_hash"])
            lines = path.read_text(encoding="utf-8").splitlines()
            value = json.loads(lines[0])
            value["payload"]["priority"] = "critical"
            lines[0] = json.dumps(value, sort_keys=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ContinuityError):
                read_project_events(path)

    def test_state_db_is_disposable_and_rebuilt_from_events(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            append_project_event(
                repo=repo,
                event_type="decision.recorded",
                subject={"id": "DEC-KEEP-IDEMPOTENCY", "kind": "decision", "label": "Keep refunds idempotent"},
                epistemic_status="DECLARED",
                payload={"why": "retries happen"},
                actor={"kind": "human", "id": "test"},
                provenance={"producer": "test", "source": "unit"},
            )
            state = rebuild_state(repo, include_structure=True)
            conn = sqlite3.connect(state)
            try:
                self.assertEqual(conn.execute("select count(*) from entities").fetchone()[0], 1)
                self.assertGreater(conn.execute("select count(*) from structure_components").fetchone()[0], 0)
            finally:
                conn.close()
            state.write_bytes(b"not a sqlite database")
            repaired = ensure_state(repo, include_structure=True)
            conn = sqlite3.connect(repaired)
            try:
                self.assertEqual(conn.execute("select count(*) from entities").fetchone()[0], 1)
                self.assertEqual(conn.execute("select value from meta where key='schema'").fetchone()[0], STATE_SCHEMA)
            finally:
                conn.close()

    def test_python_structure_separates_observed_from_inferred(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            state = rebuild_state(repo, include_structure=True)
            conn = sqlite3.connect(state)
            try:
                observed = conn.execute("select count(*) from structure_edges where predicate='imports' and epistemic_status='OBSERVED'").fetchone()[0]
                inferred = conn.execute("select count(*) from structure_edges where predicate='calls-name' and epistemic_status='INFERRED'").fetchone()[0]
                wrong = conn.execute("select count(*) from structure_edges where predicate='calls-name' and epistemic_status='VERIFIED'").fetchone()[0]
            finally:
                conn.close()
            self.assertGreaterEqual(observed, 1)
            self.assertGreaterEqual(inferred, 1)
            self.assertEqual(wrong, 0)

    def test_manual_envelope_cannot_self_promote_proof_to_verified(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            envelope, cid = self.envelope(repo)
            first = record_change_envelope(repo=repo, envelope=envelope, actor="human-import", trusted_proof=False)
            self.assertEqual(first["change_id"], cid)
            events = read_project_events(continuity_paths(repo).events)
            proof_events = [event for event in events if event["event_type"] == "proof.completed"]
            self.assertEqual(len(proof_events), 1)
            self.assertEqual(proof_events[0]["epistemic_status"], "OBSERVED")
            file_targets = [relation["target"] for event in events for relation in event.get("relations", []) if relation["target"].get("kind") == "file"]
            self.assertTrue(any(target.get("label") == "payments/refund path.py" for target in file_targets))
            self.assertTrue(all(" " not in target["id"] for target in file_targets))

            second = record_change_envelope(repo=repo, envelope=envelope, actor="diffwitness-guard", trusted_proof=True)
            self.assertEqual(second["created"]["proof"], 1)
            third = record_change_envelope(repo=repo, envelope=envelope, actor="diffwitness-guard", trusted_proof=True)
            self.assertEqual(sum(third["created"].values()), 0)
            state = ensure_state(repo)
            conn = sqlite3.connect(state)
            try:
                row = conn.execute("select epistemic_status,accepted,change_id from proofs where certificate_id=?", (envelope["proof"]["certificate_id"],)).fetchone()
            finally:
                conn.close()
            self.assertEqual(row, ("VERIFIED", 1, cid))

    def test_context_compiler_joins_human_memory_structure_and_change_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            objective_cli(["add", "Support partial refunds safely", "--repo", str(repo), "--id", "OBJ-REFUNDS", "--priority", "high", "--component", "payments/refund.py"])
            decision_cli(["record", "Keep refund operations idempotent", "--repo", str(repo), "--id", "DEC-IDEMPOTENCY", "--why", "payment retries are normal", "--objective", "OBJ-REFUNDS", "--component", "payments/refund.py"])
            invariant_cli(["add", "Refund total must never exceed captured payment", "--repo", str(repo), "--id", "INV-CAPTURE-LIMIT", "--critical", "--objective", "OBJ-REFUNDS", "--component", "payments/refund.py"])
            failed_approach_cli(["record", "Mutating charge rows directly", "--repo", str(repo), "--id", "FAIL-DIRECT-CHARGE", "--reason", "retries duplicated side effects", "--decision", "DEC-IDEMPOTENCY", "--component", "payments/refund.py"])
            envelope, cid = self.envelope(repo)
            record_change_envelope(repo=repo, envelope=envelope, actor="diffwitness-guard", trusted_proof=True)
            context = compile_context(repo, "implement partial refunds in payments", max_items=20, refresh_structure=True)
            self.assertEqual(context["schema_version"], "continuity-context-1")
            self.assertRegex(context["context_id"], r"^dwctx_[a-f0-9]{24}$")
            self.assertEqual(context["project"]["fingerprint"], repository_fingerprint(repo))
            self.assertNotIn("root", context["project"])
            self.assertIn("OBJ-REFUNDS", {item["id"] for item in context["objectives"]})
            self.assertIn("DEC-IDEMPOTENCY", {item["id"] for item in context["decisions"]})
            self.assertIn("INV-CAPTURE-LIMIT", {item["id"] for item in context["invariants"]})
            failed = next(item for item in context["failedApproaches"] if item["id"] == "FAIL-DIRECT-CHARGE")
            self.assertGreaterEqual(failed.get("relationDepth", 99), 1)
            self.assertIn("payments/refund.py", {item["path"] for item in context["components"]})
            self.assertIn("DW-0123456789AB", {item["debt_id"] for item in context["knownDebt"]})
            change = next(item for item in context["recentRelatedChanges"] if item["changeId"] == cid)
            self.assertEqual(change["proof"]["epistemicStatus"], "VERIFIED")
            self.assertTrue(any(item["kind"] == "invariant" for item in context["requiredEvidence"]))
            again = compile_context(repo, "implement partial refunds in payments", max_items=20, refresh_structure=True)
            self.assertEqual(again["context_id"], context["context_id"])

    def test_component_identity_is_provider_neutral_and_path_safe(self):
        self.assertEqual(component_id_for_path("payments/refund.py"), component_id_for_path("./payments\\refund.py"))
        self.assertRegex(component_id_for_path("a folder/file.py"), r"^dwcomp_[a-f0-9]{24}$")

    def test_event_and_state_do_not_store_raw_diff_or_prompt_fields(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            envelope, _ = self.envelope(repo)
            record_change_envelope(repo=repo, envelope=envelope, actor="diffwitness-guard", trusted_proof=True)
            raw = continuity_paths(repo).events.read_text(encoding="utf-8")
            self.assertNotIn("raw_prompt", raw)
            self.assertNotIn("raw_diff", raw)
            self.assertNotIn("partial_refund(amount)", raw)
            status = state_status(repo)
            self.assertEqual(status["event_count"], len(read_project_events(continuity_paths(repo).events)))


if __name__ == "__main__":
    unittest.main()
