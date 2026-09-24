"""Actual installed CLI: declarations -> questions -> original citations -> abstention."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from diffwitness.continuity_events import append_project_event, continuity_paths
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
        run(dw,'decision','record','Authentification auth service','--id','DEC-AUTH','--why','Réduire les accès non autorisés')
        run(dw,'objective','add','Contrôle auth','--id','OBJ-AUTH','--why','Garder une frontière explicite')
        run(dw,'relation','add','OBJ-AUTH','depends_on','DEC-AUTH')
        run(dw,'decision','record','Payment service','--id','DEC-PAY','--why','Keep payment records')
        run(dw,'objective','add','Checkout','--id','OBJ-PAY','--why','Keep payment scope')
        run(dw,'relation','add','OBJ-PAY','depends_on','DEC-PAY')
        for identity,label in [('DEC-LEX-X','lexical x v1'),('DEC-LEX-Y','lexical y v2'),
                               ('DEC-TOKYO','lexical 東京'),('DEC-OSAKA','lexical 大阪')]:
            run(dw,'decision','record',label,'--id',identity,'--why','Exact lexical fixture')
        for identity,label in [('DEC-TECH-CPP','C++ runtime'),('DEC-TECH-CSHARP','C# runtime'),
                               ('DEC-TECH-FSHARP','F# runtime'),('DEC-TECH-C','C runtime')]:
            run(dw,'decision','record',label,'--id',identity,'--why','Exact technology fixture')
        run(dw,'decision','record','fallback works import calls importe appelle',
            '--id','DEC-QUERY','--why','Explicit lexical record fixture')
        run(dw,'decision','record','Spring','--id','DEC-SPRING','--why','Compose the application')
        run(dw,'decision','record','clause and please do kindly could you remember memory mémoire billing et veuillez','--id','DEC-COMPOUND',
            '--why','Synthetic all-terms compound fixture')
        run(dw,'decision','record','adjacent why pourquoi billing what changed in remember please memory qu est ce qui que a changé dans dépend de appelle importe',
            '--id','DEC-ADJACENT','--why','Synthetic adjacent-question fixture')
        run(dw,'decision','record','dashed why pourquoi what changed in billing quels changements dans '
            'qu est ce qui a changé remember please memory','--id','DEC-DASH','--why','Synthetic dash-clause fixture')
        lexical_shapes=('lexicalshape-2026-09-21','lexicalshape-21.09.2026')
        for index,label in enumerate(lexical_shapes):
            run(dw,'decision','record',label,'--id','DEC-LEXICAL-'+str(index),'--why','Exact lexical-shape reason')
        intent_names=('change management','memory management','call management','dependency management',
                      'risk and memory retention','risque et mémoire retention',
                      'risk or change retention','risk and call retention',
                      'import management','imports management','depend management','depends management','car service')
        numeric_names=('ISO27001','ISO27002','CVE-2026-12345','RFC9110','v2026alpha',
                       'Python 3.14','Python 3.12','Node 24.1.0','Deno 2.3',
                       'release-2026-09-21','release-2026-09-22','build_2026-09-21','api/2026-09-21',
                       'dotted-21.09.2026','build_2026.9.21',
                       'plan 9 et migration','12 pt typography','12pt typeface','12 Pt lettering',
                       'RFC 9110','RFC 9111','RFC 2026','ISO 9001','IEEE 8023','IEC 61508',
                       'System.Memory','foo.memory.py')
        for index,label in enumerate(intent_names):
            identity='DEC-NAME-'+str(index);source_identity='OBJ-NAME-'+str(index)
            run(dw,'decision','record',label,'--id',identity,'--why','Original reason for '+label)
            run(dw,'objective','add','Source','--id',source_identity,'--why','Record dependency source')
            run(dw,'relation','add',source_identity,'depends_on',identity)
        for index,label in enumerate(numeric_names):
            run(dw,'decision','record',label,'--id','DEC-NUMERIC-'+str(index),'--why','Original numeric-name reason')
        # Import-shaped fixture through the installed event API; queries and
        # exact source opening below still execute the installed CLI.
        for identity,target in [
            ('OPA-SRC-A',{'id':'RAW-TARGET','kind':'component','label':'opaque boundary'}),
            ('OPA-SRC-B',{'id':'RAW-TARGET','kind':'component'}),
            ('OPA-SRC-DORMANT',{'id':'RAW-DORMANT','kind':'component','label':'opaque boundary'}),
            ('STALE-SRC-DORMANT',{'id':'RAW-STALE','kind':'component','label':'stale boundary'}),
            ('STALE-SRC-LIVE',{'id':'RAW-STALE','kind':'component'}),
        ]:
            append_project_event(repo=repo,event_type='component.observed',
                subject={'id':identity,'kind':'component','label':'Imported source'},
                epistemic_status='DECLARED',payload={'lifecycle':'inactive'} if identity.endswith('DORMANT') else {},
                relations=[{'predicate':'depends_on','target':target,'epistemic_status':'INFERRED'}],
                provenance={'producer':'question-acceptance','source':'synthetic-unresolved-target'},
                actor={'kind':'fixture','id':'question-acceptance'})
        relative_periods=('this weekend','this spring','this summer','this autumn','this fall','this winter',
                          'ce week-end','ce printemps','cet été','cet automne','cet hiver',
                          'cette fin de semaine','this fortnight','this decade','cette décennie',
                          'ce siècle','this century','this season','cette saison','this sprint','cette itération',
                          'from launch','during migration','pendant migration','durant migration',
                          'on 3.14','le 3.12','since 21.09.2026','depuis 21.09.2026',
                          'on 2026-09','le 2026-09','2026-09','on 09-21','le 21-09','on 21',
                          'on Mon','le début','2026W39','2026-W39',
                          'lately','so far','to date','thus far','hitherto','up to now',
                          'YTD','MTD','QTD','WTD','dernièrement','dernierement',
                          "jusqu'ici",'jusqu’ici','à ce jour','a ce jour',
                          "pour l'instant",'pour le moment','à présent','a present',
                          '09-21-2026','21-09-2026','09-21-26','21-09-26',
                          '2026-9-21','2026-09-1','2026-9-1','2026-9',
                          '2026-W39-4','2026-W39-7','2026W394','2026W397',
                          '21.09.2026','9.21.2026','2026.09.21','2026.9.21',
                          'Sept 21','Sep 21','Sep. 21','21 Sep 2026','Jan 12','Feb 2',
                          'janv. 12','févr. 2','avr. 3','juil. 4','déc. 5','Sep21',
                          'Sep 21st','Sep. 21st','Sept21st','Jan 1st','Feb 2nd','Apr 3rd',
                          'Aug 4th','janv. 1er','févr. 2e',
                          '12 EST','12 PST','12 EDT','12 PDT','12 CET','12 CEST','12 JST',
                          '12 ET','12 CT','12 MT','12 PT','12ET','12PT',
                          '12 IST','12 AEST','12 NZDT','12 Europe/Paris','12+0200')
        append_project_event(repo=repo,event_type='change.observed',
            subject={'id':'CHANGE-OLD','kind':'change','label':'auth change'},
            epistemic_status='DECLARED',payload={'changed_files':['auth/2026/service.py','auth/at/12/30/3pm/pm/12h30/vers/utc/service.py',
                'auth/at/three/pm/p/m/trois/o/clock/release/around/vers/threepm/service.py']
                + ['auth/'+period.replace(' ','/')+'/service.py' for period in relative_periods]},
            relations=[],timestamp='2025-09-21T08:00:00Z',
            provenance={'producer':'question-acceptance','source':'synthetic-year-filter'},
            actor={'kind':'fixture','id':'question-acceptance'})
        paths=continuity_paths(repo);before={p:p.read_bytes() for p in (paths.events,paths.state) if p.exists()}
        cases=[]
        for question in ['Why auth?','Pourquoi auth ?','What depends on auth service?','Qu’est-ce qui dépend de auth service ?',
                         'Why unrecorded_lunar_module?','What changed in auth since yesterday?',
                         'auth depends on what?', 'de quoi auth dépend-il ?',
                         'What depends on auth and what does auth depend on?',
                         'Qu’est-ce qui dépend de auth et de quoi auth dépend-il ?',
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
            ambiguous_direction=question in ('auth depends on what?', 'de quoi auth dépend-il ?',
                'What depends on auth and what does auth depend on?',
                'Qu’est-ce qui dépend de auth et de quoi auth dépend-il ?')
            ambiguous_time='yesterday' in question or '2026-09-21' in question
            expected='abstained' if 'unrecorded_' in question or ambiguous_direction or ambiguous_time else 'cited-records'
            assert values[0]['status']==expected
            if ambiguous_direction:assert values[0]['context']['abstention']=='dependency-direction-ambiguous'
            if ambiguous_time:assert values[0]['context']['abstention']=='ambiguous-time-filter'
            cases.append({'question':question,'status':expected,'citations':len(values[0]['parts'])})

        for question,flags in [
            ('What changed in auth from 2026?', ('--until','2027-01-01')),
            ('What changed in auth from 2026?', ('--since','2024-01-01')),
            ('What changed in auth since yesterday?', ('--until','2026-09-24')),
            ('What changed in auth before 2026-09-21?', ('--since','2026-09-01')),
            ('Qu’est-ce qui a changé dans auth depuis hier ?', ('--until','2026-09-24')),
        ]:
            for lang in ('fr','en'):
                ambiguous=json.loads(run(dw,'--language',lang,'ask',question,*flags,'--json'))
                assert ambiguous['status']=='abstained'
                assert ambiguous['context']['abstention']=='ambiguous-time-filter'
                assert ambiguous['parts']==[]
        for question,reason in [
            ('Why auth recently?', 'ambiguous-time-filter'),
            ('Pourquoi auth récemment ?', 'ambiguous-time-filter'),
            ('What depends on auth this week?', 'ambiguous-time-filter'),
            ('Qu’est-ce qui dépend de auth cette semaine ?', 'ambiguous-time-filter'),
            ('Remember auth as of Monday?', 'ambiguous-time-filter'),
            ('What changed in auth from 2026?', 'ambiguous-time-filter'),
            ('Qu’est-ce qui a changé dans auth à partir de 2026 ?', 'ambiguous-time-filter'),
            ('Why auth and what changed in billing?', 'mixed-question-intents'),
            ('Pourquoi auth et quels changements dans billing ?', 'mixed-question-intents'),
            ('What changed in auth two days ago?', 'ambiguous-time-filter'),
            ('What changed in auth this week?', 'ambiguous-time-filter'),
            ('What changed in auth recently?', 'ambiguous-time-filter'),
            ('What changed in auth as of Monday?', 'ambiguous-time-filter'),
            ('Qu’est-ce qui a changé dans auth il y a deux jours ?', 'ambiguous-time-filter'),
            ('Qu’est-ce qui a changé dans auth récemment ?', 'ambiguous-time-filter'),
        ]:
            for lang in ('fr','en'):
                result=json.loads(run(dw,'--language',lang,'ask',question,'--json'))
                assert result['status']=='abstained' and result['parts']==[]
                assert result['context']['abstention']==reason
        for lang in ('fr','en'):
            for period in ('in Q1 2026','in Q4 2026','en T1 2026','in H1 2026',
                           'in Q1','en T2','in Ｑ１ 2026','in 2026 Q3','2026',
                           'in FY2026','in FY26','in 2026Q1','in Q12026',
                           'in 2026H1','in H12026','en AF2026','en AF26','in ２０２６Ｑ１',
                           'in FY 26',"in FY'26",'en AF 26') + relative_periods:
                value=json.loads(run(dw,'--language',lang,'ask','What changed in auth '+period+'?','--json'))
                assert value['status']=='abstained' and value['parts']==[]
                assert value['context']['abstention']=='ambiguous-time-filter'
            for question,expected in [('Why lexical x v1?',['DEC-LEX-X']),
                                      ('Why lexical y v2?',['DEC-LEX-Y']),
                                      ('Why x?',['DEC-LEX-X']),('Why lexical z?',[]),
                                      ('Why lexical 東京?',['DEC-TOKYO']),
                                      ('Pourquoi lexical 大阪 ?',['DEC-OSAKA']),
                                      ('Why C++?',['DEC-TECH-CPP']),('Why C#?',['DEC-TECH-CSHARP']),
                                      ('Pourquoi F# ?',['DEC-TECH-FSHARP']),('Why C?',['DEC-TECH-C']),
                                      ('Why Spring?',['DEC-SPRING'])]:
                value=json.loads(run(dw,'--language',lang,'ask',question,'--json'))
                assert [f['fields']['id'] for f in value['context']['facts']]==expected
                assert value['status']==('cited-records' if expected else 'abstained')
                for part in value['parts']:
                    source=part['source']
                    opened=json.loads(run(dw,'state','event',source['eventId'],'--hash',source['eventHash'],'--json'))
                    assert opened['event']['event_hash']==source['eventHash']
        for lang in ('fr','en'):
            for phrase in ('at 12:30','at 3pm','at 12 PM','à 12h30','vers 12','at 12 UTC',
                           'at three PM','three PM','at three p.m.','à trois PM',
                           "at three o'clock",'at release','around three PM','vers trois','threepm'):
                value=json.loads(run(dw,'--language',lang,'ask','What changed in auth '+phrase+'?','--json'))
                assert value['status']=='abstained' and value['parts']==[]
                assert value['context']['abstention']=='ambiguous-time-filter'
            for question,reason in [('What does fallback import?','dependency-direction-ambiguous'),
                                    ('Who calls fallback?','dependency-direction-ambiguous'),
                                    ('Qu’appelle fallback ?','dependency-direction-ambiguous'),
                                    ('How fallback works?','unrecognized-question-intent')]:
                value=json.loads(run(dw,'--language',lang,'ask',question,'--json'))
                assert value['status']=='abstained' and value['parts']==[]
                assert value['context']['abstention']==reason
            for question,flags in [('Remember fallback works?',()),('Mémoire fallback works ?',()),
                                   ('fallback works',('--kind','memory'))]:
                value=json.loads(run(dw,'--language',lang,'ask',question,*flags,'--json'))
                assert [f['fields']['id'] for f in value['context']['facts']]==['DEC-QUERY']
                assert value['status']=='cited-records'
                for part in value['parts']:
                    source=part['source']
                    opened=json.loads(run(dw,'state','event',source['eventId'],'--hash',source['eventHash'],'--json'))
                    assert opened['event']['event_hash']==source['eventHash']
        for lang in ('fr','en'):
            for index,label in enumerate(intent_names):
                identity='DEC-NAME-'+str(index)
                for question,flags in [('Why '+label+'?',()),
                                       ('Pourquoi utilisons-nous '+label+' ici ?',()),
                                       (label,('--kind','memory')),('Remember '+label+'?',())]:
                    value=json.loads(run(dw,'--language',lang,'ask',question,*flags,'--json'))
                    assert value['status']=='cited-records'
                    assert [f['fields']['id'] for f in value['context']['facts']]==[identity], (question, flags, value['context']['facts'])
                    for part in value['parts']:
                        citation=part['source']
                        opened=json.loads(run(dw,'state','event',citation['eventId'],'--hash',citation['eventHash'],'--json'))
                        assert opened['event']['event_hash']==citation['eventHash']
                for question in ('What depends on '+label+'?', 'Qu’est-ce qui dépend de '+label+' ?'):
                    value=json.loads(run(dw,'--language',lang,'ask',question,'--json'))
                    assert value['status']=='cited-records'
                    assert [f['fields']['to'] for f in value['context']['facts']]==[identity]
                    for part in value['parts']:
                        citation=part['source']
                        opened=json.loads(run(dw,'state','event',citation['eventId'],'--hash',citation['eventHash'],'--json'))
                        assert opened['event']['event_hash']==citation['eventHash']
            for index,label in enumerate(numeric_names):
                value=json.loads(run(dw,'--language',lang,'ask','Why '+label+'?','--json'))
                assert value['status']=='cited-records'
                assert [f['fields']['id'] for f in value['context']['facts']]==['DEC-NUMERIC-'+str(index)], (label, value['status'], value['context']['abstention'], [f['fields']['id'] for f in value['context']['facts']])
                for part in value['parts']:
                    citation=part['source']
                    opened=json.loads(run(dw,'state','event',citation['eventId'],'--hash',citation['eventHash'],'--json'))
                    assert opened['event']['event_hash']==citation['eventHash']
        for lang in ('fr','en'):
            for question,identity in [
                ('Why auth. Why billing?','DEC-AUTH'),
                ('Why auth and why billing?','DEC-AUTH'),
                ('Pourquoi auth et pourquoi billing ?','DEC-AUTH'),
                ('Remember auth; Remember billing?','DEC-AUTH'),
                ('What changed in auth and what changed in billing?','CHANGE-OLD'),
            ]:
                value=json.loads(run(dw,'--language',lang,'ask',question,'--entity',identity,'--json'))
                assert value['status']=='abstained' and value['parts']==[]
                assert value['context']['abstention']=='multiple-question-clauses'
        for lang in ('fr','en'):
            for question,reason in [
                ('Why clause and remember billing?','mixed-question-intents'),
                ('Pourquoi clause et remember billing ?','mixed-question-intents'),
                ('Remember clause and remember billing?','multiple-question-clauses'),
                ('Why auth: why billing?','multiple-question-clauses'),
                ('Pourquoi auth : pourquoi billing ?','multiple-question-clauses'),
                ('Remember auth: Remember billing?','multiple-question-clauses'),
                ('Why auth: what changed in billing?','mixed-question-intents'),
                ('Pourquoi auth : quels changements dans billing ?','mixed-question-intents'),
                ('Why auth: Memory billing?','mixed-question-intents'),
            ]:
                value=json.loads(run(dw,'--language',lang,'ask',question,'--entity','DEC-AUTH','--json'))
                assert value['status']=='abstained' and value['parts']==[]
                assert value['context']['abstention']==reason
            for question,identity,flags in [
                ('Why billing?','DEC-AUTH',()),
                ('Why auth unrecordedqualifier?','DEC-AUTH',()),
                ('What changed in billing?','CHANGE-OLD',()),
                ('What changed in auth unrecordedqualifier?','CHANGE-OLD',()),
                ('Remember billing?','DEC-AUTH',()),
                ('billing','DEC-AUTH',('--kind','memory')),
            ]:
                value=json.loads(run(dw,'--language',lang,'ask',question,'--entity',identity,*flags,'--json'))
                assert value['status']=='abstained' and value['parts']==[]
            exact=json.loads(run(dw,'--language',lang,'ask','Why?','--entity','DEC-AUTH','--json'))
            assert exact['status']=='cited-records'
            assert [f['fields']['id'] for f in exact['context']['facts']]==['DEC-AUTH']
            for part in exact['parts']:
                source=part['source']
                opened=json.loads(run(dw,'state','event',source['eventId'],'--hash',source['eventHash'],'--json'))
                assert opened['event']['event_hash']==source['eventHash']
        for lang in ('fr','en'):
            for question,identity in [
                ('Why clause and please remember billing?','DEC-COMPOUND'),
                ('Why clause and do remember billing?','DEC-COMPOUND'),
                ('Why clause and could you please remember billing?','DEC-COMPOUND'),
                ('Why clause and kindly remember billing?','DEC-COMPOUND'),
                ('Why clause: please remember billing?','DEC-COMPOUND'),
                ('Why clause; please remember billing?','DEC-COMPOUND'),
                ('Why clause: please Memory billing?','DEC-COMPOUND'),
                ('Pourquoi clause ; veuillez Mémoire billing ?','DEC-COMPOUND'),
                ('Remember clause and please remember billing?','DEC-COMPOUND'),
                ('What depends on auth and please remember billing?','DEC-AUTH'),
            ]:
                value=json.loads(run(dw,'--language',lang,'ask',question,'--entity',identity,'--json'))
                assert value['status']=='abstained' and value['parts']==[]
                assert value['context']['abstention']=='unsupported-compound-memory-clause'
            literal=json.loads(run(dw,'--language',lang,'ask','clause and please remember billing',
                                   '--kind','memory','--entity','DEC-COMPOUND','--json'))
            assert literal['status']=='cited-records'
            assert [f['fields']['id'] for f in literal['context']['facts']]==['DEC-COMPOUND']
            for part in literal['parts']:
                source=part['source']
                opened=json.loads(run(dw,'state','event',source['eventId'],'--hash',source['eventHash'],'--json'))
                assert opened['event']['event_hash']==source['eventHash']
        for lang in ('fr','en'):
            for question,reason in [
                ('Why adjacent.Why billing?','multiple-question-clauses'),
                ('Pourquoi adjacent.Pourquoi billing ?','multiple-question-clauses'),
                ('Remember adjacent.Remember billing?','multiple-question-clauses'),
                ('Why adjacent.What changed in billing?','mixed-question-intents'),
                ("Pourquoi adjacent.Qu’est-ce qui a changé dans billing ?",'mixed-question-intents'),
                ("Pourquoi adjacent.Qu'est-ce qui a changé dans billing ?",'mixed-question-intents'),
                ("Pourquoi adjacent.Qu’est-ce qui dépend de billing ?",'mixed-question-intents'),
                ("Pourquoi adjacent.Qu'est-ce que billing importe ?",'mixed-question-intents'),
                ("Pourquoi adjacent.Qu’appelle billing ?",'mixed-question-intents'),
                ('Why adjacent.Please remember billing?','unsupported-compound-memory-clause'),
            ]:
                value=json.loads(run(dw,'--language',lang,'ask',question,'--entity','DEC-ADJACENT','--json'))
                assert value['status']=='abstained' and value['parts']==[]
                assert value['context']['abstention']==reason
        for lang in ('fr','en'):
            for separator in (' — ',' – ',' - ',' -- ','—','–'):
                for tail,reason in (
                    ('what changed in billing?','mixed-question-intents'),
                    ('quels changements dans billing ?','mixed-question-intents'),
                    ('Qu’est-ce qui a changé dans billing ?','mixed-question-intents'),
                    ('why billing?','multiple-question-clauses'),
                    ('please remember billing?','unsupported-compound-memory-clause'),
                ):
                    value=json.loads(run(dw,'--language',lang,'ask','Why dashed'+separator+tail,'--entity','DEC-DASH','--json'))
                    assert value['status']=='abstained' and value['parts']==[]
                    assert value['context']['abstention']==reason
            for label in lexical_shapes:
                for identity in (None,'DEC-LEXICAL-0','DEC-LEXICAL-1'):
                    flags=() if identity is None else ('--entity',identity)
                    value=json.loads(run(dw,'--language',lang,'ask','Why '+label+'?',*flags,'--json'))
                    expected=['DEC-LEXICAL-0','DEC-LEXICAL-1'] if identity is None else [identity]
                    assert value['status']=='cited-records'
                    assert sorted(f['fields']['id'] for f in value['context']['facts'])==expected
                    assert value['assurance']=='none' and value['actions']==[] and value['questionStored'] is False
                    for part in value['parts']:
                        citation=part['source']
                        opened=json.loads(run(dw,'state','event',citation['eventId'],'--hash',citation['eventHash'],'--json'))
                        assert opened['event']['event_hash']==citation['eventHash']
        for flag,bound in [('--since',''),('--until',''),('--since','9999-12-31T23:59:59-23:59'),
                           ('--until','0001-01-01T00:00:00+23:59')]:
            rejected=subprocess.run([dw,'ask','What changed in auth?',flag,bound],
                                    cwd=repo,encoding='utf-8',capture_output=True,timeout=30)
            assert rejected.returncode==2 and rejected.stdout==''
            assert 'Traceback' not in rejected.stderr
        for lang in ('fr','en'):
            for question in ('What depends on auth service?', 'Qu’est-ce qui dépend de auth service ?'):
                selected=json.loads(run(dw,'--language',lang,'ask',question,'--json'))
                assert [f['fields']['to'] for f in selected['context']['facts']]==['DEC-AUTH']
                for part in selected['parts']:
                    source=part['source']
                    opened=json.loads(run(dw,'state','event',source['eventId'],'--hash',source['eventHash'],'--json'))
                    assert opened['event']['event_hash']==source['eventHash']
            ambiguous=json.loads(run(dw,'--language',lang,'ask','What depends on auth?','--json'))
            assert ambiguous['status']=='abstained' and ambiguous['parts']==[]
            assert ambiguous['context']['abstention']=='ambiguous-dependency-target'
            exact=json.loads(run(dw,'--language',lang,'ask','What depends on auth?','--entity','DEC-AUTH','--json'))
            assert [f['fields']['to'] for f in exact['context']['facts']]==['DEC-AUTH']
        for lang in ('fr','en'):
            for question in ('What depends on opaque boundary?', 'Qu’est-ce qui dépend de opaque boundary ?'):
                selected=json.loads(run(dw,'--language',lang,'ask',question,'--json'))
                assert sorted(f['fields']['from'] for f in selected['context']['facts'])==['OPA-SRC-A','OPA-SRC-B']
                assert selected['context']['coverage']['matches']==2
                assert selected['context']['coverage']['omitted']==0
                for part in selected['parts']:
                    source=part['source']
                    opened=json.loads(run(dw,'state','event',source['eventId'],'--hash',source['eventHash'],'--json'))
                    assert opened['event']['event_hash']==source['eventHash']
        for lang in ('fr','en'):
            for question in ('What depends on stale boundary?', 'Qu’est-ce qui dépend de stale boundary ?'):
                unresolved=json.loads(run(dw,'--language',lang,'ask',question,'--json'))
                assert unresolved['status']=='abstained' and unresolved['parts']==[]
                assert unresolved['context']['abstention']=='insufficient-cited-records'
                exact=json.loads(run(dw,'--language',lang,'ask',question,'--entity','RAW-STALE','--json'))
                assert [f['fields']['from'] for f in exact['context']['facts']]==['STALE-SRC-LIVE']
                for part in exact['parts']:
                    source=part['source']
                    opened=json.loads(run(dw,'state','event',source['eventId'],'--hash',source['eventHash'],'--json'))
                    assert opened['event']['event_hash']==source['eventHash']
        assert all(p.read_bytes()==b for p,b in before.items())
        run(dw,'decision','retire','DEC-AUTH','--reason','Historic only')
        retired=json.loads(run(dw,'ask','Why?','--entity','DEC-AUTH','--json'));assert retired['status']=='abstained'
        print(json.dumps({'schema':'memory-question-acceptance-1','classification':'MACHINE','human_executed':False,
                          'passed':True,'cases':cases,'journal_before_sha256':hashlib.sha256(before[paths.events]).hexdigest()}))


if __name__=='__main__':main()
