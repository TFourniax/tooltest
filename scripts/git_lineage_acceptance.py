"""MACHINE installed-wheel acceptance for explicit, cited relocation hypotheses."""
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
env = {key:value for key,value in os.environ.items() if key != 'PYTHONPATH'}

with tempfile.TemporaryDirectory(prefix='dw-lineage-installed-') as td:
    repo = Path(td)
    def run(command):
        process = subprocess.run(command, cwd=repo, env=env, capture_output=True,
                                 text=True, encoding='utf-8', timeout=30)
        assert process.returncode == 0, (command, process.stdout, process.stderr)
        return process.stdout.strip()
    def git(*options):
        return run(['git', *options])
    def page(*options, language='en'):
        return json.loads(run([dw, '--language', language, 'state', 'bootstrap-git',
                               '--all-branches', '--include-lineage', '--max-commits', '1', '--json', *options]))
    git('init', '-q')
    git('config', 'user.name', 'Generated fixture')
    git('config', 'user.email', 'private@example.invalid')
    (repo / 'ancien.py').write_text('PRIVATE_SOURCE = 42\n', encoding='utf-8')
    git('add', 'ancien.py')
    git('commit', '-qm', 'PRIVATE_MESSAGE root')
    git('mv', 'ancien.py', 'déplacé.py')
    git('commit', '-qm', 'PRIVATE_MESSAGE moved')
    tip = git('rev-parse', 'HEAD')
    before = (repo / '.git/index').read_bytes()
    first = page(language='fr')
    events = repo / '.git/diffwitness/events.jsonl'
    original = events.read_bytes()
    assert first['lineage_pairs'] == 1 and first['created'] == 2
    assert page()['created'] == 0 and events.read_bytes() == original
    assert first['next_cursor']
    assert page('--cursor', first['next_cursor'])['complete']
    stable = events.read_bytes()
    for language in ('fr', 'en'):
        result = json.loads(run([dw, '--language', language, 'state', 'lineage', '--path', 'ancien.py', '--json']))
        assert result['matches'] == 1 and result['omitted'] == 0
        item = result['items'][0]
        assert (item['from'], item['to'], item['commit']) == ('ancien.py', 'déplacé.py', tip)
        assert item['epistemic_status'] == 'INFERRED'
        source = next(json.loads(line) for line in stable.splitlines() if json.loads(line)['event_id'] == item['event_id'])
        assert source['event_hash'] == item['event_hash']
        assert all(edge['epistemic_status'] == 'INFERRED' for edge in source['relations'])
        text = run([dw, '--language', language, 'state', 'lineage', '--path', 'ancien.py'])
        assert '[INFERRED]' in text and 'ancien.py' in text and 'déplacé.py' in text
        assert ('Filiation du fichier' if language == 'fr' else 'File lineage') in text
    assert events.read_bytes() == stable and (repo / '.git/index').read_bytes() == before
    assert all(private not in stable for private in (b'PRIVATE_SOURCE', b'PRIVATE_MESSAGE', b'private@example.invalid'))
    print(json.dumps({'schema':'installed-git-lineage-1', 'classification':'MACHINE', 'passed':True,
                      'exact_citations':True, 'languages':['fr','en'], 'hypothesis_authority':'INFERRED',
                      'raw_content_excluded':True, 'real_index_preserved':True}))
