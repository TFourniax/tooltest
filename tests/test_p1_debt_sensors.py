from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtSignal
from diffwitness.debt_sensor import DebtSensorResult
from diffwitness.p1_sensors import (
    AGENT_EXPANSION_RULE_ID,
    PARALLEL_SOURCE_RULE_ID,
    SECURITY_POLICY_RULE_ID,
    AgentExpansionSensor,
    ParallelSourceOfTruthSensor,
    security_policy_from_semantic,
)


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init_repo(repo: Path, files: dict[str, str]) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "p1-sensors@example.invalid", cwd=repo)
    git("config", "user.name", "P1 Sensor Tests", cwd=repo)
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


class ParallelSourceOfTruthTests(unittest.TestCase):
    def test_new_second_domain_constant_is_observed_without_points(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"billing/plans.py": "FREE_LIMIT = 10\n"})
            (repo / "api").mkdir()
            (repo / "api/quota.py").write_text("DEFAULT_FREE_LIMIT = 10\n", encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "duplicate domain truth", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            result = ParallelSourceOfTruthSensor().scan_change(repo=repo, base_sha=base, candidate_sha=candidate)
            self.assertEqual(len(result.signals), 1)
            signal = result.signals[0]
            self.assertEqual(signal.rule_id, PARALLEL_SOURCE_RULE_ID)
            self.assertEqual(signal.category, "architecture")
            self.assertEqual(signal.measurement, "heuristic")
            self.assertEqual(signal.points, 0)
            self.assertEqual({item["path"] for item in signal.evidence["locations"]}, {"billing/plans.py", "api/quota.py"})
            self.assertFalse(signal.evidence["source_code_exported"])

    def test_unrelated_constants_are_not_grouped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"billing/plans.py": "FREE_LIMIT = 10\n"})
            (repo / "api.py").write_text("RETRY_ATTEMPTS = 10\n", encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "unrelated constant", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)
            result = ParallelSourceOfTruthSensor().scan_change(repo=repo, base_sha=base, candidate_sha=candidate)
            self.assertEqual(result.signals, [])


class SecurityPolicyDerivationTests(unittest.TestCase):
    def test_security_context_derives_distinct_zero_point_observation(self) -> None:
        semantic = DebtSignal(
            category="redundancy",
            rule_id="sensor.semantic-redundancy",
            title="Possible semantic reimplementation",
            severity="low",
            measurement="heuristic",
            anchor="pair-anchor",
            explanation="advisory",
            path="auth/access.py",
            line=4,
            points=0,
            evidence={"locations": [{"path": "auth/access.py", "name": "authorize_user"}, {"path": "security/policy.py", "name": "check_permission"}], "source_code_exported": False},
        )
        result = security_policy_from_semantic(DebtSensorResult(sensor_id="semantic-redundancy-v1", signals=[semantic]))
        self.assertEqual(len(result.signals), 1)
        signal = result.signals[0]
        self.assertEqual(signal.rule_id, SECURITY_POLICY_RULE_ID)
        self.assertEqual(signal.category, "security")
        self.assertEqual(signal.points, 0)
        self.assertEqual(signal.anchor, semantic.anchor)
        self.assertFalse(signal.evidence["source_code_exported"])


class AgentExpansionTests(unittest.TestCase):
    def test_large_multi_file_change_is_observed_but_not_charged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"app.py": "VALUE = 2\n"})
            for index in range(8):
                lines = [f"def helper_{index}_{n}():\n    return {n}\n" for n in range(18)]
                (repo / f"module_{index}.py").write_text("\n".join(lines), encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "broad generated expansion", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            result = AgentExpansionSensor().scan_change(repo=repo, base_sha=base, candidate_sha=candidate)
            self.assertEqual(len(result.signals), 1)
            signal = result.signals[0]
            self.assertEqual(signal.rule_id, AGENT_EXPANSION_RULE_ID)
            self.assertEqual(signal.category, "complexity")
            self.assertEqual(signal.points, 0)
            self.assertGreaterEqual(signal.evidence["changed_production_files"], 8)
            self.assertFalse(signal.evidence["source_code_exported"])


if __name__ == "__main__":
    unittest.main()
