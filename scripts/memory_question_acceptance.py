"""Actual installed CLI: declarations -> questions -> original citations -> abstention."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from diffwitness.continuity_events import continuity_paths
from diffwitness.runtime_executable import resolve_dw_command


def main():
    dw=resolve_dw_command()
    with tempfile.TemporaryDirectory(prefix='dw-question-acceptance-') as temporary:
        repo=Path(temporary)
        def run(*args, expected=0):
            r=subprocess.run(args,cwd=repo,encoding='utf-8',capture_output=True,timeout=30)
            assert r.returncode==expected, r.stderr
            return r.stdout
        run('git','init','-q');run('git','config','user.name','Question Fixture');run('git','config','user.email','question@example.test')
        run('git','-c','commit.gpgsign=false','commit','--allow-empty','-qm','baseline')
        run(dw,'decision','record','Authentification auth','--id','DEC-AUTH','--why','Réduire les accès non autorisés')
        run(dw,'objective','add','Contrôle auth','--id','OBJ-AUTH','--why','Garder une frontière explicite')
        run(dw,'relation','add','OBJ-AUTH','depends_on','DEC-AUTH')
        paths=continuity_paths(repo);before={p:p.read_bytes() for p in (paths.events,paths.state) if p.exists()}
        cases=[]
        for question in ['Why auth?','Pourquoi auth ?','What depends on auth?','Qu’est-ce qui dépend de auth ?',
                         'Why unrecorded_lunar_module?','What changed in auth since yesterday?',
                         'auth depends on what?', 'de quoi auth dépend-il ?',
                         'What changed in auth since 2026-09-21T12:00:00Z?',
                         'Qu’est-ce qui a changé dans auth depuis 2026-09-21 à midi ?']:
            values=[]
            for lang in ('fr','en'):
                value=json.loads(run(dw,'--language',lang,'ask',question,'--json'));values.append(value)
                for part in value['parts']:
                    source=part['source']
                    opened=json.loads(run(dw,'state','event',source['eventId'],'--hash',source['eventHash'],'--json'))
                    assert opened['event']['event_hash']==source['eventHash']
                assert value['assurance']=='none' and value['actions']==[] and value['questionStored'] is False
                readable=run(dw,'--language',lang,'ask',question)
                assert ('Mémoire' if lang=='fr' else 'Recorded') in readable
            assert values[0]==values[1]
            ambiguous_direction=question in ('auth depends on what?', 'de quoi auth dépend-il ?')
            ambiguous_time='yesterday' in question or '2026-09-21' in question
            expected='abstained' if 'unrecorded_' in question or ambiguous_direction or ambiguous_time else 'cited-records'
            assert values[0]['status']==expected
            if ambiguous_direction:assert values[0]['context']['abstention']=='dependency-direction-ambiguous'
            if ambiguous_time:assert values[0]['context']['abstention']=='ambiguous-time-filter'
            cases.append({'question':question,'status':expected,'citations':len(values[0]['parts'])})
        assert all(p.read_bytes()==b for p,b in before.items())
        run(dw,'decision','retire','DEC-AUTH','--reason','Historic only')
        retired=json.loads(run(dw,'ask','Why?','--entity','DEC-AUTH','--json'));assert retired['status']=='abstained'
        print(json.dumps({'schema':'memory-question-acceptance-1','classification':'MACHINE','human_executed':False,
                          'passed':True,'cases':cases,'journal_before_sha256':hashlib.sha256(before[paths.events]).hexdigest()}))


if __name__=='__main__':main()
