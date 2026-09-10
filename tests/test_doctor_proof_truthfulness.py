"""HT-016: real accepted evidence, drift and failure never become launcher readiness."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from diffwitness.entry import main
from diffwitness.gitops import git


class DoctorProofTruthfulnessTests(unittest.TestCase):
    def invoke(self, repo, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = main([*args, '--repo', str(repo)])
        return rc, out.getvalue()

    def assert_state(self, repo, status, verified):
        # Explicit files only: snapshot Git object creation is permitted, mutation of these is not.
        paths = ['calculator.py', 'test_calculator.py', '.diffwitness.toml', '.git/HEAD',
                 '.git/index', '.codex/hooks.json', '.git/diffwitness/change-envelope.json']
        def fingerprint():
            return {p: hashlib.sha256((repo/p).read_bytes()).hexdigest() if (repo/p).exists() else None for p in paths}
        before = fingerprint()
        documents = {}
        for command in ('doctor', 'status'):
            rc, raw = self.invoke(repo, [command, '--json'])
            canonical = json.loads(raw)
            proof = canonical['readiness']['currentProof']
            self.assertEqual(proof['status'], status)
            self.assertEqual(proof['currentTreeVerified'], verified)
            self.assertTrue(canonical['evidence']['configured'])
            self.assertTrue(canonical['evidence']['executableReady'])
            self.assertFalse(canonical['evidence']['checksRun'])
            if status in ('accepted', 'stale'):
                self.assertEqual(proof['candidate_tree'] == proof['current_tree'], verified)
            documents[command] = proof
            for language in ('en', 'fr'):
                for view in ('guided', 'technical'):
                    args = ['--language', language, command, '--view', view]
                    rendered_rc, text = self.invoke(repo, args)
                    self.assertEqual(rendered_rc, rc)
                    if language == 'en':
                        self.assertIn(f'current tree verified={verified}', text)
                        self.assertNotIn('Evidence:   ready', text)
                        self.assertNotIn('project has no uncovered change', text)
                        if verified:
                            self.assertIn('The current exact code is covered by the latest accepted Proof.', text)
                        else:
                            self.assertIn('Next: verify the current change', text)
                            self.assertNotIn('The current exact code is covered', text)
                            if status == 'stale':
                                self.assertIn('The latest Proof is historical. The current code is not covered by it.', text)
                            else:
                                self.assertIn('No accepted Proof establishes coverage', text)
                        if command == 'doctor':
                            self.assertIn('configured=True · executable=True', text)
                            self.assertIn('without running project checks', text)
                    json_rc, raw = self.invoke(repo, [*args, '--json'])
                    self.assertEqual((json_rc, json.loads(raw)), (rc, canonical))
        self.assertEqual(documents['doctor'], documents['status'])
        self.assertEqual(fingerprint(), before)
        self.assertFalse((repo/'.claude').exists())

    def test_real_no_proof_fresh_drift_clean_stale_and_failed_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            git(repo, 'init', '-q')
            git(repo, 'config', 'user.name', 'Doctor Truthfulness')
            git(repo, 'config', 'user.email', 'doctor@example.test')
            (repo/'calculator.py').write_text('def add(a,b):\n return a-b\n', encoding='utf-8')
            (repo/'test_calculator.py').write_text('import unittest\nfrom calculator import add\nclass T(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n', encoding='utf-8')
            (repo/'.gitignore').write_text('__pycache__/\n', encoding='utf-8')
            (repo/'.codex').mkdir()
            (repo/'.codex/hooks.json').write_text('{"hooks": {}}\n', encoding='utf-8')
            command = subprocess.list2cmdline([sys.executable, '-m', 'unittest', '-q'])
            (repo/'.diffwitness.toml').write_text('[diffwitness]\ntest = '+json.dumps(command)+'\nstability_runs = 1\n', encoding='utf-8')
            git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'broken baseline')
            self.assert_state(repo, 'unknown', False)
            def guard(expression):
                code = "from pathlib import Path; Path('calculator.py').write_text("+repr('def add(a,b):\n return '+expression+'\n')+")"
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = main(['guard', '--repo', str(repo), '--policy', 'strict', '--strategy', 'auto', '--stability-runs', '1', '--', sys.executable, '-c', code])
                return rc, out.getvalue()
            rc, output = guard('a+b')
            self.assertEqual(rc, 0, output)
            self.assert_state(repo, 'accepted', True)
            envelope = (repo/'.git/diffwitness/change-envelope.json').read_bytes()
            (repo/'calculator.py').write_text('def add(a,b):\n return a*b\n', encoding='utf-8')
            self.assert_state(repo, 'stale', False)
            git(repo, 'add', 'calculator.py'); git(repo, 'commit', '-qm', 'unverified drift')
            self.assertEqual(git(repo, 'status', '--porcelain').strip(), '')
            self.assert_state(repo, 'stale', False)
            rc, output = guard('a/b')
            self.assertNotEqual(rc, 0, output)
            # Existing failure behavior retains the last accepted historical envelope.
            self.assertEqual((repo/'.git/diffwitness/change-envelope.json').read_bytes(), envelope)
            self.assert_state(repo, 'stale', False)


if __name__ == '__main__':
    unittest.main()
