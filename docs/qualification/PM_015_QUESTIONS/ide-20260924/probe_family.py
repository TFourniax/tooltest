import sys,tempfile,re
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/tests')
import test_continuity_kernel as fixtures
from diffwitness.continuity_events import append_project_event
from diffwitness.continuity_questions import answer_question
neg=['12 EST5EDT','12:00 EST5EDT','12 UTC+3','12 GMT-5','12 UTC−5','12 Z','12:00 Z','1200 Z','12:00:00.123Z','12:00:00,5Z','12:00 utc','12 h EET','noon Z','3 pm Z','12h30 Z','12.30.00 EET','12 EST5','9 UTC0']
pos=['12z','v12Z','3PMZ-build','EST5EDT migration','12 PT100 probe','60hz filter','1.2+34 build','Python 3.14','12 pt typography']
with tempfile.TemporaryDirectory() as tmp:
    repo=fixtures.ContinuityKernelTests().repo(Path(tmp))
    paths=['auth/'+'/'.join(re.findall(r'[^\W_]+',f.lower()))+'/service.py' for f in neg]
    append_project_event(repo=repo,event_type='change.observed',subject={'id':'OLD','kind':'change','label':'auth change'},
        epistemic_status='DECLARED',payload={'changed_files':paths},relations=[],timestamp='2025-09-21T08:00:00Z',
        provenance={'producer':'p','source':'s'},actor={'kind':'fixture','id':'f'})
    for f in neg:
        r=answer_question(repo,'What changed in auth '+f+'?')
        print('NEG' ,'ok ' if r['status']=='abstained' else 'GAP', repr(f), r['status'], r['context'].get('abstention'))
    for i,f in enumerate(pos):
        append_project_event(repo=repo,event_type='decision.recorded',subject={'id':'P%d'%i,'kind':'decision','label':f},
            epistemic_status='DECLARED',payload={'why':'r'},relations=[],timestamp='2026-09-20T12:00:00Z',
            provenance={'producer':'p','source':'s'},actor={'kind':'fixture','id':'f'})
        r=answer_question(repo,'Why '+f+'?',entity='P%d'%i)
        print('POS','ok ' if r['status']=='cited-records' else 'GAP', repr(f), r['status'], r['context'].get('abstention'))
