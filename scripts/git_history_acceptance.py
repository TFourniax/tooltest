"""MACHINE acceptance of installed all-branch pages on generated Git fixtures."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--dw')
args = parser.parse_args()
dw = str(Path(args.dw).resolve()) if args.dw else shutil.which('dw')
assert dw, 'installed dw required'
env = {key:value for key,value in os.environ.items() if key != 'PYTHONPATH'}

with tempfile.TemporaryDirectory(prefix='dw-history-installed-') as td:
    repo = Path(td)
    def run(command):
        result = subprocess.run(command, cwd=repo, env=env, text=True, encoding='utf-8',
                                capture_output=True, timeout=30)
        assert result.returncode == 0, (command, result.returncode, result.stdout, result.stderr)
        return result.stdout.strip()
    def git(*command):
        return run(['git', *command])
    def commit(name):
        (repo / name).write_text('VALUE=1\n', encoding='utf-8')
        git('add', '--', name)
        git('commit', '-qm', 'GENERATED_MESSAGE_' + name)
        return git('rev-parse', 'HEAD')
    def page(*options, language='en'):
        return json.loads(run([dw, '--language', language, 'state', 'bootstrap-git', '--all-branches',
                               '--max-commits', '2', '--json', *options]))
    git('init', '-q')
    git('config', 'user.name', 'Generated history fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    commit('root.py')
    main = git('branch', '--show-current')
    git('checkout', '-qb', 'side')
    commit('côté.py')
    git('checkout', '-q', main)
    commit('main.py')
    git('merge', '--no-ff', '-qm', 'GENERATED_MESSAGE_merge', 'side')
    git('checkout', '--orphan', 'separate')
    git('rm', '-rf', '.')
    commit('other.py')
    git('checkout', '-q', main)
    expected = set(git('rev-list', '--branches').splitlines())
    (repo / 'root.py').write_text('DIRTY_SOURCE_MUST_NOT_ENTER_HISTORY\n')
    (repo / 'untracked.py').write_text('UNTRACKED_SOURCE_MUST_NOT_ENTER_HISTORY\n')
    before = git('status', '--porcelain'), git('write-tree')
    first = page(language='fr')
    events_path = repo / '.git/diffwitness/events.jsonl'
    original = events_path.read_bytes()
    assert page()['created'] == 0
    assert events_path.read_bytes() == original
    assert before == (git('status', '--porcelain'), git('write-tree'))
    later = commit('later.py')
    after_advance = git('status', '--porcelain'), git('write-tree')
    current = first
    for _ in range(10):
        if current['complete']:
            break
        current = page('--cursor', current['next_cursor'])
    assert current['complete']
    observed = [json.loads(line) for line in events_path.read_text(encoding='utf-8').splitlines()]
    assert {event['payload']['commit'] for event in observed} == expected
    assert later not in expected
    assert all(event['event_type'] == 'commit.observed' for event in observed)
    assert all(marker not in events_path.read_bytes() for marker in
               (b'GENERATED_MESSAGE', b'fixture@example.invalid', b'DIRTY_SOURCE', b'UNTRACKED_SOURCE'))
    current = page('--include-messages')
    for _ in range(10):
        if current['complete']:
            break
        current = page('--include-messages', '--cursor', current['next_cursor'], language='fr')
    assert current['complete']
    observed = json.loads(run([dw, 'state', 'events', '--json', '--limit', '100']))
    assert {event['payload']['commit'] for event in observed} == expected | {later}
    assert sum(event['event_type'] == 'commit.message' for event in observed) == len(expected) + 1
    assert all(event['epistemic_status'] == 'DECLARED' for event in observed if event['event_type'] == 'commit.message')
    assert after_advance == (git('status', '--porcelain'), git('write-tree'))
    with contextlib.closing(sqlite3.connect(repo / '.git/diffwitness/state.db')) as conn:
        assert conn.execute('select count(*) from proofs').fetchone()[0] == 0
    print(json.dumps({'schema':'installed-git-history-1', 'classification':'MACHINE', 'passed':True,
                      'captured_commits':len(expected), 'later_tip_excluded_until_restart':True,
                      'messages':'explicit DECLARED opt-in', 'real_index_preserved':True}))
