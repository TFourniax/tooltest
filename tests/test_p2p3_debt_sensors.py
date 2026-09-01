from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtSignal
from diffwitness.debt_sensor import DebtSensorResult
from diffwitness.p2p3_sensors import (
    DEPENDENCY_SPRAW_RULE_ID,
    LAYER_BYPASS_RULE_ID,
    ORPHAN_CODE_RULE_ID,
    PARALLEL_ABSTRACTION_RULE_ID,
    DependencySprawlSensor,
    architecture_change_results,
    build_graph_context,
    parallel_abstraction_from_semantic,
)


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
    git("config", "user.email", "p2p3-sensors@example.invalid", cwd=repo)
    git("config", "user.name", "P2P3 Sensor Tests", cwd=repo)
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


class LayerBypassTests(unittest.TestCase):
    def test_existing_presentation_file_adds_direct_persistence_edge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(
                repo,
                {
                    "src/routes/profile.py": (
                        "from services.profile import load_profile\n\n"
                        "def profile(user_id):\n"
                        "    return load_profile(user_id)\n"
                    ),
                    "src/services/profile.py": (
                        "from db.users import fetch_user\n\n"
                        "def load_profile(user_id):\n"
                        "    return fetch_user(user_id)\n"
                    ),
                    "src/db/users.py": (
                        "def fetch_user(user_id):\n"
                        "    return {'id': user_id}\n\n"
                        "def save_user(user_id):\n"
                        "    return user_id\n"
                    ),
                },
            )
            route = repo / "src/routes/profile.py"
            route.write_text(
                "from services.profile import load_profile\n"
                "from db.users import save_user\n\n"
                "def profile(user_id):\n"
                "    save_user(user_id)\n"
                "    return load_profile(user_id)\n",
                encoding="utf-8",
            )
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "route bypasses service", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            context = build_graph_context(repo, base_sha=base, candidate_sha=candidate)
            layer, orphan = architecture_change_results(context, candidate_sha=candidate)
            self.assertEqual(len(layer.signals), 1)
            self.assertEqual(layer.signals[0].rule_id, LAYER_BYPASS_RULE_ID)
            self.assertEqual(layer.signals[0].points, 0)
            self.assertFalse(layer.signals[0].evidence["source_code_exported"])
            self.assertEqual(orphan.signals, [])

    def test_direct_persistence_edge_without_historical_mediator_is_not_called_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(
                repo,
                {
                    "src/routes/profile.py": "def profile(user_id):\n    return user_id\n",
                    "src/db/users.py": "def save_user(user_id):\n    return user_id\n",
                },
            )
            (repo / "src/routes/profile.py").write_text(
                "from db.users import save_user\n\n"
                "def profile(user_id):\n"
                "    return save_user(user_id)\n",
                encoding="utf-8",
            )
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "direct data access", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            context = build_graph_context(repo, base_sha=base, candidate_sha=candidate)
            layer, _ = architecture_change_results(context, candidate_sha=candidate)
            self.assertEqual(layer.signals, [])


class OrphanCodeTests(unittest.TestCase):
    def test_unchanged_service_loses_its_last_static_import_after_rewire(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(
                repo,
                {
                    "src/routes/checkout.py": (
                        "from services.legacy_checkout import checkout\n\n"
                        "def run(order):\n"
                        "    return checkout(order)\n"
                    ),
                    "src/services/legacy_checkout.py": (
                        "def checkout(order):\n"
                        "    return {'legacy': order}\n"
                    ),
                    "src/services/checkout.py": (
                        "def checkout(order):\n"
                        "    return {'current': order}\n"
                    ),
                },
            )
            (repo / "src/routes/checkout.py").write_text(
                "from services.checkout import checkout\n\n"
                "def run(order):\n"
                "    return checkout(order)\n",
                encoding="utf-8",
            )
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "rewire checkout service", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            context = build_graph_context(repo, base_sha=base, candidate_sha=candidate)
            _, orphan = architecture_change_results(context, candidate_sha=candidate)
            self.assertEqual(len(orphan.signals), 1)
            signal = orphan.signals[0]
            self.assertEqual(signal.rule_id, ORPHAN_CODE_RULE_ID)
            self.assertEqual(signal.path, "src/services/legacy_checkout.py")
            self.assertEqual(signal.points, 0)
            self.assertTrue(signal.evidence["static_import_graph_only"])


class ParallelAbstractionTests(unittest.TestCase):
    def test_high_confidence_semantic_pair_with_abstraction_roles_is_reclassified(self) -> None:
        semantic = DebtSignal(
            category="redundancy",
            rule_id="sensor.semantic-redundancy",
            title="Possible semantic reimplementation",
            severity="medium",
            measurement="heuristic",
            anchor="same-role-pair",
            explanation="advisory",
            path="billing/payment_service.py",
            line=10,
            points=0,
            evidence={
                "similarity": 0.96,
                "locations": [
                    {"path": "billing/payment_service.py", "name": "process_charge"},
                    {"path": "billing/billing_manager.py", "name": "process_payment"},
                ],
                "source_code_exported": False,
            },
        )
        result = parallel_abstraction_from_semantic(
            DebtSensorResult(sensor_id="semantic-redundancy-v1", signals=[semantic])
        )
        self.assertEqual(len(result.signals), 1)
        signal = result.signals[0]
        self.assertEqual(signal.rule_id, PARALLEL_ABSTRACTION_RULE_ID)
        self.assertEqual(signal.category, "architecture")
        self.assertEqual(signal.points, 0)
        self.assertEqual(signal.anchor, semantic.anchor)
        self.assertFalse(signal.evidence["source_code_exported"])

    def test_plain_helper_pair_is_not_promoted_to_architecture(self) -> None:
        semantic = DebtSignal(
            category="redundancy",
            rule_id="sensor.semantic-redundancy",
            title="Possible semantic reimplementation",
            severity="medium",
            measurement="heuristic",
            anchor="helper-pair",
            explanation="advisory",
            path="utils/format.py",
            points=0,
            evidence={
                "similarity": 0.97,
                "locations": [
                    {"path": "utils/format.py", "name": "format_name"},
                    {"path": "utils/text.py", "name": "normalize_name"},
                ],
            },
        )
        result = parallel_abstraction_from_semantic(
            DebtSensorResult(sensor_id="semantic-redundancy-v1", signals=[semantic])
        )
        self.assertEqual(result.signals, [])


class DependencySprawlTests(unittest.TestCase):
    def test_new_second_http_client_in_same_package_scope_is_observed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(
                repo,
                {
                    "package.json": (
                        '{\n'
                        '  "dependencies": {"axios": "1.0.0"}\n'
                        '}\n'
                    )
                },
            )
            (repo / "package.json").write_text(
                '{\n'
                '  "dependencies": {"axios": "1.0.0", "got": "14.0.0"}\n'
                '}\n',
                encoding="utf-8",
            )
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "add second http client", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            result = DependencySprawlSensor().scan_change(
                repo=repo,
                base_sha=base,
                candidate_sha=candidate,
            )
            self.assertEqual(len(result.signals), 1)
            signal = result.signals[0]
            self.assertEqual(signal.rule_id, DEPENDENCY_SPRAW_RULE_ID)
            self.assertEqual(signal.category, "dependency")
            self.assertEqual(signal.points, 0)
            self.assertEqual(signal.evidence["added_packages"], ["got"])
            self.assertEqual(signal.evidence["packages"], ["axios", "got"])

    def test_unrelated_new_dependency_does_not_trigger_family_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(
                repo,
                {"package.json": '{"dependencies":{"axios":"1.0.0"}}\n'},
            )
            (repo / "package.json").write_text(
                '{"dependencies":{"axios":"1.0.0","uuid":"11.0.0"}}\n',
                encoding="utf-8",
            )
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "add unrelated dependency", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)
            result = DependencySprawlSensor().scan_change(
                repo=repo,
                base_sha=base,
                candidate_sha=candidate,
            )
            self.assertEqual(result.signals, [])


if __name__ == "__main__":
    unittest.main()
