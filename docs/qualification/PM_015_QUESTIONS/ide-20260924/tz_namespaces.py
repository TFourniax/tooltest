import json
from importlib import resources
import tzdata
root = resources.files('tzdata') / 'zoneinfo'
namespaces, single, ids = set(), [], []
for child in root.iterdir():
    if child.is_dir():
        namespaces.add(child.name)
        stack=[(child, child.name)]
        while stack:
            node, prefix = stack.pop()
            for c in node.iterdir():
                if c.is_dir(): stack.append((c, prefix+'/'+c.name))
                elif c.read_bytes()[:4]==b'TZif': ids.append(prefix+'/'+c.name)
    elif child.read_bytes()[:4] == b'TZif':
        single.append(child.name)
print(json.dumps({'tzdata': tzdata.IANA_VERSION, 'namespaces': sorted(namespaces), 'namespaced_ids': len(ids),
                  'id_chars': sorted(set(''.join(ids))), 'max_depth': max(i.count('/') for i in ids),
                  'single': sorted(single)}))
