from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtReport, DebtSignal
from diffwitness.ledger import DebtLedger, LedgerError, _event_hash


class LedgerTests(unittest.TestCase):
    def signal(self, anchor="a", verification=None):
        return DebtSignal(
            category="evidence",
            rule_id="r",
            title="Debt",
            severity="medium",
            measurement="causal",
            anchor=anchor,
            explanation="why",
            path="app.py",
            verification=verification or {"type": "rerun-proof"},
        )

    def test_event_sourced_lifecycle_and_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            ledger = DebtLedger.load(path)
            signal = self.signal()
            ledger.record_report(DebtReport(scope="change", signals=[signal]))
            self.assertTrue(ledger.items()[signal.debt_id].active)
            ledger.resolve(signal.debt_id, reason="verified", verification={"result": "pass"})
            self.assertFalse(ledger.items()[signal.debt_id].active)
            ledger.record_report(DebtReport(scope="change", signals=[signal]))
            reopened = ledger.items()[signal.debt_id]
            self.assertTrue(reopened.active)
            self.assertEqual(reopened.reopen_count, 1)

    def test_tampering_breaks_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            ledger = DebtLedger.load(path)
            ledger.record_report(DebtReport(scope="change", signals=[self.signal()]))
            value = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            value["payload"]["signal"]["points"] = 99
            path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                DebtLedger.load(path)

    def test_stale_instances_append_without_losing_events(self):
        """Two agents that loaded the same ledger must not overwrite each other."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            first = DebtLedger.load(path)
            second = DebtLedger.load(path)
            signal_a = self.signal(anchor="agent-a")
            signal_b = self.signal(anchor="agent-b")

            first.record_report(DebtReport(scope="change", signals=[signal_a]))
            second.record_report(DebtReport(scope="change", signals=[signal_b]))

            reloaded = DebtLedger.load(path)
            self.assertEqual(len(reloaded.events), 2)
            self.assertEqual(set(reloaded.items()), {signal_a.debt_id, signal_b.debt_id})
            self.assertEqual(second.last_hash, reloaded.last_hash)

    def test_stale_instances_do_not_double_introduce_same_debt(self):
        """The state decision and append must share the same lock, not only the disk write."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            first = DebtLedger.load(path)
            second = DebtLedger.load(path)
            signal = self.signal(anchor="same-lineage")
            report = DebtReport(scope="change", signals=[signal])

            self.assertEqual(first.record_report(report)["introduced"], 1)
            stats = second.record_report(report)

            self.assertEqual(stats, {"introduced": 0, "reopened": 0, "refreshed": 0})
            reloaded = DebtLedger.load(path)
            self.assertEqual(len(reloaded.events), 1)
            self.assertEqual(list(reloaded.items()), [signal.debt_id])

    def test_stale_accept_cannot_accept_debt_resolved_by_another_process(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            live = DebtLedger.load(path)
            signal = self.signal(anchor="resolve-race")
            live.record_report(DebtReport(scope="change", signals=[signal]))
            stale = DebtLedger.load(path)

            live.resolve(signal.debt_id, reason="verified", verification={"result": "pass"})
            with self.assertRaisesRegex(LedgerError, "cannot accept non-open debt"):
                stale.accept(signal.debt_id, reason="temporary exception")

            reloaded = DebtLedger.load(path)
            self.assertFalse(reloaded.items()[signal.debt_id].active)
            self.assertEqual(len(reloaded.events), 2)

    def test_stale_persist_cannot_overwrite_newer_history(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            stale = DebtLedger.load(path)
            live = DebtLedger.load(path)
            live.record_report(DebtReport(scope="change", signals=[self.signal(anchor="new")]))
            with self.assertRaisesRegex(LedgerError, "concurrently"):
                stale._persist()
            self.assertEqual(len(DebtLedger.load(path).events), 1)

    def test_semantic_identity_mismatch_fails_closed_on_load(self):
        """A hash-valid imported event cannot relabel a signal under another DW id."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            ledger = DebtLedger.load(path)
            signal = self.signal(anchor="identity")
            ledger.record_report(DebtReport(scope="change", signals=[signal]))
            event = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            event["debt_id"] = "DW-000000000000"
            event["event_hash"] = _event_hash(event)
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(LedgerError, "identity mismatch"):
                DebtLedger.load(path)

    def test_hash_valid_but_invalid_transition_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            ledger = DebtLedger.load(path)
            signal = self.signal(anchor="transition")
            ledger.record_report(DebtReport(scope="change", signals=[signal]))
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            duplicate = dict(events[0])
            duplicate["prev_hash"] = events[0]["event_hash"]
            duplicate["timestamp"] = "2026-08-20T00:00:01+00:00"
            duplicate["event_hash"] = _event_hash(duplicate)
            path.write_text(
                "".join(json.dumps(event) + "\n" for event in [events[0], duplicate]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(LedgerError, "invalid introduced transition"):
                DebtLedger.load(path)

    def test_unknown_event_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = DebtLedger.load(Path(td) / "ledger.jsonl")
            with self.assertRaisesRegex(LedgerError, "unknown debt ledger event type"):
                ledger.append(event_type="rewritten", debt_id="DW-X", payload={})

    def test_project_reconciliation_only_closes_project_rules(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = DebtLedger.load(Path(td) / "ledger.jsonl")
            project = self.signal(anchor="project", verification={"type": "project-rule"})
            causal = self.signal(anchor="causal", verification={"type": "mutation-necessity"})
            ledger.record_report(DebtReport(scope="project", signals=[project, causal]))
            ledger.reconcile_project_report(DebtReport(scope="project", signals=[]))
            state = ledger.items()
            self.assertFalse(state[project.debt_id].active)
            self.assertTrue(state[causal.debt_id].active)


if __name__ == "__main__":
    unittest.main()
