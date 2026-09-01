from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.engine_capabilities import EngineCapabilityError, inspect_engine_capabilities
from diffwitness.entry import main as dw_main


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return proc.stdout.strip()


def init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Doctor Test")
    git(repo, "config", "user.email", "doctor@localhost")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text(
        "import unittest\n\nclass AppTest(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo


def capability_payload(**overrides):
    payload = {
        "schema_version": "engine-capabilities-1",
        "engine": {"name": "diffwitness-private", "version": "0.1.0a1"},
        "protocol": {"request": "engine-request-1", "plan": "engine-plan-1"},
        "limits": {"request_bytes": 2 * 1024 * 1024, "mutations": 5000},
        "privacy": {
            "accepts_embedded_source": False,
            "supports_metadata_only": True,
            "supports_local_candidate_object_reads": True,
        },
        "authority": {
            "advisory_only": True,
            "executes_evidence_commands": False,
            "writes_target_repository": False,
        },
    }
    payload.update(overrides)
    return payload


def write_engine(root: Path, payload: dict) -> Path:
    script = root / "engine.py"
    script.write_text(
        "import json, sys\n"
        f"PAYLOAD = {payload!r}\n"
        "if '--capabilities' not in sys.argv:\n"
        "    raise SystemExit(9)\n"
        "print(json.dumps(PAYLOAD, sort_keys=True, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    return script


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


class EngineDoctorTests(unittest.TestCase):
    def test_capability_preflight_accepts_compatible_bounded_engine(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = init_repo(root)
            engine = write_engine(root, capability_payload())
            capabilities = inspect_engine_capabilities(
                cwd=repo,
                command=[sys.executable, str(engine)],
                timeout=2,
            )
            self.assertEqual(capabilities["engine"]["name"], "diffwitness-private")
            self.assertEqual(capabilities["protocol"]["request"], "engine-request-1")

    def test_capability_preflight_rejects_protocol_or_authority_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = init_repo(root)
            bad_protocol = capability_payload(
                protocol={"request": "engine-request-2", "plan": "engine-plan-1"}
            )
            engine = write_engine(root, bad_protocol)
            with self.assertRaisesRegex(EngineCapabilityError, "incompatible"):
                inspect_engine_capabilities(
                    cwd=repo,
                    command=[sys.executable, str(engine)],
                    timeout=2,
                )

            bad_authority = capability_payload(
                authority={
                    "advisory_only": False,
                    "executes_evidence_commands": True,
                    "writes_target_repository": False,
                }
            )
            engine.write_text(
                "import json, sys\n"
                f"PAYLOAD = {bad_authority!r}\n"
                "print(json.dumps(PAYLOAD)) if '--capabilities' in sys.argv else sys.exit(9)\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EngineCapabilityError, "authority boundary"):
                inspect_engine_capabilities(
                    cwd=repo,
                    command=[sys.executable, str(engine)],
                    timeout=2,
                )

    def test_capability_preflight_rejects_ambiguous_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = init_repo(root)
            engine = root / "ambiguous.py"
            engine.write_text(
                "import sys\n"
                "print('{\"schema_version\":\"engine-capabilities-1\",\"schema_version\":\"engine-capabilities-1\"}')\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "duplicate JSON object key"):
                inspect_engine_capabilities(
                    cwd=repo,
                    command=[sys.executable, str(engine)],
                    timeout=2,
                )

    def test_dw_doctor_reports_compatible_required_private_engine(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = init_repo(root)
            engine = write_engine(root, capability_payload())
            (repo / ".diffwitness.toml").write_text(
                "[diffwitness]\n"
                'test = "python -m unittest discover -s tests -q"\n'
                "\n[engine]\n"
                f"command = [{toml_string(sys.executable)}, {toml_string(str(engine))}]\n"
                "required = true\n"
                "timeout = 2\n",
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = dw_main(["doctor", "--repo", str(repo)])
            text = out.getvalue()
            self.assertEqual(rc, 0, text)
            self.assertIn("configured - python -m unittest", text)
            self.assertIn("compatible - diffwitness-private 0.1.0a1", text)
            self.assertIn("advisory-only", text)
            self.assertIn("embedded source refused", text)

    def test_dw_doctor_fails_preflight_for_incompatible_configured_engine(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = init_repo(root)
            engine = write_engine(
                root,
                capability_payload(
                    protocol={"request": "engine-request-9", "plan": "engine-plan-1"}
                ),
            )
            (repo / ".diffwitness.toml").write_text(
                "[diffwitness]\n"
                'test = "python -m unittest discover -s tests -q"\n'
                "\n[engine]\n"
                f"command = [{toml_string(sys.executable)}, {toml_string(str(engine))}]\n"
                "required = true\n",
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = dw_main(["doctor", "--repo", str(repo)])
            self.assertEqual(rc, 1)
            self.assertIn("Advisory:   INVALID", out.getvalue())
            self.assertIn("required advisory engine must pass preflight", out.getvalue())

    def test_dw_doctor_keeps_community_only_onboarding_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = init_repo(root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = dw_main(["doctor", "--repo", str(repo)])
            self.assertEqual(rc, 0, out.getvalue())
            self.assertIn("Community planner only", out.getvalue())
            self.assertIn("python -m unittest discover -s tests -q", out.getvalue())


if __name__ == "__main__":
    unittest.main()
