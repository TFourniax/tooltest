import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import types

from diffwitness.continuity_state import _schema
from diffwitness import structure_provider

repo = Path(sys.argv[1]).resolve()
baseline = 'e882f7cb34aad4217250196c4c948b7b08297c8f'
source = subprocess.check_output(['git','show',baseline+':src/diffwitness/structure_provider.py'],cwd=repo).decode('utf-8')
legacy = types.ModuleType('diffwitness._baseline_structure_provider')
legacy.__package__ = 'diffwitness'
exec(compile(source, '<pre-refactor-provider>', 'exec'), legacy.__dict__)
projections = []
for provider in (legacy, structure_provider):
    conn = sqlite3.connect(':memory:')
    try:
        _schema(conn)
        summary = provider.refresh_structure_index(repo, conn=conn)
        tables = {}
        for table in ('structure_components','structure_symbols','structure_edges'):
            columns = [row[1] for row in conn.execute('pragma table_info('+table+')') if row[1] != 'indexed_at']
            tables[table] = conn.execute('select '+','.join(columns)+' from '+table+' order by '+columns[0]).fetchall()
        projections.append(tables)
    finally:
        conn.close()
assert projections[0] == projections[1], 'provider refactor changed stable structural facts'
print(json.dumps({'schema':'structure-provider-equivalence-1','baseline':baseline,'tree':summary['tree'],
                  'counts':{key:len(rows) for key,rows in projections[1].items()},'matched':True,
                  'sha256':hashlib.sha256(json.dumps(projections[1],sort_keys=True).encode()).hexdigest()}))
