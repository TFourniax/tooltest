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

from diffwitness.doctor import doctor_cli
from diffwitness.gitops import git, snapshot_worktree
from diffwitness.idleproof_entry import integration_install, _adapter_installed
from diffwitness.local_git_state import ensure_local_integration_excludes
from diffwitness.native_activation import record_native_activation
from diffwitness.protect import set_protect_mode, evaluate_pre_tool
from diffwitness.readiness import build_readiness, native_readiness
from diffwitness.runtime_executable import resolve_dw_command
from diffwitness.setup import _persist_setup_scope, setup_status
from diffwitness.status_cli import build_project_status, render_project_status


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        for args in [('init', '-q'), ('config', 'user.name', 'Readiness Test'),
                     ('config', 'user.email', 'readiness@example.invalid')]:
            subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True)
        (self.repo / '.diffwitness.toml').write_text('[diffwitness]\ntest = "python -m unittest -q"\n')
        (self.repo / 'app.py').write_text('VALUE = 1\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'fixture')

    def install(self, agent='codex', owner=None):
        ensure_local_integration_excludes(self.repo)
        # Apply the public idleproof entry shim exactly as its main() does.
        with mock.patch("diffwitness.idleproof_sidecar._adapter_installed", _adapter_installed):
            integration_install(self.repo, agent=agent, dw_command=owner or resolve_dw_command())
        _persist_setup_scope(self.repo, agent.split(','))

    def doctor(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = doctor_cli(['--repo', str(self.repo), '--json'])
        return rc, json.loads(out.getvalue())

    def test_ht005_missing_hooks_preserves_configured_but_repairs_in_every_view(self):
        self.install()
        (self.repo / '.codex/hooks.json').unlink()
        value = build_project_status(self.repo)
        self.assertTrue(value['setup']['native_configured'])
        self.assertFalse(value['setup']['native_installed'])
        self.assertFalse(value['setup']['native_ready'])
        self.assertEqual(value['next_actions'][0]['kind'], 'repair-native-integration')
        self.assertNotIn('use-native-agent', [x['kind'] for x in value['next_actions']])
        for view in ('guided', 'technical'):
            output = render_project_status(value, view=view)
            self.assertNotIn('PRÊT À LANCER', output)
            self.assertIn('dw setup', output)
        rc, doctor = self.doctor()
        setup = setup_status(cwd=self.repo)
        self.assertEqual(rc, 1)
        self.assertEqual(value['readiness'], doctor['readiness'])
        self.assertEqual(value['readiness'], setup['readiness'])
        self.assertFalse(setup['productReady'])

    def test_ht012_unobserved_then_observed_is_independent_of_provider_trust_and_proof(self):
        self.install()
        before = build_project_status(self.repo)
        native = before['readiness']['native']
        self.assertTrue(native['installed'])
        self.assertFalse(native['runtimeUsable'])
        self.assertEqual(before['next_actions'][0]['kind'], 'observe-native-agent')
        self.assertFalse(before['readiness']['scopedProduct']['ready'])
        hook_bytes = (self.repo / '.codex/hooks.json').read_bytes()
        record_native_activation(self.repo, 'codex')
        after = build_project_status(self.repo)
        native = after['readiness']['native']
        self.assertTrue(native['runtimeUsable'])
        self.assertEqual(native['adapters']['codex']['providerTrust'], 'unknown')
        self.assertFalse(native['adapters']['codex']['requiresProviderTrust'])
        self.assertTrue(after['readiness']['scopedProduct']['ready'])
        self.assertFalse(after['readiness']['currentProof']['currentTreeVerified'])
        self.assertEqual(after['readiness']['currentProof']['freshness'], 'unknown')
        self.assertEqual(hook_bytes, (self.repo / '.codex/hooks.json').read_bytes())
        self.assertEqual(self.doctor()[1]['readiness'], after['readiness'])
        self.assertEqual(setup_status(cwd=self.repo)['readiness'], after['readiness'])

    def test_historical_observation_does_not_hide_missing_hook_or_executable(self):
        owner = self.root / ('dw.exe' if os.name == 'nt' else 'dw')
        owner.write_text('fixture executable; never executed')
        owner.chmod(0o755)
        self.install(owner=str(owner))
        record_native_activation(self.repo, 'codex')
        owner.unlink()
        native = native_readiness(self.repo)
        self.assertTrue(native['installed'])
        self.assertTrue(native['fullyObserved'])
        self.assertFalse(native['executableAvailable'])
        self.assertFalse(native['runtimeUsable'])
        (self.repo / '.codex/hooks.json').unlink()
        native = native_readiness(self.repo)
        self.assertTrue(native['fullyObserved'])
        self.assertFalse(native['installed'])
        self.assertFalse(native['runtimeUsable'])

    def test_mixed_adapters_do_not_hide_the_unobserved_one(self):
        self.install('claude,codex')
        record_native_activation(self.repo, 'claude')
        native = native_readiness(self.repo)
        self.assertTrue(native['adapters']['claude']['runtimeUsable'])
        self.assertFalse(native['adapters']['codex']['runtimeUsable'])
        self.assertFalse(native['runtimeUsable'])
        record_native_activation(self.repo, 'codex')
        self.assertTrue(native_readiness(self.repo)['runtimeUsable'])

    def test_verification_preflight_does_not_run_the_command(self):
        marker = self.repo / 'should-not-exist'
        (self.repo / 'evidence.py').write_text("from pathlib import Path\nPath('should-not-exist').touch()\n")
        config = {'test': 'python evidence.py'}
        state = build_readiness(self.repo, config=config)
        self.assertTrue(state['verification']['configured'])
        self.assertTrue(state['verification']['executableReady'])
        self.assertFalse(state['verification']['checksRun'])
        self.assertFalse(marker.exists())
        self.assertFalse(state['currentProof']['currentTreeVerified'])
        state = build_readiness(self.repo, config={'test': 'not-a-real-dw-evidence-runner'})
        self.assertTrue(state['verification']['configured'])
        self.assertFalse(state['verification']['executableReady'])
        self.assertFalse(state['scopedProduct']['ready'])

    def test_current_proof_staleness_is_independent_of_native_readiness(self):
        self.install()
        record_native_activation(self.repo, 'codex')
        candidate = snapshot_worktree(self.repo)
        tree = git(self.repo, 'rev-parse', candidate + '^{tree}').strip()
        # Synthetic envelope fixture exercises only the existing exact-tree reader.
        envelope = self.repo / '.git/diffwitness/change-envelope.json'
        envelope.write_text(json.dumps({'proof': {'accepted': True}, 'candidate': {'tree': tree}}))
        before = build_project_status(self.repo)['readiness']
        self.assertTrue(before['currentProof']['currentTreeVerified'])
        (self.repo / 'app.py').write_text('VALUE = 2\n')
        after = build_project_status(self.repo)['readiness']
        self.assertTrue(after['native']['runtimeUsable'])
        self.assertTrue(after['scopedProduct']['ready'])
        self.assertFalse(after['currentProof']['currentTreeVerified'])
        self.assertEqual(after['currentProof']['freshness'], 'stale')
        self.assertEqual(self.doctor()[1]['readiness']['currentProof'], after['currentProof'])

    def test_protect_optional_delegated_and_pending_are_separate_from_proof(self):
        self.install()
        record_native_activation(self.repo, 'codex')
        off = build_readiness(self.repo)
        self.assertIsNone(off['protect']['ready'])
        self.assertTrue(off['scopedProduct']['ready'])
        set_protect_mode(self.repo, 'external')
        external = build_readiness(self.repo)
        self.assertTrue(external['protect']['delegated'])
        self.assertIsNone(external['protect']['ready'])
        set_protect_mode(self.repo, 'builtin', force=True)
        pending = build_readiness(self.repo)
        self.assertFalse(pending['protect']['ready'])
        self.assertFalse(pending['scopedProduct']['ready'])
        evaluate_pre_tool(self.repo, {'provider': 'codex', 'tool_name': 'shell', 'tool_input': {'command': 'git status --short'}})
        active = build_readiness(self.repo)
        self.assertTrue(active['protect']['ready'])
        self.assertTrue(active['scopedProduct']['ready'])
        self.assertFalse(active['currentProof']['currentTreeVerified'])


if __name__ == '__main__':
    unittest.main()
