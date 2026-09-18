from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness import config
from diffwitness.continuity_context import compile_context
from diffwitness.continuity_state import rebuild_state
from diffwitness.engine_protocol import repository_fingerprint
from diffwitness.gitops import GitError, git


class ContextProcessBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = fixtures.ContinuityKernelTests().repo(Path(temporary.name))

    def test_warm_context_uses_at_most_five_git_processes(self):
        rebuild_state(self.repo, include_structure=True)
        with patch('subprocess.run', wraps=subprocess.run) as run:
            packet = compile_context(self.repo, 'refund', refresh_structure=True)
        commands = [call.args[0] for call in run.call_args_list if call.args and call.args[0][0] == 'git']
        self.assertLessEqual(len(commands), 5, commands)
        self.assertTrue(packet['project']['fingerprint'].startswith('dwrepo_'))

    def test_context_uses_project_test_configuration_without_private_engine_access(self):
        (self.repo / '.diffwitness.toml').write_text('[diffwitness]\ntest = "python -m unittest"\n', encoding='utf-8')
        with patch.object(config, 'load_local_engine_profile', side_effect=AssertionError('private profile read')):
            packet = compile_context(self.repo, 'refund', refresh_structure=False)
        self.assertIn('python -m unittest', [item.get('command') for item in packet['requiredEvidence']])

    def test_fingerprint_uses_reachable_roots_and_ignores_other_refs(self):
        (self.repo / 'HEAD').write_text('A working-tree filename is not a revision\n', encoding='utf-8')
        expected_roots = sorted(git(self.repo, 'rev-list', '--max-parents=0', 'HEAD', '--').splitlines())
        expected = 'dwrepo_' + hashlib.sha256('\n'.join(expected_roots).encode()).hexdigest()[:24]
        tree = git(self.repo, 'rev-parse', 'HEAD^{tree}').strip()
        unrelated = git(self.repo, 'commit-tree', tree, input_text='Other root\n').strip()
        git(self.repo, 'update-ref', 'refs/heads/unrelated-fixture', unrelated)
        self.assertEqual(repository_fingerprint(self.repo), expected)
        git(self.repo, 'merge', '--allow-unrelated-histories', '-s', 'ours', '--no-edit', 'unrelated-fixture')
        merged_roots = sorted([*expected_roots, unrelated])
        merged_expected = 'dwrepo_' + hashlib.sha256('\n'.join(merged_roots).encode()).hexdigest()[:24]
        self.assertEqual(repository_fingerprint(self.repo), merged_expected)

    def test_failed_committed_history_walk_is_not_an_unborn_fingerprint(self):
        real_run = subprocess.run
        def failed_walk(command, *args, **kwargs):
            if command[:3] == ['git', 'rev-list', '--max-parents=0']:
                return subprocess.CompletedProcess(command, 128, '', 'missing object')
            return real_run(command, *args, **kwargs)
        with patch('subprocess.run', side_effect=failed_walk):
            with self.assertRaises(GitError):
                repository_fingerprint(self.repo)

    def test_malformed_project_configuration_still_fails(self):
        (self.repo / '.diffwitness.toml').write_text('[diffwitness]\ntest = 123\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            compile_context(self.repo, 'refund', refresh_structure=False)


if __name__ == '__main__':
    unittest.main()
