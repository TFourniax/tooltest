"""List every abbreviation stored in the TZif files of the installed tzdata package."""
import json, struct, sys
from importlib import resources
import tzdata

def abbreviations(data):
    assert data[:4] == b'TZif', 'not TZif'
    version = data[4:5]
    def counts(off):
        return struct.unpack('>6l', data[off + 20: off + 44])
    isut, isstd, leap, timecnt, typecnt, charcnt = counts(0)
    off = 44
    v1 = timecnt * 4 + timecnt + typecnt * 6 + charcnt + leap * 8 + isstd + isut
    chars_v1 = data[off + timecnt * 5 + typecnt * 6: off + timecnt * 5 + typecnt * 6 + charcnt]
    found = set(x.decode('ascii') for x in chars_v1.split(b'\0') if x)
    if version >= b'2':
        off2 = off + v1
        isut, isstd, leap, timecnt, typecnt, charcnt = counts(off2)
        start = off2 + 44 + timecnt * 9 + typecnt * 6
        found |= set(x.decode('ascii') for x in data[start:start + charcnt].split(b'\0') if x)
    return found

root = resources.files('tzdata') / 'zoneinfo'
seen, files = set(), 0
def walk(node):
    global files
    for child in node.iterdir():
        if child.is_dir():
            walk(child)
        else:
            raw = child.read_bytes()
            if raw[:4] == b'TZif':
                files += 1
                seen.update(abbreviations(raw))
walk(root)
alpha = sorted(a for a in seen if a.isalpha())
numeric = sorted(a for a in seen if not a.isalpha())
print(json.dumps({'tzdata': tzdata.IANA_VERSION, 'package': tzdata.__version__, 'files': files,
                  'alphabetic': alpha, 'non_alphabetic_sample': numeric[:12], 'non_alphabetic_count': len(numeric)}))
