"""Unsupported textual bytes must stop before analysis and persistence."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from diffwitness import cli
from diffwitness.diffing import _mutation_id, parse_file_patches
from diffwitness.gitops import git, head_commit


class PatchEncodingBoundaryTests(unittest.TestCase):
    def test_distinct_invalid_bytes_are_rejected_before_identity(self):
        for byte in (b'\xff', b'\xfe'):
            text = ('diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n'
                    '@@ -1 +1 @@\n-old\n+').encode() + byte + b'\n'
            decoded = text.decode('utf-8', 'surrogateescape')
            for operation in (lambda: parse_file_patches(decoded),
                              lambda: _mutation_id('a.py', decoded)):
                with self.assertRaisesRegex(ValueError, 'INCONCLUSIVE.*unsupported-text-encoding') as cm:
                    operation()
                self.assertNotIsInstance(cm.exception, UnicodeEncodeError)
        valid = 'diff --git a/café.py b/café.py\r\n+é\r\n'
        expected = hashlib.sha256(('café.py\0' + valid).encode('utf-8')).hexdigest()[:10]
        self.assertEqual(_mutation_id('café.py', valid), expected)

    def test_real_prove_rejects_non_utf8_before_analysis_or_outputs(self):
        for byte in (b'\xff', b'\xfe'):
            with self.subTest(byte=byte), tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve(); repo = root / 'repo'; repo.mkdir()
                git(repo, 'init', '-q'); git(repo, 'config', 'core.autocrlf', 'false')
                git(repo, 'config', 'user.name', 'Encoding Fixture')
                git(repo, 'config', 'user.email', 'encoding@example.invalid')
                original = b'# coding: latin-1\n# context ' + byte + b'\ndef add(a, b):\n    return a - b\n'
                app = repo / 'app.py'; app.write_bytes(original)
                git(repo, 'add', 'app.py'); git(repo, 'commit', '-qm', 'baseline')
                app.write_bytes(original.replace(b'a - b', b'a + b'))
                index = (repo / '.git/index').read_bytes(); head = head_commit(repo)
                args = ['prove', '--repo', str(repo), '--base', 'HEAD', '--candidate', 'WORKTREE',
                        '--test', 'must-never-run', '--certificate', str(root / 'proof.json'),
                        '--report', str(root / 'proof.md'), '--minimize',
                        '--reduction-patch', str(root / 'reduction.patch')]
                out = io.StringIO(); err = io.StringIO()
                with patch.object(cli, 'run_analysis') as analyze, patch.object(cli, 'build_report') as report:
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        result = cli.main(args)
                    analyze.assert_not_called(); report.assert_not_called()
                self.assertEqual(result, 2)
                self.assertIn('INCONCLUSIVE [unsupported-text-encoding]', err.getvalue())
                self.assertNotIn('UnicodeEncodeError', err.getvalue())
                self.assertNotIn('analyzed mutation', out.getvalue())
                for name in ('proof.json', 'proof.md', 'reduction.patch'):
                    self.assertFalse((root / name).exists())
                self.assertEqual((repo / '.git/index').read_bytes(), index)
                self.assertEqual(head_commit(repo), head)
                self.assertEqual(app.read_bytes(), original.replace(b'a - b', b'a + b'))

    def test_utf8_prove_persists_certificate_and_exact_crlf_reduction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve(); repo = root / 'repo'; repo.mkdir()
            git(repo, 'init', '-q'); git(repo, 'config', 'core.autocrlf', 'false')
            git(repo, 'config', 'user.name', 'Encoding Fixture')
            git(repo, 'config', 'user.email', 'encoding@example.invalid')
            original = '# café\r\ndef add(a, b):\r\n    return a - b\r\n'.encode()
            (repo / 'app.py').write_bytes(original)
            (repo / 'tests').mkdir()
            (repo / 'tests/test_app.py').write_bytes(b'import unittest\nfrom app import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2,3),5)\n')
            git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'baseline')
            # One necessary and one irrelevant file: minimization must write a real delta.
            (repo / 'app.py').write_bytes(original.replace(b'a - b', b'a + b'))
            (repo / 'extra.py').write_bytes('# café\r\nunused = 1\r\n'.encode())
            command = subprocess.list2cmdline([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'])
            certificate = root / 'proof.json'; reduction = root / 'reduction.patch'
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = cli.main(['prove', '--repo', str(repo), '--test', command, '--base', 'HEAD',
                    '--candidate', 'WORKTREE', '--certificate', str(certificate), '--minimize',
                    '--reduction-patch', str(reduction)])
            self.assertEqual(result, 0)
            report = json.loads(certificate.read_bytes().decode('utf-8'))
            self.assertTrue(report['certificate_id'].startswith('dw2_'))
            delta = reduction.read_bytes()
            self.assertIn('-# café\r\n-unused = 1\r\n'.encode(), delta)
            self.assertNotIn(b'\r\r\n', delta)
