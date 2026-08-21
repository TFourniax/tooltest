from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from diffwitness.engine_protocol import (
    EngineProtocolError,
    build_engine_request,
    change_id,
    repository_fingerprint,
    request_digest,
    run_advisory_engine,
    validate_engine_plan,
)
from diffwitness.models import Mutation


ROOT = Path(__file__).resolve().parents[1]
COMPAT_REQUEST_DIGEST = "f0ec375a81df52cdcdac55856201b559e8c1e6a29b74a4b96cfb0d0a9e3ca320"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=True
    ).stdout.strip()


def make_repo(root: Path) -> tuple[Path, str, str, str, str]:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "DiffWitness Test")
    git(repo, "config", "user.email", "test@localhost")
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    git(repo, "add", "app.py")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    git(repo, "add", "app.py")
    git(repo, "commit", "-qm", "candidate")
    candidate = git(repo, "rev-parse", "HEAD")
    candidate_tree = git(repo, "rev-parse", "HEAD^{tree}")
    return repo, base, candidate, base_tree, candidate_tree


def mutations() -> list[Mutation]:
    return [
        Mutation("m1", "app.py", "app.py hunk 1", "patch-1", "hunk", 1, 1, 1, 2),
        Mutation("m2", "auth/session.py", "auth hunk", "patch-2", "hunk", 2, 0, 10, 12),
        Mutation("m3", "docs_like.py", "cleanup", "patch-3", "hunk", 1, 1, 20, 21),
    ]


class EngineProtocolTests(unittest.TestCase):
    def _request(self, repo: Path, base: str, candidate: str, base_tree: str, candidate_tree: str):
        return build_engine_request(
            repo=repo,
            base_sha=base,
            base_tree=base_tree,
            candidate_sha=candidate,
            candidate_tree=candidate_tree,
            mutations=mutations(),
            max_experiments=40,
            max_total_seconds=900,
            stability_runs=2,
            policy="balanced",
            strategy="adaptive",
            test_command="python -m unittest",
            changed_test_files=["tests/test_app.py"],
        )

    def test_canonical_compat_vector_has_frozen_request_id_and_digest(self):
        request = json.loads((ROOT / "compat" / "engine-request-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(request["request_id"], "dwerq_9f199984b5c39adba0e39b87")
        self.assertEqual(request["change_id"], "dwchg_599cbaed708663721c128c78")
        self.assertEqual(request_digest(request), COMPAT_REQUEST_DIGEST)
        plan = {
            "schema_version": "engine-plan-1",
            "request_id": request["request_id"],
            "request_digest": COMPAT_REQUEST_DIGEST,
            "engine": {"name": "compat-vector", "version": "1"},
            "ordered_mutation_ids": ["m_extra", "m_core"],
            "partitions": [["m_extra"], ["m_core"]],
            "interaction_pairs": [["m_core", "m_extra"]],
        }
        self.assertEqual(validate_engine_plan(request, plan)["request_digest"], COMPAT_REQUEST_DIGEST)

    def test_request_is_content_bound_without_embedding_test_command_or_patch(self):
        with tempfile.TemporaryDirectory() as td:
            repo, base, candidate, base_tree, candidate_tree = make_repo(Path(td))
            request = self._request(repo, base, candidate, base_tree, candidate_tree)
            encoded = json.dumps(request)
            self.assertTrue(request["request_id"].startswith("dwerq_"))
            self.assertTrue(request["change_id"].startswith("dwchg_"))
            self.assertTrue(repository_fingerprint(repo).startswith("dwrepo_"))
            self.assertNotIn("python -m unittest", encoded)
            self.assertNotIn("patch-1", encoded)
            self.assertFalse(request["privacy"]["source_embedded"])

    def test_change_identity_depends_on_repository_and_git_trees(self):
        a = change_id(repository="dwrepo_" + "a" * 24, base_tree="b" * 40, candidate_tree="c" * 40)
        b = change_id(repository="dwrepo_" + "a" * 24, base_tree="b" * 40, candidate_tree="d" * 40)
        self.assertNotEqual(a, b)

    def test_non_finite_planning_budget_is_rejected_before_request_hashing(self):
        with tempfile.TemporaryDirectory() as td:
            repo, base, candidate, base_tree, candidate_tree = make_repo(Path(td))
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(EngineProtocolError, "planning budget"):
                        build_engine_request(
                            repo=repo,
                            base_sha=base,
                            base_tree=base_tree,
                            candidate_sha=candidate,
                            candidate_tree=candidate_tree,
                            mutations=mutations(),
                            max_experiments=40,
                            max_total_seconds=value,
                            stability_runs=2,
                            policy="balanced",
                            strategy="adaptive",
                            test_command="python -m unittest",
                        )

    def test_plan_must_be_exactly_bound_and_cover_every_mutation_once(self):
        with tempfile.TemporaryDirectory() as td:
            repo, base, candidate, base_tree, candidate_tree = make_repo(Path(td))
            request = self._request(repo, base, candidate, base_tree, candidate_tree)
            plan = {
                "schema_version": "engine-plan-1",
                "request_id": request["request_id"],
                "request_digest": request_digest(request),
                "engine": {"name": "test-engine", "version": "1"},
                "ordered_mutation_ids": ["m3", "m1", "m2"],
                "partitions": [["m3"], ["m1", "m2"]],
                "interaction_pairs": [["m1", "m2"]],
            }
            validated = validate_engine_plan(request, plan)
            self.assertEqual(validated["ordered_mutation_ids"][0], "m3")

            missing = {**plan, "ordered_mutation_ids": ["m1", "m2"]}
            with self.assertRaisesRegex(EngineProtocolError, "every mutation"):
                validate_engine_plan(request, missing)

            stale = {**plan, "request_digest": "0" * 64}
            with self.assertRaisesRegex(EngineProtocolError, "exact request"):
                validate_engine_plan(request, stale)

            non_finite = {**plan, "diagnostics": {"planner_ms": math.nan}}
            with self.assertRaisesRegex(EngineProtocolError, "non-finite"):
                validate_engine_plan(request, non_finite)

    def test_optional_engine_failure_degrades_but_required_engine_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo, base, candidate, base_tree, candidate_tree = make_repo(root)
            request = self._request(repo, base, candidate, base_tree, candidate_tree)
            bad = root / "bad_engine.py"
            bad.write_text("raise SystemExit(7)\n", encoding="utf-8")
            plan, diagnostic = run_advisory_engine(
                repo=repo,
                command=[sys.executable, str(bad)],
                request=request,
                timeout=2,
                required=False,
            )
            self.assertIsNone(plan)
            self.assertIn("exited with 7", diagnostic or "")
            with self.assertRaises(EngineProtocolError):
                run_advisory_engine(
                    repo=repo,
                    command=[sys.executable, str(bad)],
                    request=request,
                    timeout=2,
                    required=True,
                )

    def test_ambiguous_engine_json_is_rejected_before_plan_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo, base, candidate, base_tree, candidate_tree = make_repo(root)
            request = self._request(repo, base, candidate, base_tree, candidate_tree)
            fixtures = {
                "duplicate": 'print(\'{"schema_version":"engine-plan-1","schema_version":"engine-plan-1"}\')\n',
                "nan": 'print(\'{"diagnostics":{"planner_ms":NaN}}\')\n',
            }
            for label, source in fixtures.items():
                with self.subTest(label=label):
                    engine = root / f"ambiguous_{label}.py"
                    engine.write_text(source, encoding="utf-8")
                    plan, diagnostic = run_advisory_engine(
                        repo=repo,
                        command=[sys.executable, str(engine)],
                        request=request,
                        timeout=2,
                        required=False,
                    )
                    self.assertIsNone(plan)
                    self.assertTrue(
                        "duplicate JSON object key" in (diagnostic or "")
                        or "numeric constant" in (diagnostic or "")
                    )

    def test_real_subprocess_plan_is_validated_before_use(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo, base, candidate, base_tree, candidate_tree = make_repo(root)
            request = self._request(repo, base, candidate, base_tree, candidate_tree)
            engine = root / "engine.py"
            engine.write_text(textwrap.dedent("""
                import hashlib, json, sys
                request = json.load(sys.stdin)
                canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                ids = [item["id"] for item in request["mutations"]]
                print(json.dumps({
                    "schema_version": "engine-plan-1",
                    "request_id": request["request_id"],
                    "request_digest": hashlib.sha256(canonical.encode()).hexdigest(),
                    "engine": {"name": "fixture", "version": "1.0"},
                    "ordered_mutation_ids": list(reversed(ids)),
                    "partitions": [[item] for item in reversed(ids)],
                    "interaction_pairs": [],
                    "diagnostics": {"reason_codes": ["fixture"]}
                }))
            """), encoding="utf-8")
            plan, diagnostic = run_advisory_engine(
                repo=repo,
                command=[sys.executable, str(engine)],
                request=request,
                timeout=2,
            )
            self.assertIsNone(diagnostic)
            self.assertEqual(plan["ordered_mutation_ids"], ["m3", "m2", "m1"])


if __name__ == "__main__":
    unittest.main()
