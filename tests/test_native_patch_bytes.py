"""Native staged-unborn counterfactuals must preserve Git patch bytes on every OS."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from diffwitness import analysis
from diffwitness.gitops import empty_analysis_base, git, head_commit, snapshot_worktree
from diffwitness.ide_plugin import session_start, session_stop, user_prompt_submit
from diffwitness.proof_cli import _state_path
from diffwitness.setup import setup_install
from diffwitness.status_cli import build_project_status
from diffwitness.continuity_state import state_status


class NativePatchBytesTests(unittest.TestCase):
    def test_native_staged_unborn_counterfactual_uses_exact_lf_and_crlf_bytes(self):
        # Unlike Path.write_text's default on Windows, these fixtures have explicit
        # bytes matching the human PowerShell LF setup, plus a real CRLF control.
        for eol in (b'\n', b'\r\n'):
            with self.subTest(eol=repr(eol)), tempfile.TemporaryDirectory() as td:
                repo = Path(td).resolve()
                git(repo, 'init', '-q'); git(repo, 'config', 'core.autocrlf', 'false')
                original = b'def add(a, b):\n    return a - b\n'.replace(b'\n', eol)
                fixed = original.replace(b'a - b', b'a + b')
                (repo / 'app.py').write_bytes(original)
                (repo / 'tests').mkdir()
                (repo / 'tests/test_app.py').write_bytes(
                    b'import unittest\nfrom app import add\nclass T(unittest.TestCase):\n'
                    b'    def test_add(self): self.assertEqual(add(2, 3), 5)\n'.replace(b'\n', eol))
                evidence = subprocess.list2cmdline([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'])
                (repo / '.diffwitness.toml').write_bytes(
                    ('[diffwitness]\ntest = ' + json.dumps(evidence) + '\nstability_runs = 1\nmax_total_seconds = 120\n').encode().replace(b'\n', eol))
                git(repo, 'add', 'app.py')
                index = (repo / '.git/index').read_bytes()
                unchanged = {p: p.read_bytes() for p in (repo / 'tests/test_app.py', repo / '.diffwitness.toml')}
                setup_install(cwd=repo, agent='codex')
                hooks = (repo / '.codex/hooks.json').read_bytes()
                payload = {'cwd': str(repo), 'session_id': 'exact-bytes', 'provider': 'codex'}
                session_start(payload)
                baseline = json.loads(_state_path(repo, 'exact-bytes').read_text())['base']
                user_prompt_submit({**payload, 'prompt': 'Fix add, changing only the return expression'})
                (repo / 'app.py').write_bytes(fixed)
                candidate = snapshot_worktree(repo)
                applications = []
                real_apply = analysis.apply_patch
                def trace_apply(worktree, text, *, reverse=False):
                    ok, error = real_apply(worktree, text, reverse=reverse)
                    applications.append({'direction': 'reverse' if reverse else 'forward',
                        'patch': text, 'worktree': str(worktree),
                        'sandboxHead': git(worktree, 'rev-parse', 'HEAD').strip(),
                        'sandboxAppHex': (worktree / 'app.py').read_bytes().hex(),
                        'ok': ok, 'stderr': error})
                    return ok, error
                with patch.object(analysis, 'apply_patch', side_effect=trace_apply):
                    result = session_stop(payload)
                diagnostic = {'eol': repr(eol), 'os': os.name, 'emptyBase': empty_analysis_base(repo),
                    'baseline': baseline, 'baselineTree': git(repo, 'rev-parse', baseline + '^{tree}').strip(),
                    'candidate': candidate, 'candidateTree': git(repo, 'rev-parse', candidate + '^{tree}').strip(),
                    'applications': applications, 'stop': result}
                self.assertIn('Proof accepted', result['systemMessage'], json.dumps(diagnostic))
                self.assertTrue(applications)
                self.assertTrue(all(item['ok'] for item in applications), diagnostic)
                self.assertEqual((repo / '.git/index').read_bytes(), index)
                self.assertEqual((repo / '.codex/hooks.json').read_bytes(), hooks)
                self.assertEqual((repo / 'app.py').read_bytes(), fixed)
                self.assertTrue(all(p.read_bytes() == value for p, value in unchanged.items()))
                self.assertIsNone(head_commit(repo))
                self.assertEqual(git(repo, 'for-each-ref'), '')
                status = build_project_status(repo)
                self.assertTrue(status['readiness']['currentProof']['currentTreeVerified'])
                self.assertGreater(state_status(repo)['event_count'], 0)
                envelope = json.loads((repo / '.git/diffwitness/change-envelope.json').read_text())
                self.assertTrue(envelope['proof']['accepted'])
                self.assertFalse((repo / '.claude').exists())


if __name__ == '__main__':
    unittest.main()
