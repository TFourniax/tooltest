"""Bounded advisory view over captured sources, reusing Core's redundancy features.

Never calls the debt sensor's admission/ledger path. Literals and conditions are
retained for review; similarity cannot establish behavioral equivalence.
"""
import ast
from collections import defaultdict
from itertools import combinations
import re
import time

from .semantic_redundancy import _extract_units, _candidate_pairs, _similarity, _overlap, TOKEN_RE

MAX_FILES, MAX_UNITS, MAX_PAIRS, MAX_FINDINGS = 100, 500, 2000, 20


def triage_captured(rows, read_source):
    admitted=[r for r in rows if r['role']=='production' and r['status']=='parsed']
    units, details, processed, oversized=[],{},0,0
    deadline=time.monotonic()+3
    stopped=False
    for row in admitted[:MAX_FILES]:
        if time.monotonic()>deadline or len(units)>=MAX_UNITS:
            stopped=True;break
        data=read_source(row)
        if len(data)>128*1024:
            oversized+=1;stopped=True;continue
        text=data.decode('utf-8')
        lines=text.splitlines(keepends=True)
        extracted=_extract_units(row['path'],text,min_tokens=8)
        source_guards=[]
        if row['path'].endswith('.py'):
            try:source_guards=[(n.lineno,ast.unparse(n.test)) for n in ast.walk(ast.parse(text)) if isinstance(n,(ast.If,ast.IfExp))]
            except (SyntaxError,RecursionError):pass
        for unit in extracted:
            if len(units)>=MAX_UNITS:stopped=True;break
            excerpt=''.join(lines[unit.line-1:unit.end_line])
            tokens=TOKEN_RE.findall(excerpt)
            literals={t for t in tokens if t.startswith(('"',"'")) or re.fullmatch(r'\d+(?:\.\d+)?',t)}
            guards=[value for line,value in source_guards if unit.line<=line<=unit.end_line]
            details[len(units)]={'tokens':tokens,'literals':literals,'guards':guards,'sourceSha256':row['sourceSha256']}
            units.append(unit)
        processed+=1
    pairs=_candidate_pairs(units)
    # Small corpora permit full comparison. In larger ones, operation-name
    # matches only nominate pairs; a name never becomes a finding on its own.
    if len(units)<=64:pairs.update(combinations(range(len(units)),2))
    else:
        names=defaultdict(list)
        for i,u in enumerate(units):names[(u.language,u.name)].append(i)
        for candidates in names.values():pairs.update(combinations(candidates[:32],2))
    findings=[]
    compared=0
    for a,b in sorted(pairs)[:MAX_PAIRS]:
        if time.monotonic()>deadline:
            stopped=True;break
        compared+=1
        left,right=units[a],units[b]
        if left.language!=right.language or _overlap(left,right):continue
        ld,rd=details[a],details[b]
        same=ld['tokens']==rd['tokens']
        score,features=_similarity(left,right)
        if not same and score<.60:continue
        different_literals=ld['literals']!=rd['literals']
        different_guards=ld['guards']!=rd['guards']
        findings.append({'kind':'identical-token-candidate' if same else 'potential-behavior-conflict' if different_literals or different_guards else 'structural-overlap-candidate',
            'authority':'INFERRED','debt':'NOT_MEASURED','score':round(score,4),'features':features,
            'locations':[{'path':u.path,'name':u.name,'line':u.line,'endLine':u.end_line,'sourceSha256':d['sourceSha256']} for u,d in ((left,ld),(right,rd))],
            'differences':{'literalValuesDiffer':different_literals,'conditionsDiffer':different_guards,
                'leftConditions':[v[:300] for v in ld['guards'][:8]],'rightConditions':[v[:300] for v in rd['guards'][:8]]},
            'interpretation':'Review candidate only. These operations may implement complementary layers or different requirements. Similarity is not equivalence.',
            'acceptanceTest':'Compare callers, requirements, boundary inputs, outputs and raised errors, especially differing conditions/literals. Do not consolidate or delete before discriminating tests.'})
    findings.sort(key=lambda f:(-f['score'],f['locations'][0]['path'],f['locations'][1]['path']))
    return {'schema':'structure-triage-1','findings':findings[:MAX_FINDINGS],
        'coverage':{'productionParsedFiles':len(admitted),'filesInspected':processed,'units':len(units),'candidatePairs':len(pairs),
                    'pairsCompared':compared,'filesOmittedByBytes':oversized,'findingsOmitted':max(0,len(findings)-MAX_FINDINGS),
                    'complete':not stopped and len(admitted)<=MAX_FILES and len(pairs)<=MAX_PAIRS,
                    'limits':{'files':MAX_FILES,'fileBytes':128*1024,'units':MAX_UNITS,'pairs':MAX_PAIRS,'findings':MAX_FINDINGS,'seconds':3}},
        'unusedCode':'UNKNOWN: static imports cannot exclude dynamic loading, reflection, configuration or unsupported language paths.'}
