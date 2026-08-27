from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_budget import evaluate_budget
from diffwitness.debt_scan import scan_change
from diffwitness.ledger import DebtLedger
from diffwitness.semantic_redundancy import RULE_ID, SemanticRedundancySensor


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init_repo(repo: Path, files: dict[str, str]) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "sensor@example.com", cwd=repo)
    git("config", "user.name", "Sensor Test", cwd=repo)
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


LEGACY = """\
def verify_session_token(raw_token, expected_secret):
    if not raw_token:
        return False
    pieces = raw_token.split(".")
    if len(pieces) != 3:
        return False
    payload = pieces[1]
    signature = pieces[2]
    if not payload or not signature:
        return False
    normalized = signature.strip().lower()
    expected = expected_secret.strip().lower()
    if normalized != expected:
        return False
    return True
"""

REIMPLEMENTED = """\
def check_access_credential(credential, configured_key):
    if not credential:
        return False
    segments = credential.split(".")
    if len(segments) != 3:
        return False
    body = segments[1]
    proof = segments[2]
    if not body or not proof:
        return False
    cleaned = proof.strip().lower()
    target = configured_key.strip().lower()
    if cleaned != target:
        return False
    return True
"""


class SemanticRedundancySensorTests(unittest.TestCase):
    def test_change_sensor_finds_renamed_reimplementation_without_exporting_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"legacy/auth.py": LEGACY})
            new = repo / "new" / "access.py"
            new.parent.mkdir(parents=True)
            new.write_text(REIMPLEMENTED, encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "agent adds parallel implementation", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            result = SemanticRedundancySensor().scan_change(
                repo=repo,
                base_sha=base,
                candidate_sha=candidate,
            )

            self.assertEqual(len(result.signals), 1)
            signal = result.signals[0]
            self.assertEqual(signal.rule_id, RULE_ID)
            self.assertEqual(signal.category, "redundancy")
            self.assertEqual(signal.measurement, "heuristic")
            self.assertEqual(signal.points, 0)
            self.assertFalse(signal.evidence["source_code_exported"])
            paths = {item["path"] for item in signal.evidence["locations"]}
            self.assertEqual(paths, {"legacy/auth.py", "new/access.py"})
            self.assertGreaterEqual(signal.evidence["similarity"], 0.88)

    def test_change_and_project_modes_keep_same_debt_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"legacy/auth.py": LEGACY})
            new = repo / "new" / "access.py"
            new.parent.mkdir(parents=True)
            new.write_text(REIMPLEMENTED, encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "parallel implementation", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            sensor = SemanticRedundancySensor()
            change = sensor.scan_change(repo=repo, base_sha=base, candidate_sha=candidate)
            project = sensor.scan_project(repo=repo, candidate_sha=candidate)

            self.assertEqual(len(change.signals), 1)
            self.assertEqual(len(project.signals), 1)
            self.assertEqual(change.signals[0].debt_id, project.signals[0].debt_id)

    def test_exact_source_copy_is_left_to_existing_deterministic_duplicate_rule(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"one.py": LEGACY})
            (repo / "two.py").write_text(LEGACY, encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "exact copy", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            result = SemanticRedundancySensor().scan_change(
                repo=repo,
                base_sha=base,
                candidate_sha=candidate,
            )
            self.assertEqual(result.signals, [])

    def test_accounting_boundary_enriches_report_but_zero_point_sensor_cannot_break_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"legacy/auth.py": LEGACY})
            new = repo / "new" / "access.py"
            new.parent.mkdir(parents=True)
            new.write_text(REIMPLEMENTED, encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "agent duplication", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            report = scan_change(repo=repo, base_sha=base, candidate_sha=candidate)
            before_points = report.total_points
            ledger = DebtLedger.load(repo / ".git" / "diffwitness" / "sensor-test-ledger.jsonl")
            budget = evaluate_budget(
                ledger=ledger,
                change=report,
                debt_config={"max_per_change": before_points},
            )

            semantic = [signal for signal in report.signals if signal.rule_id == RULE_ID]
            self.assertEqual(len(semantic), 1)
            self.assertEqual(semantic[0].points, 0)
            self.assertEqual(report.total_points, before_points)
            self.assertTrue(budget.passed)
            self.assertIn("semantic-redundancy-v1", report.metadata["debt_sensors"])

    def test_sensor_can_be_disabled_at_accounting_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"legacy/auth.py": LEGACY})
            new = repo / "new" / "access.py"
            new.parent.mkdir(parents=True)
            new.write_text(REIMPLEMENTED, encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "agent duplication", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            report = scan_change(repo=repo, base_sha=base, candidate_sha=candidate)
            ledger = DebtLedger.load(repo / ".git" / "diffwitness" / "sensor-disabled-ledger.jsonl")
            evaluate_budget(
                ledger=ledger,
                change=report,
                debt_config={"semantic_redundancy_scan": False},
            )
            self.assertFalse(any(signal.rule_id == RULE_ID for signal in report.signals))


if __name__ == "__main__":
    unittest.main()
