import sys,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/tests')
import test_continuity_kernel as fixtures
from diffwitness.continuity_events import append_project_event
from diffwitness.continuity_questions import answer_question
with tempfile.TemporaryDirectory() as tmp:
    repo=fixtures.ContinuityKernelTests().repo(Path(tmp))
    for i,label in enumerate(['12EST-service','12h30Z-service','1200EST-api']):
        append_project_event(repo=repo,event_type='decision.recorded',subject={'id':'X%d'%i,'kind':'decision','label':label},
            epistemic_status='DECLARED',payload={'why':'r'},relations=[],timestamp='2026-09-20T12:00:00Z',
            provenance={'producer':'p','source':'s'},actor={'kind':'fixture','id':'f'})
        r=answer_question(repo,'Why '+label+'?',entity='X%d'%i)
        print(label,r['status'],r['context'].get('abstention'))
