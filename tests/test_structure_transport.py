from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


class StructureTransportTests(unittest.TestCase):
    def request(self, files):
        return {'schema_version': 'structure-request-1', 'files': [
            {'path': path, 'content_base64': base64.b64encode(content).decode('ascii')}
            for path, content in files]}

    def run_cli(self, request, language='en'):
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run([sys.executable, '-m', 'diffwitness.entry', '--language', language,
                                     'state', 'extract', '--json'], input=request, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=td,
                                    encoding='utf-8', timeout=10)
            self.assertEqual(list(Path(td).iterdir()), [], 'pure extraction must not persist input')
        return result

    def test_real_cli_outside_git_preserves_python_provider_and_french_json(self):
        source = 'def café(x):\n    return x\n'.encode()
        request = json.dumps(self.request([('src/payments.py', source), ('notes.unknown', b'opaque')]))
        results = [self.run_cli(request, language) for language in ('en', 'fr')]
        self.assertTrue(all(r.returncode == 0 for r in results), '\n'.join(r.stderr for r in results))
        self.assertEqual(results[0].stdout, results[1].stdout)
        value = json.loads(results[0].stdout)
        self.assertEqual(value['schema_version'], 'structure-response-1')
        first, fallback = value['files']
        self.assertEqual(first['source_sha256'], hashlib.sha256(source).hexdigest())
        self.assertEqual(first['symbols'][0]['qualified_name'], 'src.payments.café')
        self.assertEqual(first['symbols'][0]['epistemic_status'], 'OBSERVED')
        self.assertEqual(fallback['provider'], 'file-only')
        self.assertFalse(fallback['parsed'])
        self.assertEqual(fallback['symbols'], [])

    def test_extraction_stays_independent_of_journal_proof_and_debt_services(self):
        script = '''
import sys
class UnavailableServices:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'diffwitness.continuity_bridge', 'diffwitness.continuity_context',
                        'diffwitness.continuity_debt_bridge', 'diffwitness.continuity_events',
                        'diffwitness.continuity_state', 'diffwitness.engine_protocol',
                        'diffwitness.gitops', 'diffwitness.continuity_contract',
                        'diffwitness.structure_provider'}:
            raise RuntimeError('unrelated service initialized: ' + fullname)
sys.meta_path.insert(0, UnavailableServices())
from diffwitness.entry import main
raise SystemExit(main(sys.argv[1:]))
'''
        for version in (1, 2):
            request = self.request([('worker.py', 'def café(): pass'.encode()), ('settings.json', b'{"active":true}')])
            request['schema_version'] = f'structure-request-{version}'
            for language in ('en', 'fr'):
                with self.subTest(version=version, language=language), tempfile.TemporaryDirectory() as td:
                    result = subprocess.run([sys.executable, '-c', script, '--language', language,
                                             'state', 'extract', '--json'], input=json.dumps(request),
                                            capture_output=True, text=True, encoding='utf-8', cwd=td, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    value = json.loads(result.stdout)
                    self.assertEqual(value['schema_version'], f'structure-response-{version}')
                    self.assertEqual(value['files'][0]['symbols'][0]['qualified_name'], 'worker.café')
                    self.assertEqual(value['files'][1]['path'], 'settings.json')
                    self.assertEqual(list(Path(td).iterdir()), [])

    def test_python_only_extraction_does_not_initialize_optional_distribution_metadata(self):
        script = """
import sys
class NoOptionalMetadata:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'importlib.metadata':
            raise RuntimeError('optional distribution metadata initialized for Python source')
sys.meta_path.insert(0, NoOptionalMetadata())
from diffwitness.entry import main
raise SystemExit(main(['state', 'extract', '--json']))
"""
        for version in (1, 2):
            request = self.request([('worker.py', b'def actual(): pass')])
            request['schema_version'] = f'structure-request-{version}'
            with self.subTest(version=version), tempfile.TemporaryDirectory() as td:
                result = subprocess.run([sys.executable, '-c', script], input=json.dumps(request),
                                        capture_output=True, text=True, encoding='utf-8', cwd=td, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)['files'][0]['parsed'])

    def test_malformed_json_path_base64_schema_and_duplicate_paths_fail_atomically(self):
        good = self.request([('ok.py', b'def ok(): pass')])
        cases = ['{"schema_version":"x","schema_version":"structure-request-1","files":[]}']
        for path in ('/secret.py', '../secret.py', 'a/../secret.py', 'C:/secret.py', 'a\\b.py', './a.py', 'a//b.py', 'a\x00.py'):
            cases.append(json.dumps(self.request([(path, b'x')])) )
        cases.extend(json.dumps(value) for value in (
            {**good, 'schema_version': 'unsupported'}, {**good, 'extra': True},
            {**good, 'files': good['files'] * 2},
            {**good, 'files': [{'path': 'ok.py', 'content_base64': '!!!!'}]},
            {**good, 'files': [{'path': 'ok.py', 'content_base64': 'eA==\n'}]},
            {**good, 'files': [{'path': 'ok.py', 'content_base64': 'eB=='}]},
            {**good, 'files': [{'path': 'ok.py', 'content_base64': 42}]},
        ))
        for request in cases:
            with self.subTest(request=request):
                result = self.run_cli(request)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')

    def test_transport_limits_and_binary_or_invalid_python_have_explicit_coverage(self):
        from diffwitness.structure_transport import extract_request
        from diffwitness.structure_sources import MAX_SOURCE_FILE_BYTES
        for files in ([('big.py', b'x' * (MAX_SOURCE_FILE_BYTES + 1))],
                      [(f'{i}.py', b'x') for i in range(65)],
                      [(f'{i}.py', b'x' * MAX_SOURCE_FILE_BYTES) for i in range(5)]):
            with self.assertRaises(ValueError):
                extract_request(self.request(files))
        value = extract_request(self.request([('bad.py', b'def broken('), ('blob.bin', b'\xff\x00')]))
        self.assertEqual([f['parsed'] for f in value['files']], [False, False])
        self.assertEqual(value['coverage'], {'files': 2, 'parsed': 0, 'unsupported': 1, 'unparsed': 1})

    def test_results_are_detached_and_empty_batch_is_valid(self):
        from diffwitness.structure_transport import extract_request
        request = self.request([('a.py', b'def known(): pass')])
        first = extract_request(request)
        first['files'][0]['symbols'][0]['qualified_name'] = 'invented'
        self.assertEqual(extract_request(request)['files'][0]['symbols'][0]['qualified_name'], 'a.known')
        self.assertEqual(extract_request(self.request([]))['files'], [])

    def test_wire_bounds_reject_before_emitting_any_partial_response(self):
        from diffwitness import structure_transport as transport
        request = json.dumps(self.request([])).encode()
        for setting in ('MAX_WIRE_BYTES', 'MAX_RESPONSE_BYTES'):
            with self.subTest(setting=setting), patch.object(transport, setting, 8):
                stdin = io.TextIOWrapper(io.BytesIO(request), encoding='utf-8')
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(sys, 'stdin', stdin), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(transport.extraction_cli(), 2)
                self.assertEqual(stdout.getvalue(), '')
                self.assertIn('wire-byte bound', stderr.getvalue())

    def test_public_entry_never_discovers_repository_or_reads_language_preferences(self):
        from diffwitness.entry import main
        for options in ([], ['--language', 'en'], ['--language=fr']):
            with self.subTest(options=options):
                stdin = io.TextIOWrapper(io.BytesIO(json.dumps(self.request([])).encode()), encoding='utf-8')
                stdout = io.StringIO()
                with patch('diffwitness.gitops.repo_root', side_effect=AssertionError('repository lookup forbidden')) as root, \
                     patch('diffwitness.language.saved_language', side_effect=AssertionError('preferences forbidden')) as language, \
                     patch.object(sys, 'stdin', stdin), contextlib.redirect_stdout(stdout):
                    self.assertEqual(main([*options, 'state', 'extract', '--json']), 0)
                root.assert_not_called()
                language.assert_not_called()
                self.assertEqual(json.loads(stdout.getvalue())['files'], [])


if __name__ == '__main__':
    unittest.main()
