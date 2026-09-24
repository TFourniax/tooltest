"""Actual installed CLI -> Git -> public Gate -> immutable impact comparison."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


def main():
    executable=shutil.which('dw')
    if not executable:
        raise RuntimeError('actual installed dw is required')
    with tempfile.TemporaryDirectory(prefix='dw-impact-acceptance-') as temporary:
        repo=Path(temporary)
        def run(*args):
            proc=subprocess.run(list(args),cwd=repo,capture_output=True,encoding='utf-8',timeout=90)
            if proc.returncode:
                raise RuntimeError(proc.stdout+'\n'+proc.stderr)
            return proc.stdout
        run('git','init','-q');run('git','config','user.email','impact@example.test');run('git','config','user.name','Impact Fixture')
        (repo/'app.py').write_text('def add(a,b):\n    return a-b\n',encoding='utf-8')
        (repo/'tests').mkdir();(repo/'tests/test_app.py').write_text('import unittest\nfrom app import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2,3),5)\n',encoding='utf-8')
        run('git','add','.');run('git','commit','-qm','baseline');base=run('git','rev-parse','HEAD').strip()
        run(executable,'task','add','Review anticipated scope','--id','TASK-IMPACT','--json')
        plan=json.loads(run(executable,'task','impact','anticipate','TASK-IMPACT','--file','app.py','--file','untouched.py','--unknown','Semantic effects require separate evidence','--json'))['event']
        # Ask the installed package for its existing journal location.
        from diffwitness.continuity_events import continuity_paths, read_project_events
        journal=continuity_paths(repo).events;planned_bytes=journal.read_bytes()
        index_before=run('git','ls-files','--stage')
        (repo/'app.py').write_text('def add(a,b):\n    return a+b\n',encoding='utf-8')
        (repo/'README.md').write_text('Unexpected documentation touch.\n',encoding='utf-8')
        run('git','add','.');run('git','commit','-qm','fix and document')
        command=[sys.executable,'-m','unittest','discover','-s','tests']
        evidence=subprocess.list2cmdline(command) if os.name=='nt' else shlex.join(command)
        gate=run(executable,'gate','--base',base,'--candidate','HEAD','--test',evidence,'--max-total-seconds','60')
        events=read_project_events(journal)
        change=[e for e in events if e['event_type']=='change.observed'][-1]
        proof=[e for e in events if e['event_type']=='proof.completed'][-1]
        assert proof['epistemic_status']=='VERIFIED' and proof['payload']['accepted'] is True, gate
        comparison=json.loads(run(executable,'task','impact','compare',plan['subject']['id'],change['subject']['id'],'--json'))['event']
        d=comparison['payload']['delta']
        assert d['planned_observed']==['app.py'] and d['outside_plan']==['README.md'] and d['not_observed']==['untouched.py']
        assert d['correctness']=='unknown' and d['causal_proof'] is False and comparison['epistemic_status']=='OBSERVED'
        assert journal.read_bytes().startswith(planned_bytes)
        before=journal.read_bytes();indexes=run('git','ls-files','--stage');views=[]
        for lang in ('fr','en'):
            run(executable,'--language',lang,'task','impact','show',change['subject']['id'])
            views.append(json.loads(run(executable,'--language',lang,'task','impact','show','TASK-IMPACT','--json')))
        assert views[0]==views[1] and views[0]['plans']==[plan] and views[0]['comparisons']==[comparison]
        assert before==journal.read_bytes() and indexes==run('git','ls-files','--stage')
        assert index_before!=indexes  # The fixture really committed a changed source.
        print(json.dumps({'schema':'impact-plan-acceptance-1','classification':'MACHINE','passed':True,
                          'base_commit':base,'base_tree':plan['payload']['base_tree'],'change_id':change['subject']['id'],
                          'plan_event':plan['event_id'],'comparison_event':comparison['event_id'],
                          'public_proof_event':proof['event_id'],'journal_sha256':hashlib.sha256(before).hexdigest(),
                          'human_executed':False}))

if __name__=='__main__':
    main()
