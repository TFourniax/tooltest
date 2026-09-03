from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from diffwitness.engine_protocol import repository_fingerprint
from diffwitness.idleproof_sidecar import (
    IdleProofSidecarError,
    build_portal_snapshot,
    ensure_local_project,
    integration_install,
    integration_status,
    integration_uninstall,
    portal_assurance,
    portal_configure,
    portal_status,
    portal_sync,
)


class RepoFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "sidecar@diffwitness.local")
        self.git("config", "user.name", "Sidecar Test")
        (self.repo / "app.py").write_text("value = 1\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-qm", "root")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def write_evidence(self) -> None:
        state = self.repo / ".git" / "diffwitness"
        state.mkdir(parents=True, exist_ok=True)
        fingerprint = repository_fingerprint(self.repo)
        envelope = {
            "schema_version": "change-envelope-1",
            "change_id": "dwchg_0123456789abcdef01234567",
            "repository": {"fingerprint": fingerprint, "vcs": "git"},
            "privacy": {
                "code_uploaded": False,
                "contains_paths": False,
                "contains_prompt_text": False,
            },
            "proof": {
                "tool": "diffwitness",
                "certificate_id": "dw2_0123456789abcdef01234567",
                "claim": "inconclusive",
                "accepted": False,
                "certificate_schema": 2,
            },
            "debt": {
                "report_schema": "debt-report-1",
                "points": 7,
                "open_lineages": ["DW-0123456789AB"],
                "budget_passed": True,
            },
        }
        explanation = {
            "schema": "idleproof.explanation.v2",
            "source": "deterministic",
            "change_id": envelope["change_id"],
            "confidence": "mixed",
            "summary": {"files": 1, "additions": 4, "deletions": 2},
            "files": [
                {
                    "path": "src/checkout.py",
                    "kind": "production",
                    "additions": 4,
                    "deletions": 2,
                    "binary": False,
                    "structural": False,
                }
            ],
            "raw_code": "RAW_SOURCE_MUST_NEVER_LEAVE_83f1",
            "prompt": "RAW_PROMPT_MUST_NEVER_LEAVE_83f1",
        }
        (state / "change-envelope.json").write_text(json.dumps(envelope), encoding="utf-8")
        (state / "idleproof-explanation.json").write_text(json.dumps(explanation), encoding="utf-8")


class IntegrationTests(RepoFixture):
    def test_auto_without_a_detected_provider_is_actionable_and_non_mutating(self) -> None:
        with mock.patch("diffwitness.idleproof_sidecar.shutil.which", return_value=None):
            with self.assertRaisesRegex(IdleProofSidecarError, "Choose one explicitly"):
                integration_install(
                    self.repo,
                    agent="auto",
                    dw_command=str(Path(sys.executable).resolve()),
                )
        self.assertFalse((self.repo / ".claude").exists())
        self.assertFalse((self.repo / ".codex").exists())
        self.assertFalse((self.repo / ".cursor").exists())
        self.assertFalse((self.repo / ".idleproof" / "integration.json").exists())

    def test_auto_installs_only_detected_project_providers(self) -> None:
        (self.repo / ".codex").mkdir()
        with mock.patch("diffwitness.idleproof_sidecar.shutil.which", return_value=None):
            status = integration_install(
                self.repo,
                agent="auto",
                dw_command=str(Path(sys.executable).resolve()),
            )
        self.assertEqual(status["expectedAdapters"], ["codex"])
        self.assertTrue((self.repo / ".codex" / "hooks.json").is_file())
        self.assertFalse((self.repo / ".claude").exists())
        self.assertFalse((self.repo / ".cursor").exists())

    def test_install_status_and_uninstall_are_non_destructive(self) -> None:
        claude = self.repo / ".claude" / "settings.local.json"
        claude.parent.mkdir(parents=True)
        claude.write_text(
            json.dumps(
                {
                    "permissions": {"allow": ["Bash(git status:*)"]},
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": "echo keep-me"}],
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        first_project = ensure_local_project(self.repo)
        status = integration_install(
            self.repo,
            agent="all",
            dw_command=str(Path(sys.executable).resolve()),
        )
        self.assertTrue(status["healthy"])
        self.assertEqual(status["expectedAdapters"], ["claude", "codex", "cursor"])
        self.assertRegex(status["localProjectId"], r"^[a-f0-9]{24}$")
        self.assertEqual(status["localProjectId"], first_project["localId"])

        checked = integration_status(self.repo)
        self.assertTrue(checked["healthy"])
        self.assertEqual(checked["localProjectId"], first_project["localId"])

        claude_rendered = claude.read_text(encoding="utf-8")
        codex_rendered = (self.repo / ".codex" / "hooks.json").read_text(encoding="utf-8")
        for event in ("session-start", "user-prompt-submit", "session-stop"):
            self.assertIn(f"{event} --provider claude", claude_rendered)
            self.assertIn(f"{event} --provider codex", codex_rendered)

        cursor = json.loads((self.repo / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(cursor["version"], 1)
        self.assertIn("sessionStart", cursor["hooks"])
        self.assertIn("beforeSubmitPrompt", cursor["hooks"])
        self.assertIn("stop", cursor["hooks"])
        self.assertEqual(cursor["hooks"]["stop"][-1]["loop_limit"], 4)

        integration_uninstall(self.repo)
        after = json.loads(claude.read_text(encoding="utf-8"))
        self.assertEqual(after["permissions"]["allow"], ["Bash(git status:*)"])
        self.assertEqual(after["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "echo keep-me")
        self.assertFalse((self.repo / ".idleproof" / "integration.json").exists())
        self.assertTrue((self.repo / ".idleproof" / "project.json").is_file())

    def test_install_migrates_provider_neutral_hooks_without_double_execution(self) -> None:
        command = str(Path(sys.executable).resolve())
        path = self.repo / ".codex" / "hooks.json"
        path.parent.mkdir(parents=True)
        legacy = f"{command} ide-hook session-start"
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": legacy, "timeout": 10}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        status = integration_install(self.repo, agent="codex", dw_command=command)

        self.assertTrue(status["healthy"])
        rendered = path.read_text(encoding="utf-8")
        self.assertNotIn(f'"command": "{legacy}"', rendered)
        self.assertEqual(rendered.count("session-start --provider codex"), 1)

    def test_local_project_identity_is_stable_and_repo_bound(self) -> None:
        first = ensure_local_project(self.repo)
        second = ensure_local_project(self.repo)
        self.assertEqual(first["localId"], second["localId"])
        self.assertEqual(first["repositoryFingerprint"], repository_fingerprint(self.repo))
        self.assertRegex(first["localId"], r"^[a-f0-9]{24}$")


class PortalSidecarTests(RepoFixture):
    def test_endpoint_policy_and_token_is_never_persisted(self) -> None:
        with self.assertRaises(IdleProofSidecarError):
            portal_configure(self.repo, endpoint="http://example.com/functions/v1/idleproof-ingest", token_env="DW_TOKEN")
        with self.assertRaises(IdleProofSidecarError):
            portal_configure(self.repo, endpoint="https://user:pass@example.com/ingest", token_env="DW_TOKEN")
        with self.assertRaises(IdleProofSidecarError):
            portal_configure(self.repo, endpoint="https://example.com/ingest?token=bad", token_env="DW_TOKEN")

        result = portal_configure(
            self.repo,
            endpoint="https://portal.example.test/functions/v1/idleproof-ingest",
            token_env="DIFFWITNESS_PORTAL_TOKEN",
        )
        self.assertEqual(result["tokenEnv"], "DIFFWITNESS_PORTAL_TOKEN")
        stored = (self.repo / ".idleproof" / "portal.json").read_text(encoding="utf-8")
        self.assertNotIn("ipd_", stored)
        self.assertNotIn("secret", stored.lower())

    def test_snapshot_is_bounded_deterministic_and_preserves_inconclusive_proof(self) -> None:
        self.write_evidence()
        first = build_portal_snapshot(self.repo)
        second = build_portal_snapshot(self.repo)
        self.assertEqual(first["schema"], "idleproof.portal-snapshot.v1")
        self.assertEqual(first["snapshotId"], second["snapshotId"])
        self.assertRegex(first["snapshotId"], r"^ipsnap_[a-f0-9]{24}$")
        self.assertEqual(first["assurance"]["proof"]["claim"], "inconclusive")
        self.assertFalse(first["assurance"]["proof"]["accepted"])
        self.assertEqual(first["assurance"]["softwareDebt"]["points"], 7)
        self.assertEqual(first["assurance"]["softwareDebt"]["obligations"], 1)
        self.assertEqual(first["files"], ["src/checkout.py"])
        self.assertFalse(first["privacy"]["sourceCodeIncluded"])
        self.assertFalse(first["privacy"]["rawPromptIncluded"])
        self.assertFalse(first["privacy"]["rawDiffIncluded"])
        encoded = json.dumps(first, ensure_ascii=False)
        self.assertNotIn("RAW_SOURCE_MUST_NEVER_LEAVE_83f1", encoded)
        self.assertNotIn("RAW_PROMPT_MUST_NEVER_LEAVE_83f1", encoded)
        self.assertNotIn("raw_code", encoded)
        self.assertNotIn('"prompt"', encoded)

    def test_real_local_http_sync_sends_only_bounded_snapshot_and_uses_env_token(self) -> None:
        self.write_evidence()
        received: list[dict[str, object]] = []
        owner = received

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib callback
                length = int(self.headers.get("content-length") or "0")
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                owner.append({"authorization": self.headers.get("authorization"), "body": body})
                payload = {
                    "schema": "idleproof.portal-ingest-ack.v1",
                    "status": "accepted" if len(owner) == 1 else "duplicate",
                    "snapshotId": body["snapshotId"],
                }
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(202 if len(owner) == 1 else 200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            portal_configure(
                self.repo,
                endpoint=f"http://{host}:{port}/functions/v1/idleproof-ingest",
                token_env="DW_E2E_DEVICE_TOKEN",
            )
            token = "ipd_abcdefghijklmnopqrstuvwxyz012345"
            with mock.patch.dict(os.environ, {"DW_E2E_DEVICE_TOKEN": token}, clear=False):
                status = portal_status(self.repo)
                self.assertTrue(status["configured"])
                self.assertTrue(status["tokenAvailable"])
                first = portal_sync(self.repo)
                second = portal_sync(self.repo)
            self.assertEqual(first["status"], "accepted")
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(len(received), 2)
            self.assertEqual(received[0]["authorization"], f"Bearer {token}")
            uploaded = json.dumps(received[0]["body"], ensure_ascii=False)
            self.assertNotIn("RAW_SOURCE_MUST_NEVER_LEAVE_83f1", uploaded)
            self.assertNotIn("RAW_PROMPT_MUST_NEVER_LEAVE_83f1", uploaded)
            all_local_state = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (self.repo / ".idleproof").glob("*.json")
            )
            self.assertNotIn(token, all_local_state)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dry_run_needs_no_token_and_exposes_bounded_snapshot(self) -> None:
        self.write_evidence()
        portal_configure(
            self.repo,
            endpoint="https://portal.example.test/functions/v1/idleproof-ingest",
            token_env="DW_MISSING_TOKEN",
        )
        result = portal_sync(self.repo, dry_run=True)
        self.assertEqual(result["status"], "dry-run")
        self.assertFalse(result["codeUploaded"])
        self.assertFalse(result["rawPromptUploaded"])
        self.assertFalse(result["rawDiffUploaded"])
        self.assertEqual(result["snapshot"]["assurance"]["proof"]["claim"], "inconclusive")

    def test_assurance_bridge_rejects_envelope_that_violates_privacy_boundary(self) -> None:
        unsafe = self.repo / "unsafe-envelope.json"
        unsafe.write_text(
            json.dumps(
                {
                    "schema_version": "change-envelope-1",
                    "change_id": "dwchg_0123456789abcdef01234567",
                    "privacy": {"code_uploaded": True, "contains_prompt_text": False},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(IdleProofSidecarError):
            portal_assurance(self.repo, unsafe)


if __name__ == "__main__":
    unittest.main()
