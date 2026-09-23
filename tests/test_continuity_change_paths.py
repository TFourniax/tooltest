from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.continuity_bridge import record_change_envelope
from diffwitness.continuity_context import compile_context, render_context
from diffwitness.continuity_context_command import _guided_context
from diffwitness.continuity_events import ContinuityError, append_project_events, continuity_paths, read_project_events
from diffwitness.engine_protocol import change_id, repository_fingerprint
from diffwitness.runtime_executable import resolve_dw_command


class ChangePathAdmissionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'paths@example.test')
        self.git('config', 'user.name', 'Path admission')
        self.empty = self.git('mktree', input=b'').strip().decode()
        self.blob = self.git('hash-object', '-w', '--stdin', input=b'content\n').strip().decode()
        self.base = self.git('commit-tree', self.empty, '-m', 'base').strip().decode()
        self.git('update-ref', 'HEAD', self.base)

    def git(self, *args, input=None):
        return subprocess.run(['git', *args], cwd=self.repo, input=input, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=True).stdout

    def envelope(self, paths):
        # Object plumbing supports byte-exact Git names on every host OS without
        # creating illegal Windows/macOS working-tree paths.
        records = b''.join(b'100644 blob ' + self.blob.encode() + b'\t' + p + b'\0' for p in paths)
        tree = self.git('mktree', '-z', input=records).strip().decode()
        commit = self.git('commit-tree', tree, '-p', self.base, '-m', 'candidate').strip().decode()
        fingerprint = repository_fingerprint(self.repo)
        return {'schema_version': 'change-envelope-1', 'repository': {'fingerprint': fingerprint},
                'base': {'sha': self.base, 'tree': self.empty}, 'candidate': {'sha': commit, 'tree': tree},
                'change_id': change_id(repository=fingerprint, base_tree=self.empty, candidate_tree=tree)}

    def recorded(self, envelope):
        result = record_change_envelope(repo=self.repo, envelope=envelope)
        event = read_project_events(continuity_paths(self.repo).events)[-1]
        return result, event

    def test_exact_unicode_whitespace_control_and_backslash_paths(self):
        names = ['créer facture.py', ' spaced ', 'line\nbreak.py', 'tab\tname.py', 'slash\\name.py', 'carriage\rname.py']
        result, event = self.recorded(self.envelope([p.encode() for p in names]))
        self.assertEqual(result['changed_files'], sorted(names))
        self.assertEqual(event['payload']['changed_files'], sorted(names))
        for name, relation in zip(sorted(names), event['relations'], strict=True):
            self.assertEqual(relation['target']['label'], name)
            self.assertEqual(relation['target']['id'], 'file:' + hashlib.sha256(name.encode()).hexdigest()[:24])

    def test_file_facts_use_change_identity_trees_not_unrelated_or_missing_commit_hints(self):
        envelope = self.envelope([b'actual.py'])
        envelope['candidate']['sha'] = self.base
        envelope['base']['sha'] = None
        result, _ = self.recorded(envelope)
        self.assertEqual(result['changed_files'], ['actual.py'])
        before = continuity_paths(self.repo).events.read_bytes()
        envelope['candidate']['sha'] = 'collected-ephemeral-commit'
        self.assertEqual(record_change_envelope(repo=self.repo, envelope=envelope)['created']['change'], 0)
        self.assertEqual(continuity_paths(self.repo).events.read_bytes(), before)

    def test_untrusted_commit_hint_cannot_be_a_git_option(self):
        envelope = self.envelope([b'actual.py'])
        envelope['base']['sha'] = '--output=unexpected-write.txt'
        result, _ = self.recorded(envelope)
        self.assertFalse((self.repo / 'unexpected-write.txt').exists())
        self.assertEqual(result['changed_files'], ['actual.py'])

    def test_installed_cli_reports_safe_exact_and_partial_admission(self):
        names = ['é-accent.py', ' spaced '] + [f'file-{i:04}.py' for i in range(300)]
        envelope = self.envelope([name.encode() for name in names])
        envelope['base']['sha'] = '--output=unexpected-cli-write.txt'
        source = self.repo / 'envelope.json'
        source.write_text(json.dumps(envelope), encoding='utf-8')
        proc = subprocess.run([resolve_dw_command(), 'state', 'ingest-envelope', str(source), '--json'],
                              cwd=self.repo, capture_output=True, text=True, encoding='utf-8', timeout=45)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['changed_files'], sorted(names)[:256])
        self.assertEqual(result['changed_files_coverage']['omitted'], 46)
        self.assertFalse((self.repo / 'unexpected-cli-write.txt').exists())

    def test_human_context_quotes_paths_without_terminal_control_execution(self):
        names = ['a\x1b[2J.py', 'b\nFORGED.py', 'c\u202efile.py']
        self.recorded(self.envelope([name.encode() for name in names]))
        context = compile_context(self.repo, task='')
        self.assertEqual(context['recentRelatedChanges'][0]['files'], names)
        for output in (render_context(context), _guided_context(context, max_chars=12000)):
            self.assertNotIn('\x1b', output)
            self.assertNotIn('\u202e', output)
            self.assertNotIn('\nFORGED.py', output)
            self.assertIn('001b', output)

    def test_large_changes_keep_bounded_whole_paths_and_explicit_coverage(self):
        result, event = self.recorded(self.envelope([f'file-{i:04}.py'.encode() for i in range(300)]))
        self.assertEqual(len(event['relations']), 256)
        self.assertEqual(result['changed_files'], [f'file-{i:04}.py' for i in range(256)])
        self.assertEqual(event['payload']['changed_files_coverage'],
                         {'status': 'partial', 'total': 300, 'omitted': 44, 'reasons': {'path_limit': 44}})
        self.assertEqual(result['changed_files_coverage'], event['payload']['changed_files_coverage'])
        context = compile_context(self.repo, task='')
        self.assertTrue(any('change path' in warning.lower() and 'incomplete' in warning.lower()
                            for warning in context['warnings']))

    def test_unrepresentable_names_are_omitted_whole_without_relabeling(self):
        paths = [b'valid.py', b'invalid-\xff.py', ('é' * 499).encode(), b'x' * 501]
        result, event = self.recorded(self.envelope(paths))
        self.assertEqual(result['changed_files'], ['valid.py'])
        coverage = event['payload']['changed_files_coverage']
        self.assertEqual(coverage['total'], 4)
        self.assertEqual(coverage['omitted'], 3)
        self.assertEqual(sum(coverage['reasons'].values()), 3)

    def test_unavailable_tree_is_not_presented_as_observed_empty_change(self):
        envelope = self.envelope([b'actual.py'])
        envelope['candidate']['tree'] = '0' * 40
        envelope['change_id'] = change_id(repository=envelope['repository']['fingerprint'],
                                         base_tree=self.empty, candidate_tree='0' * 40)
        result, event = self.recorded(envelope)
        self.assertEqual(result['changed_files'], [])
        self.assertEqual(event['payload']['changed_files_coverage']['status'], 'unavailable')

    def test_whole_path_byte_budget_keeps_the_original_event_limit(self):
        names = [(f'{i:03}-' + 'n' * 496).encode() for i in range(256)]
        result, event = self.recorded(self.envelope(names))
        self.assertLess(len(result['changed_files']), 256)
        self.assertTrue(all(len(name) == 500 for name in result['changed_files']))
        self.assertLess(len(json.dumps(event, ensure_ascii=False).encode()), 256 * 1024)
        self.assertIn('byte_limit', event['payload']['changed_files_coverage']['reasons'])

    def test_byte_budget_counts_utf8_bytes_instead_of_characters(self):
        names = [(f'{i:03}-' + 'é' * 250).encode() for i in range(256)]
        result, event = self.recorded(self.envelope(names))
        self.assertLess(len(result['changed_files']), 256)
        self.assertTrue(all(len(name.encode()) == 504 for name in result['changed_files']))
        self.assertLess(len(json.dumps(event, ensure_ascii=False).encode()), 256 * 1024)

    def test_forged_coverage_is_rejected_atomically(self):
        _, event = self.recorded(self.envelope([f'f{i:03}'.encode() for i in range(300)]))
        journal = continuity_paths(self.repo).events
        before = journal.read_bytes()
        for alteration in ({'omitted': False}, {'total': 299}, {'reasons': {'path_limit': 43}},
                           {'status': 'complete'}, {'extension': True}):
            bad = copy.deepcopy(event)
            bad['payload']['changed_files_coverage'].update(alteration)
            bad['dedupe_key'] = None
            with self.subTest(alteration=alteration), self.assertRaises(ContinuityError):
                append_project_events(repo=self.repo, events=[bad])
            self.assertEqual(journal.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
