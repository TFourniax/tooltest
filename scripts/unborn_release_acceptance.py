"""Qualify installed native first-task journeys without creating an initial user commit.

This executes generated hook contracts; it does not simulate provider approval.
Use --dw and --idleproof for explicit standalone/companion consumer qualification.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def run(command, repo, env, payload=None, allowed=(0,)):
    result = subprocess.run(command, cwd=repo, env=env, input=payload, text=True,
                            encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            shell=isinstance(command, str), timeout=180)
    assert result.returncode in allowed, (command, result.returncode, result.stdout, result.stderr)
    return result.stdout


def hook(repo, provider, event, payload, env):
    path = repo / ('.codex/hooks.json' if provider == 'codex' else '.claude/settings.local.json')
    hooks = json.loads(path.read_text(encoding='utf-8'))['hooks'][event]
    entry = next(h for group in hooks for h in group['hooks']
                 if 'ide-hook' in h.get('command', '') or 'ide-hook' in h.get('args', []))
    command = [entry['command'], *entry['args']] if 'args' in entry else entry['command']
    output = run(command, repo, env, json.dumps({**payload, 'hook_event_name': event}))
    # SessionStart is silent; prompt and Stop must each be one complete JSON document.
    return output if event == 'SessionStart' else json.loads(output)


def exercise(root, provider, dw, sidecar, env, *, eol):
    label = 'LF' if eol == b'\n' else 'CRLF'
    repo = root / (provider + ' ' + label + ' first task'); repo.mkdir()
    def write_fixture(path, value):
        path.write_bytes(value.encode('utf-8').replace(b'\n', eol))
    git = lambda *args: run(['git', *args], repo, env).strip()
    call = lambda *args: run([str(dw), *args], repo, env)
    git('init', '-q')
    # Cross-platform exact-tree fixture: Git must not transform these fixture bytes.
    git('config', 'core.autocrlf', 'false')
    app = repo / 'app.py'
    write_fixture(app, 'def add(a, b):\n    return a - b\n')
    (repo / 'tests').mkdir()
    write_fixture(repo / 'tests/test_app.py',
        'import unittest\nfrom app import add\nclass T(unittest.TestCase):\n'
        '    def test_add(self): self.assertEqual(add(2, 3), 5)\n')
    evidence = subprocess.list2cmdline([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'])
    write_fixture(repo / '.diffwitness.toml',
        '[diffwitness]\ntest = ' + json.dumps(evidence) + '\nstability_runs = 1\nmax_total_seconds = 120\n')
    git('add', 'app.py')
    original_index = (repo / '.git/index').read_bytes()
    original_head = (repo / '.git/HEAD').read_bytes()
    setup_args = ['setup', 'install', '--agent', provider, '--json']
    if sidecar:
        setup_args += ['--idleproof-command', str(sidecar)]
    installed = json.loads(call(*setup_args))
    assert installed['healthy'] is True, installed
    initial = json.loads(call('status', '--json'))
    assert initial['readiness']['repository']['state'] == 'unborn', initial
    assert initial['readiness']['currentProof']['currentTreeVerified'] is False, initial
    hook_path = repo / ('.codex/hooks.json' if provider == 'codex' else '.claude/settings.local.json')
    hook_bytes = hook_path.read_bytes()
    common = {'cwd': str(repo), 'session_id': 'unborn-' + provider}
    if provider == 'codex':
        common.update(model='gpt-5.5', permission_mode='default',
                      transcript_path=str(repo / '.codex/transcript.jsonl'))
    hook(repo, provider, 'SessionStart', {**common, 'source': 'startup'}, env)
    observed = json.loads(call('status', '--json'))
    assert observed['readiness']['native']['runtimeUsable'] is True, observed
    assert observed['readiness']['currentProof']['currentTreeVerified'] is False, observed
    if provider == 'codex':
        assert observed['readiness']['native']['adapters']['codex']['providerTrust'] == 'unknown', observed
    hook(repo, provider, 'UserPromptSubmit', {**common, 'turn_id': 'unborn-1',
         'prompt': 'Fix add so the existing regression test passes'}, env)
    fixed = 'def add(a, b):\n    return a + b\n'
    write_fixture(app, fixed)
    stopped = hook(repo, provider, 'Stop', {**common, 'turn_id': 'unborn-1',
        'stop_hook_active': False, 'last_assistant_message': 'Fixed add.'}, env)
    assert 'decision' not in stopped, stopped
    assert 'Proof accepted' in stopped.get('systemMessage', ''), stopped
    assert 'Continuity' in stopped['systemMessage'], stopped
    status = json.loads(call('status', '--json'))
    assert status['readiness']['currentProof']['currentTreeVerified'] is True, status
    assert status['readiness']['repository']['hasHead'] is False, status
    assert (repo / '.git/HEAD').read_bytes() == original_head
    assert (repo / '.git/index').read_bytes() == original_index
    assert git('for-each-ref') == ''
    assert hook_path.read_bytes() == hook_bytes
    if provider == 'codex':
        assert not (repo / '.claude').exists()
    envelope_paths = list((repo / '.git').rglob('*envelope*.json'))
    assert envelope_paths, 'native task did not persist its change envelope'
    envelopes = {p: p.read_bytes() for p in envelope_paths}
    provisional = next(json.loads(value)['repository']['fingerprint'] for value in envelopes.values()
                       if json.loads(value).get('schema_version') == 'change-envelope-1')
    write_fixture(app, 'def add(a, b):\n    return a + b + 1\n')
    stale = json.loads(call('status', '--json'))['readiness']['currentProof']
    assert stale['currentTreeVerified'] is False and stale['freshness'] == 'stale', stale
    write_fixture(app, fixed)
    assert json.loads(call('status', '--json'))['readiness']['currentProof']['currentTreeVerified'] is True
    # Only the fixture now explicitly creates a first user commit.
    git('config', 'user.name', 'First User Commit')
    git('config', 'user.email', 'first@example.invalid')
    git('add', 'app.py', 'tests/test_app.py', '.diffwitness.toml')
    git('commit', '-qm', 'first real user commit')
    committed = json.loads(call('status', '--json'))
    assert committed['readiness']['repository']['state'] == 'committed', committed
    assert committed['readiness']['currentProof']['currentTreeVerified'] is True, committed
    portal = json.loads(call('portal', 'status', '--json'))
    assert portal['repositoryIdentityScope'] == 'git-root-lineage', portal
    assert portal['repositoryFingerprint'] != provisional, portal
    assert all(p.read_bytes() == value for p, value in envelopes.items())
    assert hook_path.read_bytes() == hook_bytes
    print(f'PASS {provider} {label}: installed hooks, unborn task to Proof/Continuity, index/HEAD preserved, '
          'stale/return, first user commit with historical envelopes unchanged', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dw', type=Path)
    parser.add_argument('--idleproof', type=Path)
    args = parser.parse_args()
    dw = (args.dw or Path(shutil.which('dw') or '')).resolve()
    assert dw.is_file(), 'installed dw is required'
    env = {key: value for key, value in os.environ.items()
           if key not in {'DIFFWITNESS_BIN', 'DIFFWITNESS_IDLEPROOF_BIN', 'PYTHONPATH'}}
    env['PYTHONUTF8'] = '1'
    with tempfile.TemporaryDirectory(prefix='dw-unborn-') as td:
        for provider in ('codex', 'claude'):
            for eol in (b'\n', b'\r\n'):
                exercise(Path(td).resolve(), provider, dw, args.idleproof.resolve() if args.idleproof else None, env, eol=eol)
    print('Unborn repository installed consumer acceptance PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
