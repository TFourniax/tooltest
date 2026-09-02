from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diffwitness.entry import main
from diffwitness.idleproof_user_inference import (
    UserInferenceError,
    _cache_key,
    _print_units,
    _store_cache,
    _validate_transport_security,
    call_user_owned_provider,
    presentation_units,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.payload[:size] if size >= 0 else self.payload


class _Opener:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0
        self.last_request = None

    def open(self, request, timeout=None):
        self.calls += 1
        self.last_request = request
        return _Response(self.payload)


class IdleProofUserInferenceTests(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q")
        self.git(repo, "config", "user.email", "idleproof@example.test")
        self.git(repo, "config", "user.name", "IdleProof Test")
        (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "base")
        explanation = {
            "schema": "idleproof.explanation.v2",
            "source": "deterministic",
            "change_id": "dwchg_test",
            "confidence": "mixed",
            "proof": {"accepted": True, "claim": "validation", "explanation": "Evidence accepted."},
            "summary": {"files": 1, "findings": 1},
            "what_changed": ["One production file changed."],
            "why_it_matters": ["The change is backed by bounded evidence."],
            "findings": [
                {
                    "id": "DW-TEST",
                    "title": "Review this boundary",
                    "explanation": "A heuristic finding remains advisory.",
                    "confidence": "advisory",
                    "location": "app.py:1",
                }
            ],
            "verify_next": ["Run the focused test."],
            "files": [{"path": "app.py", "kind": "production", "additions": 1, "deletions": 0}],
            "provenance": {"code_uploaded": False, "llm_used": False, "network_required": False},
        }
        path = repo / ".git" / "diffwitness" / "idleproof-explanation.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(explanation), encoding="utf-8")
        return repo

    def context(self) -> dict:
        return {
            "schema": "idleproof.llm-context.v1",
            "role": "Presentation only. Do not add facts.",
            "facts": {
                "what_changed": ["One production file changed."],
                "why_it_matters": ["Evidence is bounded."],
                "findings": [
                    {
                        "title": "Review boundary",
                        "explanation": "This remains advisory.",
                        "confidence": "advisory",
                        "location": "app.py:1",
                    }
                ],
                "verify_next": ["Run the focused test."],
            },
        }

    def test_slots_presentation_units_serialize_and_provider_rewrites_only_existing_ids(self):
        context = self.context()
        units = presentation_units(context)
        self.assertGreaterEqual(len(units), 4)
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "rewrites": [
                                    {"id": units[0].id, "text": "A clearer equivalent sentence."},
                                    {"id": "invented:99", "text": "This must be ignored."},
                                ]
                            }
                        )
                    }
                }
            ]
        }
        opener = _Opener(payload)
        with mock.patch("urllib.request.build_opener", return_value=opener):
            result = call_user_owned_provider(
                context=context,
                endpoint="https://provider.example/v1/chat/completions?secret=never-echo",
                model="user/model",
                api_key="user-secret",
            )
        self.assertEqual(opener.calls, 1)
        self.assertEqual(result["provider_endpoint"], "https://provider.example/v1/chat/completions")
        self.assertEqual(result["canonical_source"], "deterministic")
        self.assertFalse(result["diffwitness_managed_api_used"])
        ids = {unit["id"] for unit in result["units"]}
        self.assertNotIn("invented:99", ids)
        self.assertEqual(result["units"][0]["original"], "One production file changed.")
        self.assertEqual(result["units"][0]["text"], "A clearer equivalent sentence.")
        self.assertTrue(result["units"][0]["presentation_only"])
        self.assertIn("Bearer user-secret", opener.last_request.headers.get("Authorization", ""))

    def test_provider_control_characters_are_neutralized_before_display_or_cache(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"rewrites": [{"id": "what_changed:0", "text": "\u001b[31mPretend everything is safe\u001b[0m"}]}
                        )
                    }
                }
            ]
        }
        opener = _Opener(payload)
        with mock.patch("urllib.request.build_opener", return_value=opener):
            result = call_user_owned_provider(
                context=self.context(),
                endpoint="https://provider.example/v1/chat/completions",
                model="user/model",
                api_key="user-secret",
            )
        self.assertNotIn("\x1b", result["units"][0]["text"])
        self.assertEqual(result["units"][0]["original"], "One production file changed.")

    def test_human_output_always_shows_deterministic_original_before_labelled_ai_wording(self):
        result = {
            "source": "user-owned-ai",
            "canonical_source": "deterministic",
            "units": [
                {
                    "id": "what_changed:0",
                    "section": "what_changed",
                    "original": "Canonical deterministic fact.",
                    "text": "Smoother wording.",
                    "rewritten": True,
                    "presentation_only": True,
                }
            ],
            "cost_owner": "user",
            "diffwitness_managed_api_used": False,
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            _print_units(result)
        rendered = output.getvalue()
        self.assertLess(rendered.index("Canonical deterministic fact."), rendered.index("Smoother wording."))
        self.assertIn("AI wording (presentation only)", rendered)
        self.assertIn("Canonical wording above remains the deterministic evidence-derived", rendered)

    def test_api_key_cannot_be_sent_over_plain_http_except_loopback(self):
        with self.assertRaises(UserInferenceError):
            _validate_transport_security("http://provider.example/v1/chat/completions", api_key="secret")
        self.assertEqual(
            _validate_transport_security("http://127.0.0.1:11434/v1/chat/completions", api_key="secret"),
            "http://127.0.0.1:11434/v1/chat/completions",
        )

    def test_default_dw_explain_never_builds_a_network_opener(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            out = io.StringIO()
            with mock.patch("urllib.request.build_opener") as build_opener, contextlib.redirect_stdout(out):
                self.assertEqual(main(["explain", "--repo", str(repo), "--view", "technical"]), 0)
            build_opener.assert_not_called()
            self.assertIn("No LLM or paid API was used", out.getvalue())

    def test_managed_engine_is_impossible_from_oss_cli_and_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            out = io.StringIO()
            err = io.StringIO()
            with (
                mock.patch("urllib.request.build_opener") as build_opener,
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                self.assertEqual(main(["explain", "--repo", str(repo), "--engine", "managed"]), 0)
            build_opener.assert_not_called()
            self.assertIn("deliberately unavailable in the OSS CLI", err.getvalue())
            self.assertIn("No DiffWitness-paid API was contacted", err.getvalue())
            self.assertTrue(
                "No LLM or paid API was used" in out.getvalue()
                or "Aucun LLM ni API payante" in out.getvalue()
            )

    def test_openrouter_uses_only_user_key_and_cache_prevents_second_provider_call(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"rewrites": [{"id": "what_changed:0", "text": "Same fact, smoother wording."}]}
                            )
                        }
                    }
                ]
            }
            opener = _Opener(payload)
            env = {"OPENROUTER_API_KEY": "user-openrouter-key"}
            with mock.patch.dict(os.environ, env, clear=False), mock.patch("urllib.request.build_opener", return_value=opener):
                first = io.StringIO()
                with contextlib.redirect_stdout(first):
                    self.assertEqual(
                        main(["explain", "--repo", str(repo), "--engine", "openrouter", "--model", "user/model"]),
                        0,
                    )
                second = io.StringIO()
                with contextlib.redirect_stdout(second):
                    self.assertEqual(
                        main(["explain", "--repo", str(repo), "--engine", "openrouter", "--model", "user/model"]),
                        0,
                    )
            self.assertEqual(opener.calls, 1)
            self.assertIn("One production file changed.", first.getvalue())
            self.assertIn("AI wording (presentation only): Same fact, smoother wording.", first.getvalue())
            self.assertIn("cached", second.getvalue())
            cache = repo / ".git" / "diffwitness" / "idleproof-ai-cache.json"
            self.assertTrue(cache.is_file())
            self.assertNotIn("user-openrouter-key", cache.read_text(encoding="utf-8"))

    def test_cache_is_content_addressed_by_context_endpoint_and_model(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self.repo(Path(td))
            context = self.context()
            key_a = _cache_key(context=context, endpoint="https://a.example/v1/chat/completions", model="m1")
            key_b = _cache_key(context=context, endpoint="https://a.example/v1/chat/completions", model="m2")
            self.assertNotEqual(key_a, key_b)
            _store_cache(
                repo,
                key_a,
                {
                    "source": "user-owned-ai",
                    "canonical_source": "deterministic",
                    "units": [],
                    "cost_owner": "user",
                    "diffwitness_managed_api_used": False,
                },
            )
            self.assertLess((repo / ".git" / "diffwitness" / "idleproof-ai-cache.json").stat().st_size, 1_000_000)


if __name__ == "__main__":
    unittest.main()
