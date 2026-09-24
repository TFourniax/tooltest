"""Deterministic, extractive answers from one strictly validated local journal.

The question is a query, never an instruction. No model, command execution,
network, journal append or derived-state write is part of this reader.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date, datetime, timezone
import hashlib
import json
import re
import sys
import unicodedata

from .continuity_events import ContinuityError, _read_validated_snapshot, continuity_paths
from .continuity_history import _display, _source, _wire
from .continuity_search import tokens
from .gitops import repo_root
from .language import tr

MAX_PACKET_BYTES = 1024 * 1024
_STOP = tokens('why pourquoi what which who how where when does depend depends dependencies '
               'depend de dependances dependent quels quelles quel quelle qui quoi comment '
               'est que dans pour sur avec nous notre cette ceci cela ici depuis apres avant '
               'the and this that those these here there from since after before about have '
               'has was were are using use uses utilisons utiliser utilise module component '
               'composant fichiers files changed changes change changee changements fait faits '
               'memory memoire records recorded logiciel software')
_AUTHORITY = ('Extracts describe recorded assertions, not authenticated authors, current code '
              'applicability, complete semantic coverage or new causal Proof.')


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _instant(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be an ISO date or timestamp with a timezone')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp requires an explicit timezone')
    return result.astimezone(timezone.utc)


def _query(question, kind, since, until, entity):
    if (not isinstance(question, str) or not question.strip() or len(question) > 2000
            or any(ord(c) < 32 or ord(c) == 127 for c in question)):
        raise ValueError('question must be nonempty text of at most 2000 characters without controls')
    if kind not in ('auto', 'why', 'dependencies', 'changes', 'memory'):
        raise ValueError('unsupported question kind')
    if entity is not None:
        from .continuity_history import _identity
        _identity(entity)
    query_tokens = tokens(question)
    if kind == 'auto':
        kind = ('why' if query_tokens & {'why', 'pourquoi'} else
                'dependencies' if query_tokens & {'depends', 'depend', 'dependent', 'dependances', 'dependencies'} else
                'changes' if query_tokens & {'changed', 'changes', 'change', 'changements'} else 'memory')
    ambiguity = None
    # Only explicit ISO dates are interpreted. Relative dates and historical
    # "before/as of" questions must not silently become a current-state answer.
    natural_dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', question)
    if since is None and natural_dates:
        bare_bound = re.search(r"\b(?:since|depuis|after|après)\s+(\d{4}-\d{2}-\d{2})\s*[?!.]*\s*$",
                               question, re.I)
        if len(natural_dates) == 1 and bare_bound is not None:
            since = bare_bound.group(1)
        else:
            ambiguity = 'ambiguous-time-filter'
    elif since is None and until is None and query_tokens & {'since', 'depuis', 'after', 'apres', 'before', 'avant', 'yesterday', 'hier'}:
        ambiguity = 'ambiguous-time-filter'
    lower, upper = _instant(since) if since else None, _instant(until) if until else None
    if lower and upper and lower > upper:
        raise ValueError('since must not be later than until')
    if (lower or upper) and kind != 'changes':
        ambiguity = 'temporal-filter-requires-changes'
    # An incoming recorded dependency question has one supported direction.
    if kind == 'dependencies':
        incoming = (re.fullmatch(r"\s*(?:what|who)\s+depends?\s+on\s+.+?[?!.]*\s*", question, re.I)
                    or re.fullmatch(r"\s*(?:qu['’]est-ce\s+qui|qui)\s+d[eé]pend(?:ent)?\s+de\s+.+?[?!.]*\s*",
                                    question, re.I))
        if incoming is None:
            ambiguity = 'dependency-direction-ambiguous'
    cleaned = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', question)
    terms = tokens(cleaned) - _STOP
    if not terms and entity is None:
        ambiguity = ambiguity or 'no-specific-search-term'
    return {'text': question, 'kind': kind, 'entity': entity, 'terms': sorted(terms),
            'since': lower.isoformat() if lower else None, 'until': upper.isoformat() if upper else None,
            'timeBasis': 'inclusive recorded timestamps; not authenticated wall-clock',
            'dependencyDirection': 'incoming recorded edges' if kind == 'dependencies' else None}, ambiguity


def question_context(repo, question, *, kind='auto', since=None, until=None, entity=None, limit=12):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('limit must be an integer from 1 to 50')
    query, abstention = _query(question, kind, since, until, entity)
    events, journal_digest, validator = _read_validated_snapshot(continuity_paths(repo_root(repo)).events)
    current = validator.memory_history.current
    terms = set(query['terms'])
    def match(subject, extra=''):
        if entity is not None:
            return 1000 if subject['id'] == entity else 0
        return len(terms & tokens(' '.join((subject['id'], subject.get('label') or '', extra))))
    def active(identity):
        return identity not in current or current[identity]['active']
    def fact(sequence, event, category, fields, score, *, status=None, revisions=()):
        return {'category': category, 'fields': fields, 'epistemicStatus': status or event['epistemic_status'],
                'source': _source(event), 'sequence': sequence, 'recordedAt': event['timestamp'],
                'applicabilitySources': [_source(e) for e in revisions], 'relevance': score}
    candidates, invalid_times = [], 0
    if not abstention and query['kind'] == 'dependencies':
        latest = {}
        for sequence, event in enumerate(events, 1):
            for relation in event.get('relations', []):
                if relation['predicate'] not in {'depends_on', 'imports', 'calls-name'}:
                    continue
                key = (event['subject']['id'], relation['predicate'], relation['target']['id'])
                latest[key] = sequence, event, relation
        for sequence, event, relation in latest.values():
            target = relation['target']; target_state = current.get(target['id'])
            target_subject = target_state['assertion']['subject'] if target_state else target
            score = match(target_subject)
            if score and active(event['subject']['id']) and active(target['id']):
                revisions = [current[x]['revision'] for x in (event['subject']['id'], target['id'])
                             if x in current and current[x]['action']]
                candidates.append(fact(sequence, event, 'dependency',
                    {'from': event['subject']['id'], 'predicate': relation['predicate'], 'to': target['id']}, score,
                    status=relation.get('epistemic_status') or event['epistemic_status'], revisions=revisions))
    elif not abstention:
        for sequence, event in enumerate(events, 1):
            subject, payload = event['subject'], event['payload']
            if query['kind'] == 'changes':
                if event['event_type'] != 'change.observed':
                    continue
                paths = payload.get('changed_files')
                if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                    continue
                score = match(subject, ' '.join(paths))
                if not score:
                    continue
                try:
                    timestamp = _instant(event['timestamp'])
                except (ValueError, OverflowError):
                    invalid_times += 1
                    continue
                if query['since'] and timestamp < _instant(query['since']) or query['until'] and timestamp > _instant(query['until']):
                    continue
                candidates.append(fact(sequence, event, 'change', {'id': subject['id'], 'paths': paths,
                    'baseTree': payload.get('base_tree'), 'candidateTree': payload.get('candidate_tree'),
                    'pathCoverage': payload.get('changed_files_coverage', {'status': 'legacy-unspecified'})}, score))
                continue
            state = current.get(subject['id'])
            if not state or not state['active'] or state['assertion']['event_id'] != event['event_id']:
                continue
            score = match(subject)
            if not score:
                continue
            fields = {'id': subject['id'], 'kind': subject['kind'], 'label': subject.get('label')}
            if query['kind'] == 'why':
                reason_field = next((f for f in ('why', 'reason') if isinstance(payload.get(f), str) and payload[f].strip()), None)
                if reason_field is None:
                    continue
                fields.update(reasonField=reason_field, reason=payload[reason_field])
            revisions = [state['revision']] if state['action'] else []
            candidates.append(fact(sequence, event, query['kind'], fields, score, revisions=revisions))
    candidates.sort(key=lambda item: (-item['relevance'], -item['sequence'], _wire(item['fields'])))
    facts = candidates[:limit]
    if not facts:
        abstention = abstention or ('unusable-recorded-timestamps' if invalid_times else 'insufficient-cited-records')
    packet = {'schema_version': 'memory-question-context-1', 'question': query,
              'anchor': {'eventCount': len(events), 'eventHead': events[-1]['event_hash'] if events else None,
                         'journalSha256': journal_digest},
              'facts': copy.deepcopy(facts),
              'coverage': {'method': 'deterministic lexical lookup in validated journal',
                           'scope': 'recorded incoming relations' if query['kind'] == 'dependencies' else
                                    'recorded change events' if query['kind'] == 'changes' else 'current active assertions',
                           'matches': len(candidates), 'omitted': max(0, len(candidates)-limit),
                           'unusableTimestamps': invalid_times, 'semanticCompleteness': 'unknown'},
              'abstention': abstention, 'authority': _AUTHORITY}
    packet['context_id'] = 'dwqctx_' + _digest(packet)
    if len(_wire(packet)) > MAX_PACKET_BYTES:
        raise ContinuityError('question context exceeds its byte bound; select a narrower query')
    return packet


def answer_question(repo, question, **options):
    packet = question_context(repo, question, **options)
    # Every answer part references one complete immutable ContextPack fact.
    # Presentation is extractive; a model never creates factual answer text.
    answer = {'schema_version': 'memory-question-answer-1', 'status': 'abstained' if packet['abstention'] else 'cited-records',
              'context': packet, 'parts': [{'factIndex': i, 'source': copy.deepcopy(f['source'])} for i, f in enumerate(packet['facts'])],
              'assurance': 'none', 'actions': [], 'questionStored': False}
    answer['answer_id'] = 'dwanswer_' + _digest(answer)
    return answer


def render_answer(answer):
    packet = answer['context']
    lines = [tr('Recorded project memory', 'Mémoire du projet enregistrée')]
    if answer['status'] == 'abstained':
        lines.append(tr('Insufficient sources to answer this question.', 'Sources insuffisantes pour répondre à cette question.'))
        lines.append(packet['abstention'])
    for part in answer['parts']:
        fact = packet['facts'][part['factIndex']]
        fields = fact['fields']
        # JSON quoting keeps text supplied by a project visibly data, including
        # newlines, terminal controls and instruction-shaped labels/reasons.
        quoted = json.dumps(fields, ensure_ascii=False, sort_keys=True)
        quoted = ''.join(f'\\u{ord(c):04x}' if unicodedata.category(c).startswith('C') or unicodedata.category(c) in {'Zl', 'Zp'} else c for c in quoted)
        lines.append(f"- [{fact['epistemicStatus']}] {quoted}")
        source = fact['source']
        lines.append(f"  {source['eventId']} sha256:{source['eventHash']}")
        for revision in fact['applicabilitySources']:
            lines.append(f"  applicability: {revision['eventId']} sha256:{revision['eventHash']}")
    if packet['coverage']['omitted']:
        lines.append(tr('Additional matching records omitted: ', 'Autres enregistrements correspondants omis : ') + str(packet['coverage']['omitted']))
    lines.append(tr('Recorded assertions only; semantic completeness and current applicability remain unknown. No new Proof.',
                    'Assertions enregistrées seulement ; exhaustivité sémantique et applicabilité actuelle inconnues. Aucune nouvelle Proof.'))
    return '\n'.join(lines) + '\n'


def question_cli(argv):
    parser = argparse.ArgumentParser(prog='dw ask', description=tr('Ask local project memory with exact sources or abstention.',
        'Interroger la mémoire locale avec des sources exactes ou une abstention.'))
    parser.add_argument('question', nargs='+')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--kind', choices=('auto','why','dependencies','changes','memory'), default='auto')
    parser.add_argument('--entity')
    parser.add_argument('--since')
    parser.add_argument('--until')
    parser.add_argument('--limit', type=int, default=12)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = answer_question(args.repo, ' '.join(args.question), kind=args.kind, entity=args.entity,
                                 since=args.since, until=args.until, limit=args.limit)
    except (ValueError, OSError, RuntimeError) as exc:
        print(tr('Memory question rejected: ', 'Question mémoire refusée : ') + _display(str(exc), limit=500), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_answer(result), end='\n' if args.json else '')
    return 0
