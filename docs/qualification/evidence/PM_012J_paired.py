"""Fixed installed-package comparison; all 18 outcomes retained, no retries."""
import hashlib,json,os,platform,subprocess,sys
from pathlib import Path
root=Path('/workspace/scratch/e341555d0f23')
out=root/'qualification'
script=Path('/workspace/scratch/fa8b5862d36a/work/core/scripts/continuity_bench.py')
assert script.read_bytes()==Path('/workspace/scratch/fa8b5862d36a/core-scale-final/scripts/continuity_bench.py').read_bytes()
rows=[]
manifest={'classification':'MACHINE','qualification':False,'note':'Fixed installed-wheel observations on a shared Linux host; unchanged workload and thresholds; no retries; not a 100k PASS unless every required budget passes.','base':'e2e3f578d04d58f55901963e645c4bd14efbc6f3','python':sys.version,'platform':platform.platform(),'benchmark_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),'samples':rows}
for count in (10000,50000,100000):
 for pair in range(1,4):
  order=('baseline','candidate') if pair%2 else ('candidate','baseline')
  for source in order:
   outfile=out/f'paired-{count}-{pair}-{source}.json'
   command=[str(root/(source+'-env')/'bin/python'),str(script),'--events',str(count),'--context-runs','7','--json',str(outfile)]
   env=dict(os.environ);env.pop('PYTHONPATH',None)
   with outfile.with_suffix('.log').open('w') as stream:
    p=subprocess.run(command,cwd=out,env=env,stdout=stream,stderr=subprocess.STDOUT)
   result=json.loads(outfile.read_text()) if outfile.exists() else None
   rows.append({'events':count,'pair':pair,'source':source,'exitCode':p.returncode,'result':result})
   (out/'paired-results.json').write_text(json.dumps(manifest,indent=2)+'\n')
   print(json.dumps({'events':count,'pair':pair,'source':source,'exitCode':p.returncode,'result':result}),flush=True)
