from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from diffwitness.portal_proxy import _resolve_portal_transport, portal_cli


def _script(directory: Path, body: str) -> Path:
    path = directory / "idleproof"
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


BUNDLED = "#!/usr/bin/env python3\nfrom diffwitness.idleproof_entry import main\nraise SystemExit(main())\n"
NPM = "#!/usr/bin/env node\nimport '../lib/node_modules/idleproof/bin/idleproof.mjs';\n"


@unittest.skipIf(os.name == "nt", "POSIX executable fixtures")
class PortalTransportResolutionTests(unittest.TestCase):
    def test_idleproof_cli_is_preferred_over_the_bundled_entry_in_any_path_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv, npm = Path(tmp, "venv"), Path(tmp, "npm")
            venv.mkdir(); npm.mkdir()
            _script(venv, BUNDLED)
            idle = _script(npm, NPM)
            for order in ([venv, npm], [npm, venv]):
                with patch.dict(os.environ, {"PATH": os.pathsep.join(map(str, order))}):
                    self.assertEqual(_resolve_portal_transport(), ("idleproof", str(idle)))

    def test_bundled_entry_is_the_fallback_and_absence_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundled = _script(Path(tmp), BUNDLED)
            with patch.dict(os.environ, {"PATH": tmp}):
                self.assertEqual(_resolve_portal_transport(), ("bundled", str(bundled)))
        with tempfile.TemporaryDirectory() as empty, patch.dict(os.environ, {"PATH": empty}):
            self.assertEqual(_resolve_portal_transport(), (None, None))


class PortalDelegationTests(unittest.TestCase):
    def run_cli(self, repo: Path, argv: list[str], transport: tuple[str | None, str | None]):
        err = io.StringIO()
        completed = subprocess.CompletedProcess(["idleproof"], 0)
        with (
            patch("diffwitness.portal_proxy.repo_root", return_value=repo),
            patch("diffwitness.portal_proxy.ensure_local_integration_excludes"),
            patch("diffwitness.portal_proxy._resolve_portal_transport", return_value=transport),
            patch("diffwitness.portal_proxy.subprocess.run", return_value=completed) as run,
            redirect_stderr(err),
        ):
            rc = portal_cli(argv)
        return rc, run, err.getvalue()

    def enrollment(self, repo: Path, value: dict) -> None:
        (repo / ".idleproof").mkdir(exist_ok=True)
        (repo / ".idleproof" / "portal.json").write_text(json.dumps(value), encoding="utf-8")

    def test_every_command_uses_the_idleproof_enrollment_when_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for argv, forwarded in (
                (["id", "--json"], ["identity", "--json"]),
                (["sync", "--json"], ["sync", "--json"]),
                (["snapshot", "--json"], ["snapshot", "--json"]),
                (["assurance", "--envelope", "e.json"], ["assurance", "--envelope", "e.json"]),
            ):
                rc, run, _ = self.run_cli(repo, argv, ("idleproof", "/npm/bin/idleproof"))
                self.assertEqual(rc, 0)
                self.assertEqual(run.call_args.args[0], ["/npm/bin/idleproof", "portal", *forwarded])

    def test_bundled_enrollment_is_not_reused_silently_by_idleproof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.enrollment(repo, {"schema": "idleproof.portal-config.v1", "endpoint": "https://p.example", "tokenMode": "local-file"})
            rc, run, err = self.run_cli(repo, ["sync"], ("idleproof", "/npm/bin/idleproof"))
            self.assertEqual(rc, 2)
            run.assert_not_called()
            self.assertIn("nothing was sent", err)
            self.assertIn("dw portal id", err)
            # Re-enrolling (identity + configure) stays possible and goes to IdleProof.
            rc, run, _ = self.run_cli(repo, ["id"], ("idleproof", "/npm/bin/idleproof"))
            self.assertEqual((rc, run.call_args.args[0][2]), (0, "identity"))

    def test_idleproof_enrollment_is_never_driven_by_the_bundled_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.enrollment(repo, {"schema": "idleproof.portal-config.v1", "enabled": True, "endpoint": "https://p.example", "token": "ipd_x"})
            for argv in (["configure", "--endpoint", "https://p.example", "--token-stdin"], ["sync"], ["snapshot"]):
                rc, run, err = self.run_cli(repo, argv, ("bundled", "/venv/bin/idleproof"))
                self.assertEqual(rc, 2)
                run.assert_not_called()
                self.assertIn("nothing was configured or sent", err)


if __name__ == "__main__":
    unittest.main()


class BundledRepeatableSyncTests(unittest.TestCase):
    """The bundled transport resends an unchanged snapshot byte-for-byte (Portal duplicate)."""

    def setUp(self) -> None:
        from diffwitness.idleproof_sidecar import portal_configure

        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@diffwitness.local"], ["config", "user.name", "T"]):
            subprocess.check_call(["git", *args], cwd=self.repo)
        (self.repo / "app.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "app.py"], cwd=self.repo)
        subprocess.check_call(["git", "commit", "-qm", "root"], cwd=self.repo)
        portal_configure(self.repo, endpoint="https://portal.example.test/ingest", token_env="DW_TEST_TOKEN")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def sync_bodies(self, outcomes: list) -> list[dict]:
        from diffwitness import idleproof_sidecar

        bodies: list[dict] = []

        def post(_endpoint, _token, snapshot):
            bodies.append(json.loads(idleproof_sidecar._canonical(snapshot)))
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return 202, {"schema": idleproof_sidecar.ACK_SCHEMA, "status": outcome, "snapshotId": snapshot["snapshotId"]}

        with (
            patch.dict(os.environ, {"DW_TEST_TOKEN": "ipd_abcdefghijklmnopqrstuvwxyz012345"}),
            patch.object(idleproof_sidecar, "_post_snapshot", side_effect=post),
        ):
            for _ in range(len(outcomes)):
                try:
                    idleproof_sidecar.portal_sync(self.repo)
                except (OSError, idleproof_sidecar.IdleProofSidecarError):
                    pass
        return bodies

    def test_repeated_sync_and_retry_after_lost_ack_resend_the_identical_body(self) -> None:
        bodies = self.sync_bodies([OSError("connection reset after acceptance"), "duplicate", "duplicate", "duplicate"])
        self.assertEqual(len(bodies), 4)
        self.assertTrue(all(body == bodies[0] for body in bodies))

    def test_new_content_gets_a_new_identity_and_time(self) -> None:
        first = self.sync_bodies(["accepted"])[0]
        state = self.repo / ".git" / "diffwitness"
        state.mkdir(parents=True, exist_ok=True)
        (state / "idleproof-explanation.json").write_text(json.dumps({"schema": "idleproof.explanation.v2", "files": [{"path": "app.py", "kind": "modified"}], "summary": {"files": 1}}), encoding="utf-8")
        second = self.sync_bodies(["accepted"])[0]
        self.assertNotEqual(second["snapshotId"], first["snapshotId"])
        self.assertNotEqual(second["generatedAt"], first["generatedAt"])


class ExplainPrerequisiteTests(unittest.TestCase):
    def test_missing_capture_names_the_capture_paths_and_where_idleproof_tasks_are_explained(self) -> None:
        from diffwitness.idleproof_explanation import load_current_explanation

        with tempfile.TemporaryDirectory() as tmp:
            subprocess.check_call(["git", "init", "-q"], cwd=tmp)
            with self.assertRaises(FileNotFoundError) as caught:
                load_current_explanation(tmp)
        message = str(caught.exception)
        for expected in ("dw setup", "dw guard", "idleproof run", "idleproof receipt", "Portal"):
            self.assertIn(expected, message)


class BundledEntryDelegationTests(unittest.TestCase):
    """`idleproof portal …` typed by the user reaches the IdleProof CLI even when this wheel's
    console script comes first on PATH; integration commands stay in-process."""

    def run_entry(self, argv: list[str], transport: tuple[str | None, str | None]):
        from diffwitness import idleproof_entry

        with (
            patch("diffwitness.portal_proxy._resolve_portal_transport", return_value=transport),
            patch("diffwitness.portal_proxy.portal_cli", return_value=0) as proxy,
            patch.object(idleproof_entry._sidecar, "main", return_value=0) as bundled,
        ):
            rc = idleproof_entry.main(argv)
        return rc, proxy, bundled

    def test_portal_commands_are_forwarded_to_the_idleproof_cli(self) -> None:
        rc, proxy, bundled = self.run_entry(["portal", "identity", "--json"], ("idleproof", "/npm/bin/idleproof"))
        self.assertEqual(rc, 0)
        proxy.assert_called_once_with(["identity", "--json"])
        bundled.assert_not_called()

    def test_without_an_idleproof_cli_the_bundled_integration_answers_without_recursion(self) -> None:
        rc, proxy, bundled = self.run_entry(["portal", "sync"], ("bundled", "/venv/bin/idleproof"))
        self.assertEqual(rc, 0)
        proxy.assert_not_called()
        bundled.assert_called_once()

    def test_other_commands_typed_by_the_user_reach_the_idleproof_cli(self) -> None:
        from diffwitness import idleproof_entry

        completed = subprocess.CompletedProcess(["idleproof"], 0)
        with (
            patch("diffwitness.portal_proxy._resolve_portal_transport", return_value=("idleproof", "/npm/bin/idleproof")),
            patch("subprocess.run", return_value=completed) as run,
            patch.object(idleproof_entry._sidecar, "main", return_value=0) as bundled,
        ):
            rc = idleproof_entry.main(["run", "--", "git", "status"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.args[0], ["/npm/bin/idleproof", "run", "--", "git", "status"])
        bundled.assert_not_called()

    def test_integration_commands_used_by_setup_stay_in_process(self) -> None:
        rc, proxy, bundled = self.run_entry(["integration", "status"], ("idleproof", "/npm/bin/idleproof"))
        self.assertEqual(rc, 0)
        proxy.assert_not_called()
        bundled.assert_called_once()
