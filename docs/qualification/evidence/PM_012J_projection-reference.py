import contextlib,hashlib,importlib.util,json,sqlite3,sys,tempfile
from pathlib import Path
repo=Path('/workspace/scratch/fa8b5862d36a/core-scale-final')
sys.path.insert(0,str(repo/'tests'))
from test_continuity_projection_batches import declaration,tables
import test_continuity_kernel as fixtures
from diffwitness import continuity_events as journal,continuity_state as current
from diffwitness.continuity_lifecycle import lifecycle_spec
reference=Path('/workspace/scratch/fa8b5862d36a/work/core/src/diffwitness/continuity_state.py')
assert hashlib.sha256(reference.read_bytes()).hexdigest() == '03639d94030b04a4501a761fac0b217554e9766d8f016dd7b4483af4d30981c9'
spec=importlib.util.spec_from_file_location('diffwitness._baseline_state',reference)
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
with tempfile.TemporaryDirectory() as td:
 project=fixtures.ContinuityKernelTests().repo(Path(td))
 specs=[declaration(i) for i in range(2052)]
 for start in range(0,len(specs),2048): journal.append_project_events(repo=project,events=specs[start:start+2048])
 journal.append_project_events(repo=project,events=[lifecycle_spec(project,'objective','OBJ-0','retire','Historical'),dict(event_type='objective.declared',subject={'id':'OBJ-LEGACY','kind':'objective','label':'Older observed'},epistemic_status='OBSERVED',payload={'why':'Historical'}),{**declaration(2052),'subject':{'id':'OBJ-LEGACY','kind':'objective','label':None}}])
 paths=journal.continuity_paths(project);data=paths.events.read_bytes();events=journal.read_project_events(paths.events)
 with contextlib.closing(sqlite3.connect(':memory:')) as a,contextlib.closing(sqlite3.connect(':memory:')) as b:
  a.row_factory=b.row_factory=sqlite3.Row
  baseline._schema(a);current._schema(b,indexes=False)
  for index,event in enumerate(events,1):baseline._project_event(a,index,event)
  current._project_history(b,events);current._indexes(b)
  expected=tables(a);actual=tables(b)
  assert actual==expected
  assert paths.events.read_bytes()==data
  print(json.dumps({'base':'e2e3f578d04d58f55901963e645c4bd14efbc6f3','baseline_module_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),'events':len(events),'all_tables_equal':True,'rows_by_table':{k:len(v) for k,v in actual.items()},'journal_unchanged':True,'classification':'MACHINE'},indent=2))
