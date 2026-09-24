import sys,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/tests')
import test_continuity_kernel as fixtures
from diffwitness.continuity_events import append_project_event
from diffwitness.continuity_questions import answer_question
import re
forms=['1200Z','0930Z','12:00Z','12:00EST','1200EST','1200 EST','3pmEST','3PMEST','12:00+03','1200+03','12:30:00EET','T1200Z','12hEET','noonEST','12 h 30 EET','1200 hours','1200hrs','12.30 EET','12.30pm']
with tempfile.TemporaryDirectory() as tmp:
    repo=fixtures.ContinuityKernelTests().repo(Path(tmp))
    paths=['auth/'+'/'.join(re.findall(r'[^\W_]+',f.lower()))+'/service.py' for f in forms]
    append_project_event(repo=repo,event_type='change.observed',subject={'id':'OLD','kind':'change','label':'auth change'},
        epistemic_status='DECLARED',payload={'changed_files':paths},relations=[],timestamp='2025-09-21T08:00:00Z',
        provenance={'producer':'p','source':'s'},actor={'kind':'fixture','id':'f'})
    for f in forms:
        r=answer_question(repo,'What changed in auth '+f+'?')
        print(f'{f!r:16} {r["status"]:15} {r["context"].get("abstention")}')
