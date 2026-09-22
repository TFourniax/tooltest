"""MACHINE installed-wheel journey for code-bound drift and explicit revalidation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--dw')
args = parser.parse_args()
dw = str(Path(args.dw).resolve()) if args.dw else shutil.which('dw')
assert dw, 'installed dw required'
env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}

with tempfile.TemporaryDirectory(prefix='dw-code-installed-') as td:
    repo = Path(td)
    def run(command, expected=0):
        result = subprocess.run(command, cwd=repo, env=env, capture_output=True,
                                text=True, encoding='utf-8', timeout=60)
        assert result.returncode == expected, (command, result.stdout, result.stderr)
        return result.stdout.strip()
    def git(*options):
        return run(['git', *options])
    def cli(*options, language='en'):
        return run([dw, '--language', language, *options])
    def data(*options, language='en'):
        return json.loads(cli(*options, '--json', language=language))

    git('init', '-q')
    git('config', 'user.name', 'Generated fixture')
    git('config', 'user.email', 'private@example.invalid')
    (repo / 'règles.py').write_text('PRIVATE_SOURCE = 42\n', encoding='utf-8')
    (repo / 'dependencies.lock').write_text('dependency:1\n', encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'PRIVATE_MESSAGE base')
    cli('invariant', 'add', 'Refund limit', '--id', 'INV-REFUND', '--why', 'Bound exposure')
    original = data('invariant', 'show', 'INV-REFUND')['assertion']
    bound = data('invariant', 'bind-code', 'INV-REFUND', '--path', 'règles.py',
                 '--dependency', 'dependencies.lock', '--reason', 'Selected review scope')['binding']
    assert bound['epistemic_status'] == 'DECLARED'
    (repo / 'dependencies.lock').write_text('dependency:2\n', encoding='utf-8')
    git('add', 'dependencies.lock')
    git('commit', '-qm', 'PRIVATE_MESSAGE dependency changed')
    # Dirty source must remain untouched and cannot be called validated.
    (repo / 'règles.py').write_text('PRIVATE_DIRTY_SOURCE = 99\n', encoding='utf-8')
    real_index = (repo / '.git/index').read_bytes()
    dirty_source = (repo / 'règles.py').read_bytes()
    journal = repo / '.git/diffwitness/events.jsonl'
    stable = journal.read_bytes()
    results = []
    for language in ('fr', 'en'):
        result = data('invariant', 'drift', 'INV-REFUND', language=language)
        assert result['status'] == 'changed' and result['worktree_checked'] is False
        assert result['binding_event_id'] == bound['event_id']
        assert result['binding_event_hash'] == bound['event_hash']
        results.append(result)
        for view in ('guided', 'technical'):
            text = cli('invariant', 'drift', 'INV-REFUND', '--view', view, language=language)
            assert '[OBSERVED]' in text and bound['event_id'] in text and 'règles.py' in text
    assert results[0] == results[1] and journal.read_bytes() == stable
    updated = data('invariant', 'revalidate-code', 'INV-REFUND', '--reason', 'Reviewed dependency change')['binding']
    assert updated['payload']['previous_binding_event_id'] == bound['event_id']
    assert data('invariant', 'drift', 'INV-REFUND')['status'] == 'unchanged'
    shown = data('invariant', 'show', 'INV-REFUND')
    assert shown['assertion'] == original and shown['lifecycle']['action'] == 'unreviewed'
    assert len(shown['code_references']) == 2
    assert (repo / '.git/index').read_bytes() == real_index
    assert (repo / 'règles.py').read_bytes() == dirty_source
    (repo / 'dependencies.lock').unlink()
    git('add', 'dependencies.lock')
    git('commit', '-qm', 'Dependency removed')
    real_index = (repo / '.git/index').read_bytes()
    assert data('invariant', 'drift', 'INV-REFUND')['status'] == 'changed'
    cleared = data('invariant', 'revalidate-code', 'INV-REFUND', '--clear-dependencies',
                   '--reason', 'Explicit dependency removal reviewed')['binding']
    assert [item['role'] for item in cleared['payload']['files']] == ['code']
    assert data('invariant', 'drift', 'INV-REFUND')['status'] == 'unchanged'
    assert (repo / '.git/index').read_bytes() == real_index
    assert (repo / 'règles.py').read_bytes() == dirty_source
    stable = journal.read_bytes()
    assert all(private not in stable for private in (b'PRIVATE_SOURCE', b'PRIVATE_MESSAGE', b'PRIVATE_DIRTY_SOURCE'))
    journal.write_bytes(stable.replace(b'Reviewed dependency change', b'Forged dependency change'))
    run([dw, 'invariant', 'drift', 'INV-REFUND', '--json'], expected=2)
    assert (repo / '.git/index').read_bytes() == real_index
    print(json.dumps({'schema': 'installed-memory-code-1', 'classification': 'MACHINE',
                      'passed': True, 'languages': ['fr', 'en'], 'views': ['guided', 'technical'],
                      'binding_event_id': bound['event_id'], 'binding_event_hash': bound['event_hash'],
                      'revalidation_event_id': updated['event_id'], 'real_index_preserved': True,
                      'explicit_role_removal_event_id': cleared['event_id'],
                      'dirty_worktree_preserved': True, 'assertion_and_lifecycle_preserved': True,
                      'corrupt_journal_rejected': True, 'worktree_checked': False}))
