from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.continuity_context_command import context_command_cli
from diffwitness.doctor import doctor_cli
from diffwitness.explain_ui import explain_ui_cli
from diffwitness.protect_ui import protect_surface_cli
from diffwitness.view_mode import set_view_mode


class GuidedSurfaceContractTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        set_view_mode(repo, "guided")
        return repo

    def _capture(self, fn, argv: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = fn(argv)
        return rc, output.getvalue()

    def test_saved_guided_view_applies_to_doctor_explain_context_and_protect(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))

            evidence = {
                "configured": True,
                "selected": True,
                "executableReady": True,
                "ready": True,
                "checksRun": False,
                "source": "configured",
                "command": "python -m unittest",
                "reason": "configured project evidence",
                "problem": None,
                "suggestion": None,
            }
            protection = {
                "mode": "builtin",
                "health": "degraded",
                "policy": "standard",
                "adapters": {
                    "claude": {
                        "installed": True,
                        "ready": True,
                        "activation": "observed",
                        "providerTrust": "unknown",
                        "activeSeen": True,
                    },
                    "codex": {
                        "installed": True,
                        "ready": False,
                        "activation": "awaiting-first-observation",
                        "providerTrust": "unknown",
                        "activeSeen": False,
                    },
                },
                "receipts": {"integrity": True, "count": 0},
            }
            readiness = {
                "repository": {"state": "committed"},
                "currentProof": {"freshness": "fresh", "currentTreeVerified": True},
                "native": {
                    "configuredAdapters": [],
                    "pendingTrustAdapters": [],
                    "runtimeUsable": False,
                    "installed": False,
                    "executableAvailable": False,
                    "adapters": {},
                },
                "scopedProduct": {"ready": True},
            }
            with (
                mock.patch("diffwitness.doctor.load_config", return_value={}),
                mock.patch("diffwitness.doctor._evidence_state", return_value=evidence),
                mock.patch("diffwitness.doctor._protect_state", return_value=(protection, True)),
                mock.patch("diffwitness.doctor._continuity_state", return_value=({"event_count": 0}, True, None)),
                mock.patch("diffwitness.doctor._engine_state", return_value=({"configured": False, "ready": True, "required": False}, True)),
                mock.patch("diffwitness.doctor.build_readiness", return_value=readiness),
            ):
                doctor_rc, doctor = self._capture(doctor_cli, ["--repo", str(repo)])
                self.assertEqual(doctor_rc, 0, doctor)
                self.assertIn("DIFFWITNESS · GUIDED CHECK-UP", doctor)
                self.assertNotIn("Current Proof:", doctor)
                self.assertNotIn("Verification command: configured=", doctor)
                self.assertNotIn("DECLARED/INFERRED/OBSERVED", doctor)
                self.assertNotIn("aggregate degraded", doctor)

                technical_rc, technical = self._capture(
                    doctor_cli, ["--repo", str(repo), "--view", "technical"]
                )
                self.assertEqual(technical_rc, 0, technical)
                self.assertIn("Current Proof:", technical)
                self.assertIn("Verification command: configured=True", technical)
                self.assertIn("DECLARED/INFERRED/OBSERVED", technical)

            explanation = {
                "change_id": "dwchg_rr007",
                "confidence": "verified",
                "coverage": {
                    "scope": "current",
                    "freshness": "current",
                    "current_worktree_covered": True,
                },
                "proof": {"accepted": True, "claim": "causal"},
                "what_changed": ["One production file changed."],
                "why_it_matters": ["The current code is covered."],
                "verify_next": ["Verify again after the next change."],
                "findings": [],
            }
            with mock.patch("diffwitness.explain_ui.load_current_explanation", return_value=explanation):
                explain_rc, explain = self._capture(explain_ui_cli, ["--repo", str(repo)])
                self.assertEqual(explain_rc, 0, explain)
                self.assertIn("DIFFWITNESS · UNDERSTAND", explain)
                self.assertNotIn("IdleProof · evidence-backed explanation", explain)
                self.assertNotIn("Confidence:", explain)

                explain_json_rc, explain_json = self._capture(
                    explain_ui_cli, ["--repo", str(repo), "--json"]
                )
                self.assertEqual(explain_json_rc, 0, explain_json)
                self.assertEqual(json.loads(explain_json), explanation)

            context = {
                "task": "Understand the calculator repair",
                "components": [{"path": "calculator.py"}],
                "objectives": [{"label": "Keep addition correct"}],
                "decisions": [],
                "invariants": [],
                "knownDebt": [],
                "recentRelatedChanges": [],
                "requiredEvidence": [],
                "warnings": [],
            }
            with mock.patch("diffwitness.continuity_context_command.compile_context", return_value=context):
                context_rc, context_text = self._capture(
                    context_command_cli,
                    ["Understand", "the", "calculator", "repair", "--repo", str(repo)],
                )
                self.assertEqual(context_rc, 0, context_text)
                self.assertIn("DIFFWITNESS · PROJECT MEMORY", context_text)
                self.assertNotIn("PROJECT OBJECTIVES", context_text)
                self.assertNotIn("KNOWN DEBT", context_text)

                context_json_rc, context_json = self._capture(
                    context_command_cli,
                    ["Understand", "the", "calculator", "repair", "--repo", str(repo), "--json"],
                )
                self.assertEqual(context_json_rc, 0, context_json)
                self.assertEqual(json.loads(context_json), context)

            with mock.patch("diffwitness.protect_ui.protect_status", return_value=protection):
                protect_rc, protect = self._capture(
                    protect_surface_cli, ["status", "--repo", str(repo)]
                )
                self.assertEqual(protect_rc, 0, protect)
                self.assertIn("DIFFWITNESS · LIVE PROTECTION", protect)
                self.assertIn("Claude Code", protect)
                self.assertIn("Codex", protect)
                self.assertNotIn("aggregate degraded", protect)
                self.assertNotIn("Protect: builtin", protect)


if __name__ == "__main__":
    unittest.main()
