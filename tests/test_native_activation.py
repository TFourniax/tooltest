from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.ide_plugin import session_start
from diffwitness.native_activation import (
    clear_native_activation,
    native_activation_summary,
    record_native_activation,
)


class NativeActivationTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.check_call(["git", "init", "-q"], cwd=repo)
        subprocess.check_call(["git", "config", "user.email", "native@example.test"], cwd=repo)
        subprocess.check_call(["git", "config", "user.name", "Native Activation Test"], cwd=repo)
        (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.check_call(["git", "add", "app.py"], cwd=repo)
        subprocess.check_call(["git", "commit", "-qm", "base"], cwd=repo)
        return repo

    def test_codex_configuration_never_implies_provider_trust(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            pending = native_activation_summary(repo, ["codex"])
            self.assertEqual(pending["pendingTrustAdapters"], ["codex"])
            self.assertEqual(pending["pendingObservationAdapters"], ["codex"])
            self.assertFalse(pending["fullyObserved"])
            self.assertFalse(pending["adapters"]["codex"]["observed"])
            self.assertTrue(pending["adapters"]["codex"]["requiresProviderTrust"])
            self.assertEqual(
                pending["adapters"]["codex"]["activation"],
                "requires-provider-trust-and-observation",
            )

            record_native_activation(repo, "codex")
            observed = native_activation_summary(repo, ["codex"])
            self.assertEqual(observed["pendingTrustAdapters"], [])
            self.assertEqual(observed["observedAdapters"], ["codex"])
            self.assertTrue(observed["fullyObserved"])
            self.assertTrue(observed["adapters"]["codex"]["observed"])
            self.assertFalse(observed["adapters"]["codex"]["requiresProviderTrust"])

            clear_native_activation(repo)
            reset = native_activation_summary(repo, ["codex"])
            self.assertEqual(reset["pendingTrustAdapters"], ["codex"])
            self.assertFalse(reset["adapters"]["codex"]["observed"])

    def test_successful_provider_session_start_records_real_observation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            session_start(
                {
                    "cwd": str(repo),
                    "session_id": "trusted-codex-session",
                    "source": "codex",
                }
            )
            state = native_activation_summary(repo, ["codex"])
            self.assertTrue(state["adapters"]["codex"]["observed"])
            self.assertEqual(state["pendingTrustAdapters"], [])

    def test_unknown_source_cannot_fabricate_native_provider_observation(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            record_native_activation(repo, "made-up-provider")
            state = native_activation_summary(repo, ["codex", "claude"])
            self.assertEqual(state["observedAdapters"], [])
            self.assertEqual(state["pendingTrustAdapters"], ["codex"])


if __name__ == "__main__":
    unittest.main()
