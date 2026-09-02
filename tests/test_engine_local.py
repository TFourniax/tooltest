from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.config import engine_config_source, load_config, local_engine_profile_path, write_local_engine_profile
from diffwitness.entry import main as dw_main


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
    ).stdout.strip()


def test_command() -> str:
    return f'{sys.executable} -c "raise SystemExit(0)"'


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Engine Local Test")
    git(repo, "config", "user.email", "engine-local@localhost")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / ".diffwitness.toml").write_text(
        "[diffwitness]\n" f"test = {json.dumps(test_command())}\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo


def write_engine(root: Path, *, name: str = "private-fixture") -> Path:
    script = root / f"{name}.py"
    payload = {
        "schema_version": "engine-capabilities-1",
        "engine": {"name": name, "version": "0.1.0a1"},
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
    script.write_text(
        "import json, sys\n"
        f"PAYLOAD = {payload!r}\n"
        "if '--capabilities' not in sys.argv: raise SystemExit(9)\n"
        "print(json.dumps(PAYLOAD, sort_keys=True, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    return script


def command_json(args: list[str]) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = dw_main(args)
    return rc, json.loads(out.getvalue())


class LocalEngineTests(unittest.TestCase):
    def test_dw_engine_enable_status_doctor_disable_is_git_local(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = make_repo(root)
            engine = write_engine(root)
            self.assertEqual(git(repo, "status", "--porcelain=v1", "--untracked-files=all"), "")

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = dw_main([
                    "engine", "--repo", str(repo), "enable",
                    "--command", sys.executable, "--arg", str(engine),
                ])
            self.assertEqual(rc, 0, out.getvalue())
            self.assertIn("Activated private-fixture", out.getvalue())

            profile = local_engine_profile_path(repo)
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertTrue(profile.exists())
            self.assertIn("diffwitness", profile.as_posix())
            self.assertEqual(git(repo, "status", "--porcelain=v1", "--untracked-files=all"), "")

            loaded = load_config(repo)
            self.assertEqual(loaded["engine"]["command"], [sys.executable, str(engine)])
            self.assertTrue(loaded["engine"]["required"])

            rc, status = command_json(["engine", "--repo", str(repo), "status", "--json"])
            self.assertEqual(rc, 0, status)
            self.assertEqual(status["source"], "local")
            self.assertEqual(status["engine"]["name"], "private-fixture")
            self.assertTrue(status["required"])

            rc, doctor = command_json(["doctor", "--repo", str(repo), "--json"])
            self.assertEqual(rc, 0, doctor)
            configured = doctor["engine"]
            self.assertTrue(configured["configured"])
            self.assertTrue(configured["ready"])
            self.assertTrue(configured["required"])
            self.assertEqual(configured["capabilities"]["engine"]["name"], "private-fixture")
            self.assertEqual(configured["capabilities"]["engine"]["version"], "0.1.0a1")
            self.assertTrue(configured["capabilities"]["authority"]["advisory_only"])

            disable_out = io.StringIO()
            with contextlib.redirect_stdout(disable_out):
                rc = dw_main(["engine", "--repo", str(repo), "disable"])
            self.assertEqual(rc, 0, disable_out.getvalue())
            self.assertFalse(profile.exists())
            self.assertNotIn("engine", load_config(repo))
            self.assertEqual(git(repo, "status", "--porcelain=v1", "--untracked-files=all"), "")

    def test_committed_project_engine_wins_over_machine_local_profile(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = make_repo(root)
            local_engine = write_engine(root, name="local-fixture")
            project_engine = write_engine(root, name="project-fixture")
            write_local_engine_profile(
                repo,
                {"command": [sys.executable, str(local_engine)], "timeout": 2.0, "required": True},
            )
            (repo / ".diffwitness.toml").write_text(
                "[diffwitness]\n"
                f"test = {json.dumps(test_command())}\n\n"
                "[engine]\n"
                f"command = [{json.dumps(sys.executable)}, {json.dumps(str(project_engine))}]\n"
                "timeout = 2.0\n"
                "required = false\n",
                encoding="utf-8",
            )
            source, engine = engine_config_source(repo)
            self.assertEqual(source, "project")
            self.assertEqual(engine["command"], [sys.executable, str(project_engine)])
            self.assertEqual(load_config(repo)["engine"]["command"], [sys.executable, str(project_engine)])

    def test_corrupt_machine_local_profile_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = make_repo(root)
            profile = local_engine_profile_path(repo)
            self.assertIsNotNone(profile)
            assert profile is not None
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text('{"schema":"diffwitness.local-engine.v1","engine":', encoding="utf-8")

            rc, status = command_json(["engine", "--repo", str(repo), "status", "--json"])
            self.assertEqual(rc, 1)
            self.assertFalse(status["ok"])
            self.assertEqual(status["source"], "invalid")

            doctor_out = io.StringIO()
            with contextlib.redirect_stdout(doctor_out):
                rc = dw_main(["doctor", "--repo", str(repo)])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
