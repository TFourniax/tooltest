"""Installed artifact language contract; no provider runtime replay is needed."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dw',type=Path)
    parser.add_argument('--idleproof',type=Path)
    args=parser.parse_args()
    dw=(args.dw or Path(shutil.which('dw') or '')).resolve()
    assert dw.is_file()
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','DIFFWITNESS_BIN','DIFFWITNESS_VIEW'}}
    env.update(LANG='fr_FR.UTF-8',LC_ALL='fr_FR.UTF-8',LANGUAGE='fr_FR:fr',PYTHONUTF8='1')
    with tempfile.TemporaryDirectory(prefix='dw-language-') as td:
        repo=Path(td).resolve()
        subprocess.run(['git','init','-q',str(repo)],check=True,env=env)
        (repo/'app.py').write_bytes(b'value = 1\n')
        subprocess.run(['git','-C',str(repo),'add','app.py'],check=True,env=env)
        index=(repo/'.git/index').read_bytes();head=(repo/'.git/HEAD').read_bytes()
        def run(*args):
            p=subprocess.run([str(dw),*args],cwd=repo,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
            assert p.returncode in (0,1),(args,p.returncode,p.stdout,p.stderr)
            return p.returncode,p.stdout
        _,default=run('status')
        assert 'One configuration step remains' in default,default
        assert not (repo/'.git/diffwitness/ui-preferences.json').exists()
        setup=['setup','install','--agent','codex']
        if args.idleproof:setup += ['--idleproof-command',str(args.idleproof.resolve())]
        _,installed=run(*setup)
        assert 'configured for DiffWitness' in installed,installed
        hooks=(repo/'.codex/hooks.json').read_bytes()
        expected={'status':('Project state','État du projet'),'doctor':('GUIDED CHECK-UP','CHECK-UP GUIDÉ'),
                  'setup status':('Verification still','Vérification encore')}
        for command,(en,fr) in expected.items():
            words=command.split()
            rc,a=run('--language','en',*words);rc2,b=run('--language','fr',*words)
            assert rc==rc2 and en in a and fr in b,(command,a,b)
            _,a=run('--language','en',*words,'--json');_,b=run('--language','fr',*words,'--json')
            assert json.loads(a)==json.loads(b),(command,a,b)
        run('language','fr')
        assert 'État du projet' in run('status')[1]
        run('view','technical')
        assert 'VUE TECHNIQUE' in run('status')[1]
        assert 'TECHNICAL VIEW' in run('--language','en','status')[1]
        assert 'VUE TECHNIQUE' in run('status')[1]
        run('language','en');run('view','guided')
        assert 'Project state' in run('status')[1]
        assert (repo/'.codex/hooks.json').read_bytes()==hooks
        assert (repo/'.git/index').read_bytes()==index
        assert (repo/'.git/HEAD').read_bytes()==head
        assert not (repo/'.claude').exists()
        assert not list((repo/'.git').rglob('*envelope*.json'))
        print('LANGUAGE ACCEPTANCE PASS: French locale -> English; explicit French; persistent/one-off precedence; Guided/Technical; JSON identical; hooks/index/HEAD unchanged',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
