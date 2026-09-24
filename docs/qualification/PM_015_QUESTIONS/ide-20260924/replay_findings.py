"""Replay the concrete failure scenario of every PR #128 review finding.

Each finding runs in its own disposable repository against the installed
DiffWitness package. MACHINE evidence only; not a HUMAN check.
"""
import json, os, subprocess, sys, tempfile, traceback
from pathlib import Path

CORE = Path(sys.argv[1])
sys.path.insert(0, str(CORE / 'tests'))
import test_continuity_kernel as fixtures
import diffwitness
from diffwitness.continuity_events import append_project_event, continuity_paths
from diffwitness.continuity_history import event_detail
from diffwitness.continuity_questions import answer_question

TS = '2026-09-20T12:00:00Z'


class Repo:
    def __init__(self, tmp):
        self.repo = fixtures.ContinuityKernelTests().repo(Path(tmp))
        self.paths = continuity_paths(self.repo)

    def rec(self, identity, label=None, *, kind='decision', payload=None, relations=None,
            timestamp=TS, event_type='decision.recorded'):
        subject = {'id': identity, 'kind': kind}
        if label is not None:
            subject['label'] = label
        return append_project_event(repo=self.repo, event_type=event_type, subject=subject,
            epistemic_status='DECLARED', payload=payload or {}, relations=relations or [],
            timestamp=timestamp, provenance={'producer': 'finding-replay', 'source': 'synthetic'},
            actor={'kind': 'fixture', 'id': 'finding-replay'})[0]

    def old_change(self, *paths):
        return self.rec('CHANGE-OLD', 'auth change', kind='change', event_type='change.observed',
                        timestamp='2025-09-21T08:00:00Z', payload={'changed_files': list(paths)})

    def comp(self, identity, label=None, payload=None, relations=None):
        return self.rec(identity, label, kind='component', event_type='component.observed',
                        payload=payload, relations=relations)

    def ask(self, question, **options):
        before = self.paths.events.read_bytes()
        result = answer_question(self.repo, question, **options)
        assert self.paths.events.read_bytes() == before, 'journal bytes changed'
        assert result['assurance'] == 'none' and result['actions'] == [] and result['questionStored'] is False
        for part in result['parts']:
            opened = event_detail(self.repo, part['source']['eventId'], expected_hash=part['source']['eventHash'])
            assert opened['event']['event_hash'] == part['source']['eventHash']
        return result


def edge(target_id, label=None):
    target = {'id': target_id, 'kind': 'component'}
    if label:
        target['label'] = label
    return {'predicate': 'depends_on', 'target': target, 'epistemic_status': 'INFERRED'}


def abstain(r, q, reason=None, **o):
    res = r.ask(q, **o)
    assert res['status'] == 'abstained' and res['parts'] == [], (q, o, res['status'], res['context'].get('abstention'))
    if reason:
        assert res['context']['abstention'] == reason, (q, o, res['context']['abstention'])
    return res['context']['abstention']


def cited(r, q, ids, field='id', **o):
    res = r.ask(q, **o)
    got = sorted(f['fields'][field] for f in res['context']['facts'])
    assert res['status'] == 'cited-records' and got == sorted(ids), (q, o, res['status'], res['context'].get('abstention'), got)
    return 'cited ' + ','.join(got)


def date_case(phrases, path_for, extra=()):
    def run(r):
        r.old_change(*[path_for(p) for p in phrases])
        out = []
        for p in phrases:
            for prefix in ('What changed in auth ', 'Quels changements dans auth '):
                for o in ({}, {'until': '2027-01-01'}, {'entity': 'CHANGE-OLD'}):
                    out.append(abstain(r, prefix + p + '?', 'ambiguous-time-filter', **o))
        for label in extra:
            r.rec('NAME-' + str(abs(hash(label)) % 10**8), label, payload={'why': 'Exact name reason'})
        return f'{len(out)} abstentions ambiguous-time-filter'
    return run


def cli(r, *args):
    return subprocess.run(['dw', 'ask', 'What changed in auth?', '--repo', str(r.repo), *args],
                          capture_output=True, encoding='utf-8', timeout=60)


def f1(r):
    r.comp('AUTH', 'auth'); r.comp('SRC', 'source', relations=[edge('AUTH')])
    return [abstain(r, q, 'dependency-direction-ambiguous') for q in ('auth depends on what?', 'de quoi auth dépend-il ?')]

def f2(r):
    r.rec('CHANGE-MORNING', 'auth change', kind='change', event_type='change.observed',
          timestamp='2026-09-21T08:00:00Z', payload={'changed_files': ['auth.py']})
    return [abstain(r, q, 'ambiguous-time-filter') for q in (
        'What changed in auth since 2026-09-21 12:00:00+00:00?', 'What changed in auth since 2026-09-21 at noon?')]

def f3(r):
    r.comp('AUTH', 'auth'); r.comp('SRC', 'source', relations=[edge('AUTH')])
    return abstain(r, 'What depends on auth and what does auth depend on?')

def f4(r):
    r.rec('CHANGE-AUTH', 'auth change', kind='change', event_type='change.observed',
          timestamp='2026-09-10T08:00:00Z', payload={'changed_files': ['auth.py']})
    return [abstain(r, 'What changed in auth since yesterday?', 'ambiguous-time-filter', until='2026-09-24'),
            abstain(r, 'What changed in auth before 2026-09-21?', 'ambiguous-time-filter', since='2026-09-01')]

def f5(r):
    r.rec('AUTH', 'auth', payload={'why': 'auth reason'})
    r.rec('CHANGE-BILLING', 'billing', kind='change', event_type='change.observed', payload={'changed_files': ['billing.py']})
    return [abstain(r, q, 'mixed-question-intents') for q in ('Why auth and what changed in billing?', 'What changed in billing and why auth?')]

def f6(r):
    r.old_change('auth/two/days/ago/service.py', 'auth.py')
    return [abstain(r, 'What changed in auth ' + p + '?', 'ambiguous-time-filter')
            for p in ('two days ago', 'this week', 'recently', 'as of Monday')]

def f7(r):
    run = cli(r, '--since', '9999-12-31T23:59:59-23:59')
    assert run.returncode == 2 and 'Traceback' not in run.stderr, (run.returncode, run.stderr[-500:])
    return 'exit 2, no traceback'

def f8(r):
    r.rec('AUTH', 'auth', payload={'why': 'auth reason'})
    return [abstain(r, q, 'ambiguous-time-filter') for q in ('Why auth recently?', 'Pourquoi auth récemment ?')]

def f9(r):
    r.old_change('auth/2026/service.py')
    return [abstain(r, 'What changed in auth from 2026?', 'ambiguous-time-filter', **o)
            for o in ({}, {'until': '2027-01-01'}, {'since': '2024-01-01'})]

def f10(r):
    r.comp('AUTH', 'auth service'); r.comp('PAY', 'payment service')
    r.comp('SRC-AUTH', 'a', relations=[edge('AUTH')]); r.comp('SRC-PAY', 'b', relations=[edge('PAY')])
    return cited(r, 'What depends on auth service?', ['SRC-AUTH'], field='from')

def f11(r):
    r.comp('SRC-A', 'a', relations=[edge('OPAQUE-TARGET', 'auth service')])
    r.comp('SRC-B', 'b', relations=[edge('OPAQUE-TARGET')])
    return cited(r, 'What depends on auth service?', ['SRC-A', 'SRC-B'], field='from')

def f12(r):
    r.comp('SOURCE-OLD', 'Source', payload={'lifecycle': 'inactive'}, relations=[edge('RAW-TARGET', 'auth service')])
    r.comp('SOURCE-LIVE', 'Source', relations=[edge('RAW-TARGET')])
    return abstain(r, 'What depends on auth service?', 'insufficient-cited-records')

def f13(r):
    r.old_change('auth/2026/service.py', 'auth/q1/2026/service.py')
    return abstain(r, 'What changed in auth in Q1 2026?', 'ambiguous-time-filter')

def f14(r):
    r.rec('CSHARP', 'C# runtime', payload={'why': 'C# reason'})
    return abstain(r, 'Why C++?')

def f15(r):
    r.old_change('auth/fy2026/service.py', 'auth/2026q1/service.py')
    return [abstain(r, 'What changed in auth in ' + p + '?', 'ambiguous-time-filter') for p in ('FY2026', '2026Q1')]

def f16(r):
    r.rec('AUTH-IMPORT', 'auth import', payload={'why': 'import reason'})
    return abstain(r, 'What does auth import?')

def f17(r):
    r.old_change('auth/at/12/30/service.py', 'auth/at/3pm/service.py', 'auth/at/12/pm/service.py')
    return [abstain(r, 'What changed in auth at ' + p + '?', 'ambiguous-time-filter') for p in ('12:30', '3pm', '12 PM')]

def f18(r):
    r.old_change('auth/at/three/pm/service.py')
    return abstain(r, 'What changed in auth at three PM?', 'ambiguous-time-filter')

def f19(r):
    r.old_change('auth/this/weekend/service.py', 'auth/this/summer/service.py', 'auth/this/spring/service.py')
    return [abstain(r, 'What changed in auth this ' + p + '?', 'ambiguous-time-filter') for p in ('weekend', 'summer', 'spring')]

def f20(r):
    r.rec('CM', 'change management', payload={'why': 'Reason'})
    return [cited(r, 'Why change management?', ['CM']), cited(r, 'change management', ['CM'], kind='memory')]

def f21(r):
    r.rec('ISO', 'ISO27001', payload={'why': 'Reason'})
    return cited(r, 'Why ISO27001?', ['ISO'])

def f22(r):
    r.rec('RISK', 'risk and memory management', payload={'why': 'Reason'})
    return cited(r, 'Why risk and memory management?', ['RISK'])

def f23(r):
    r.rec('PY', 'Python 3.14', payload={'why': 'Reason'})
    return cited(r, 'Why Python 3.14?', ['PY'])

def f24(r):
    r.rec('REL', 'release-2026-09-21', payload={'why': 'Reason'})
    return cited(r, 'Why release-2026-09-21?', ['REL'])

def f25(r):
    r.old_change('auth/on/2026/09/service.py')
    return abstain(r, 'What changed in auth on 2026-09?', 'ambiguous-time-filter')

def f26(r):
    r.comp('IMP', 'import management'); r.comp('SRC', 'source', relations=[edge('IMP')])
    return [cited(r, 'What depends on import management?', ['SRC'], field='from'),
            cited(r, 'What depends on import management?', ['SRC'], field='from', entity='IMP')]

def f27(r):
    r.rec('AUTH', 'auth billing', payload={'why': 'Reason'})
    return [abstain(r, 'Why auth. Why billing?', entity='AUTH'), abstain(r, 'Why auth and why billing?')]

def f28(r):
    r.rec('CHANGE-AUTH', 'auth change', kind='change', event_type='change.observed', payload={'changed_files': ['auth.py']})
    runs = [cli(r, flag, '') for flag in ('--since', '--until')]
    assert all(x.returncode == 2 and 'Traceback' not in x.stderr for x in runs), [(x.returncode, x.stderr[-300:]) for x in runs]
    return 'exit 2 for empty --since/--until'

def f29(r):
    r.rec('CHANGE-AUTH', 'auth change', kind='change', event_type='change.observed', payload={'changed_files': ['auth.py']})
    return [abstain(r, 'What changed in auth ' + p + '?', 'ambiguous-time-filter', entity='CHANGE-AUTH')
            for p in ('lately', 'so far', 'to date')]

def f30(r):
    r.rec('AUTH', 'auth billing what changed in', payload={'why': 'Reason'})
    return [abstain(r, q, entity='AUTH') for q in ('Why auth: why billing?', 'Why auth: what changed in billing?')]

def f31(r):
    r.rec('AUTH', 'auth and remember billing', payload={'why': 'Reason'})
    return abstain(r, 'Why auth and remember billing?')

def f32(r):
    r.comp('CAR', 'car service'); r.comp('SRC', 'source', relations=[edge('CAR')])
    return cited(r, 'What depends on car service?', ['SRC'], field='from')

def f33(r):
    r.rec('RFC', 'RFC 9110', payload={'why': 'Reason'})
    return cited(r, 'Why RFC 9110?', ['RFC'])

def f34(r):
    r.rec('AUTH', 'auth and please remember billing', payload={'why': 'Reason'})
    return abstain(r, 'Why auth and please remember billing?')

def f38(r):
    r.rec('AUTH', 'auth why billing', payload={'why': 'Reason'})
    return abstain(r, 'Why auth.Why billing?')

def f39(r):
    r.rec('DEC', 'auth qu est ce qui a changé dans billing', payload={'why': 'Reason'})
    return abstain(r, 'Pourquoi auth.Qu’est-ce qui a changé dans billing ?', entity='DEC')

def f45(r):
    r.rec('AUTH', 'auth what changed in billing', payload={'why': 'Reason'})
    return [abstain(r, q) for q in ('Why auth — what changed in billing?', 'Why auth – what changed in billing?')]

def f46(r):
    r.rec('PLAN', 'plan 9 et migration', payload={'why': 'Reason'})
    r.rec('TYPO', '12 pt typography', payload={'why': 'Reason'})
    return [cited(r, 'Pourquoi plan 9 et migration ?', ['PLAN']), cited(r, 'Why 12 pt typography?', ['TYPO'])]

def f49(r):
    r.rec('PLAN', 'plan 12 est stable', payload={'why': 'Reason'})
    return cited(r, 'Pourquoi plan 12 est stable ?', ['PLAN'])

def f50(r):
    r.comp('DW', 'Doctor Who service'); r.comp('SRC', 'source', relations=[edge('DW')])
    return cited(r, 'What depends on Doctor Who service?', ['SRC'], field='from')

def f51(r):
    r.rec('DEC', 'auth what changed in billing', payload={'why': 'Reason'})
    return abstain(r, 'Why auth & what changed in billing?', entity='DEC')

def f52(r):
    r.rec('AUTH', 'auth what changed in billing', payload={'why': 'Reason'})
    return abstain(r, 'Why auth / what changed in billing?')

def f53(r):
    r.comp('YAHOO', 'Yahoo! service'); r.comp('SRC', 'source', relations=[edge('YAHOO')])
    return [cited(r, 'What depends on Yahoo! service?', ['SRC'], field='from'),
            cited(r, 'What depends on Yahoo! service?', ['SRC'], field='from', entity='YAHOO')]

def f55(r):
    out = date_case(('Sep-21', '21-Sep-2026', 'Sep/21/2026'), lambda p: 'auth/' + p.replace('-', '/') + '/service.py')(r)
    r.rec('SDK', 'sept-sdk', payload={'why': 'Reason'})
    return [out, cited(r, 'Why sept-sdk?', ['SDK'])]

def f56(r):
    r.rec('DEC', 'auth what changed in billing', payload={'why': 'Reason'})
    return abstain(r, 'Why auth (what changed in billing)?', entity='DEC')

def f57(r):
    r.rec('DEC', 'auth please tell me what changed in billing', payload={'why': 'Reason'})
    return abstain(r, 'Why auth (please tell me what changed in billing)?', entity='DEC')


def f61(r):
    out = []
    for index, label in enumerate(('release‐2026‐09‐21', 'release‐09‐21')):
        r.rec('REL%d' % index, label, payload={'why': 'Reason'})
        out.append(cited(r, 'Why ' + label + '?', ['REL%d' % index], entity='REL%d' % index))
    return out


def f65(r):
    r.rec('ID65', '12h30Z-service', payload={'why': 'Reason'})
    return cited(r, 'Why 12h30Z-service?', ['ID65'], entity='ID65')


def f68(r):
    r.rec('ID68', '12z compression', payload={'why': 'Reason'})
    return cited(r, 'Why 12z compression?', ['ID68'])


split = lambda p: 'auth/' + p.replace('-', '/').replace('.', '/').replace(' ', '/') + '/service.py'
FINDINGS = {
    1: (4088785920, f1), 2: (4088785929, f2), 3: (4088833583, f3), 4: (4088833589, f4),
    5: (4088878860, f5), 6: (4088878864, f6), 7: (4088878867, f7), 8: (4088930520, f8),
    9: (4088979861, f9), 10: (4088979869, f10), 11: (4089040597, f11), 12: (4089081719, f12),
    13: (4089181415, f13), 14: (4089288605, f14), 15: (4089288609, f15), 16: (4089335578, f16),
    17: (4089335580, f17), 18: (4089390630, f18), 19: (4089471249, f19), 20: (4089587924, f20),
    21: (4089587933, f21), 22: (4089734559, f22), 23: (4089734563, f23), 24: (4089734565, f24),
    25: (4089850123, f25), 26: (4089850128, f26), 27: (4089873151, f27), 28: (4089873155, f28),
    29: (4089948783, f29), 30: (4089948792, f30), 31: (4090002819, f31), 32: (4090002822, f32),
    33: (4090002828, f33), 34: (4090063735, f34),
    35: (4090127468, date_case(('09-21-2026', '21-09-2026'), split)),
    36: (4090127475, date_case(('Sept 21',), split)),
    37: (4090127481, date_case(('12 EST', '12 PST'), split)),
    38: (4090127489, f38), 39: (4090220923, f39),
    40: (4090220930, date_case(('Sep 21st',), split)),
    41: (4090220934, date_case(('2026-9-21',), split)),
    42: (4090301777, date_case(('21.09.2026',), split)),
    43: (4090360930, date_case(('2026-W39-4',), split)),
    44: (4090360937, date_case(('12 ET',), split)),
    45: (4090360945, f45), 46: (4090442851, f46),
    47: (4090514176, date_case(('21.09.26', '09.21.26'), split)),
    48: (4091207915, date_case(('Sep',), split)),
    49: (4091207921, f49), 50: (4091207928, f50), 51: (4091207932, f51), 52: (4091385402, f52),
    53: (4091385410, f53),
    54: (4091527848, date_case(('2026-264', '2026264'), lambda p: 'auth/2026/264/service.py')),
    55: (4091691319, f55), 56: (4091691327, f56), 57: (4092623217, f57),
    58: (4092727135, date_case(('09-21',), split)),
    59: (4092842170, date_case(('09 / 21',), lambda p: 'auth/09/21/service.py')),
    60: (4093864173, date_case(('Sep-21T120000Z', '21-SepT120000Z'), lambda p: 'auth/sep/21t120000z/service.py')),
    61: (4093864180, f61),
    62: (4094207977, date_case(('12 EET', '12 EEST', '12 WET', '12 WEST'), split)),
    63: (4094642025, date_case(('12 AHST', '12 AHDT', '12 HKST', '12 YST', '12 YDT'), split)),
    64: (4095024653, date_case(('12h30Z',), lambda p: 'auth/12h30z/service.py')),
    65: (4095330252, f65),
    66: (4095630671, date_case(('12 hrs-service',), lambda p: 'auth/12/hrs/service.py')),
    67: (4095927154, date_case(('12 EST5EDT', '12 PST8PDT'), split)),
    68: (4095927165, f68),
    69: (4096333942, date_case(('12 US/Eastern',), lambda p: 'auth/12/us/eastern/service.py')),
    70: (4096627454, date_case(('12 NZ-CHAT', '12 W-SU'), lambda p: 'auth/12/nz/chat/w/su/service.py')),
}

SELECTED = {int(x) for x in sys.argv[2].split(',')} if len(sys.argv) > 2 else set(FINDINGS)
results = []
for number, (comment_id, scenario) in FINDINGS.items():
    if number not in SELECTED:
        continue
    with tempfile.TemporaryDirectory() as tmp:
        try:
            detail = scenario(Repo(tmp)); ok = True
        except Exception:
            detail = traceback.format_exc(limit=3); ok = False
    results.append({'finding': number, 'comment': comment_id, 'pass': ok, 'detail': detail})
    print(number, comment_id, 'PASS' if ok else 'FAIL', detail if ok else detail.strip().splitlines()[-1], flush=True)
print(json.dumps({'schema': 'pr128-finding-replay-1', 'classification': 'MACHINE', 'human_executed': False,
                  'package': diffwitness.__file__, 'total': len(results),
                  'passed': sum(r['pass'] for r in results), 'results': results}, ensure_ascii=False))
