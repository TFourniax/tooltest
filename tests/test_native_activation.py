from __future__ import annotations

import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from diffwitness.ide_plugin import session_start
from diffwitness.native_activation import (
    activation_path,
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

    def test_linked_worktree_uses_real_git_metadata_and_keeps_activation_local(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            linked = root / "linked"
            subprocess.check_call(
                ["git", "worktree", "add", "-q", "-b", "linked-native-test", str(linked)],
                cwd=repo,
            )
            try:
                self.assertTrue((linked / ".git").is_file())
                record_native_activation(linked, "codex")

                path = activation_path(linked)
                self.assertTrue(path.is_file())
                self.assertNotEqual(path, linked / ".git" / "diffwitness" / "native-activation.json")

                linked_state = native_activation_summary(linked, ["codex"])
                self.assertEqual(linked_state["observedAdapters"], ["codex"])
                self.assertEqual(linked_state["pendingTrustAdapters"], [])

                main_state = native_activation_summary(repo, ["codex"])
                self.assertEqual(main_state["observedAdapters"], [])
                self.assertEqual(main_state["pendingTrustAdapters"], ["codex"])
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(linked)],
                    cwd=repo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

    def test_concurrent_provider_observations_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            providers = ("claude", "codex", "cursor")

            for _ in range(5):
                clear_native_activation(repo)
                barrier = threading.Barrier(len(providers))

                def observe(provider: str) -> None:
                    barrier.wait(timeout=5)
                    record_native_activation(repo, provider)

                with ThreadPoolExecutor(max_workers=len(providers)) as executor:
                    futures = [executor.submit(observe, provider) for provider in providers]
                    for future in futures:
                        future.result(timeout=10)

                state = native_activation_summary(repo, providers)
                self.assertEqual(set(state["observedAdapters"]), set(providers))
                self.assertEqual(state["pendingObservationAdapters"], [])
                self.assertEqual(state["pendingTrustAdapters"], [])
                self.assertTrue(state["fullyObserved"])


if __name__ == "__main__":
    unittest.main()
