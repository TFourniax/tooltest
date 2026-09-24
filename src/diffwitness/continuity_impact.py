"""Record anticipated scope and compare it with exact observed Git changes."""
from __future__ import annotations

import argparse
import json
import sys

from .continuity_events import ContinuityError, append_project_events, continuity_paths, read_project_events
from .continuity_impact_contract import (IMPACT_PROFILE, comparison_delta, impact_subject, reference,
                                         validate_impact)
from .gitops import GitError, git, repo_root, snapshot_worktree
from .language import tr


def _spec(kind, payload):
    subject = impact_subject(kind, payload)
    return {'event_type': kind, 'subject': subject,
            'epistemic_status': 'DECLARED' if kind == 'impact.planned' else 'OBSERVED',
            'payload': payload, 'relations': [], 'dedupe_key': subject['id'],
            'provenance': {'producer': 'diffwitness', 'source': 'local-cli', 'diffwitness_profile': IMPACT_PROFILE},
            'actor': {'kind': 'unknown' if kind == 'impact.planned' else 'system', 'id': 'diffwitness-impact'}}


def _select(events, identity, kind):
    found = [e for e in events if e['subject']['id'] == identity and e['event_type'] == kind]
    if len(found) != 1:
        raise ContinuityError('expected one exact ' + kind + ' record for ' + identity)
    return found[0]


def anticipate(repo, task_id, files, *, scope='partial', unknowns=None, memory_ids=None):
    root = repo_root(repo)
    events = read_project_events(continuity_paths(root).events)
    task = _select(events, task_id, 'task.recorded')
    by_id = {e['event_id']: e for e in events}
    memory = []
    for identity in memory_ids or []:
        if identity not in by_id:
            raise ContinuityError('unknown memory event: ' + identity)
        memory.append(reference(by_id[identity]))
    # Validate before creating an ephemeral snapshot, then capture the current
    # meaningful worktree with the existing alternate-index boundary.
    payload = {'task_id': task_id, 'task': reference(task), 'base_tree': '0' * 40,
               'expected_files': sorted(set(files)), 'scope': scope, 'unknowns': unknowns or [], 'memory': memory}
    validate_impact(_spec('impact.planned', payload))
    baseline = snapshot_worktree(root)
    payload['base_tree'] = git(root, 'rev-parse', baseline + '^{tree}').strip()
    event, created = append_project_events(repo=root, events=[_spec('impact.planned', payload)])[0]
    return {'schema_version': 'impact-result-1', 'event': event, 'created': created}


def compare(repo, plan_id, change_id):
    from .continuity_bridge import _changed_files
    root = repo_root(repo)
    events = read_project_events(continuity_paths(root).events)
    plan = _select(events, plan_id, 'impact.planned')
    change = _select(events, change_id, 'change.observed')
    p = change['payload']
    files, coverage = _changed_files(root, {'base': {'tree': p['base_tree']}, 'candidate': {'tree': p['candidate_tree']}})
    inspection = {'files': sorted(files), 'coverage': coverage}
    payload = {'plan': reference(plan), 'change': reference(change), 'change_id': change_id,
               'base_tree': p['base_tree'], 'candidate_tree': p['candidate_tree'], 'inspection': inspection,
               'delta': comparison_delta(plan, change, inspection)}
    event, created = append_project_events(repo=root, events=[_spec('impact.compared', payload)])[0]
    return {'schema_version': 'impact-result-1', 'event': event, 'created': created}


def inspect_impact(repo, identity):
    events = read_project_events(continuity_paths(repo_root(repo)).events)
    plans = [e for e in events if e['provenance'].get('diffwitness_profile') == IMPACT_PROFILE
             and e['event_type'] == 'impact.planned'
             and (e['subject']['id'] == identity or e['payload']['task_id'] == identity)]
    selected = {e['event_id'] for e in plans}
    comparisons = [e for e in events if e['provenance'].get('diffwitness_profile') == IMPACT_PROFILE
                   and e['event_type'] == 'impact.compared'
                   and (e['payload']['plan']['event_id'] in selected or e['payload']['change_id'] == identity
                        or e['subject']['id'] == identity)]
    cited_plans = {e['payload']['plan']['event_id'] for e in comparisons}
    plans = [e for e in events if e['event_id'] in selected | cited_plans]
    if not plans:
        raise ContinuityError('no impact records for exact task, plan, comparison or change identity')
    if len(plans) + len(comparisons) > 200:
        raise ContinuityError('impact result exceeds 200 records; select an exact plan or use dw state history')
    result = {'schema_version': 'impact-history-1', 'identity': identity, 'plans': plans, 'comparisons': comparisons,
              'authority': 'Recorded intent and path observations, not correctness, semantic impact or causal Proof.'}
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 1024 * 1024:
        raise ContinuityError('impact result exceeds byte bound; use dw state history')
    return result


def render_impact(result):
    if 'event' in result:
        events = [result['event']]
    else:
        events = result['plans'] + result['comparisons']
    lines = []
    for event in events:
        p = event['payload']
        lines.append(event['subject']['id'] + ' [' + event['epistemic_status'] + ']')
        lines.append(tr('Source: ', 'Source : ') + event['event_id'] + ' ' + event['event_hash'])
        if event['event_type'] == 'impact.planned':
            lines.append(tr('Task: ', 'Tâche : ') + p['task_id'])
            lines.append(tr('Anticipated files: ', 'Fichiers anticipés : ') + ', '.join(p['expected_files']))
            lines.append(tr('Declared scope: ', 'Périmètre déclaré : ') + p['scope'])
            lines.extend(tr('Cited memory: ', 'Mémoire citée : ') + ref['event_id'] + ' ' + ref['event_hash'] for ref in p['memory'])
            lines.extend(tr('Unknown: ', 'Inconnu : ') + value for value in p['unknowns'])
        else:
            lines.append(tr('Exact change: ', 'Changement exact : ') + p['change_id'])
            for key, en, fr in [('planned_observed','Anticipated and observed','Anticipés et observés'),
                                ('outside_plan','Observed outside plan','Observés hors plan'),
                                ('not_observed','Not observed in this change','Non observés dans ce changement'),
                                ('unknown_expected','Anticipation unresolved','Anticipations non résolues')]:
                lines.append(tr(en, fr) + ': ' + ', '.join(p['delta'][key]))
            if not p['delta']['baseline_matches']:
                lines.append(tr('Baseline differs: comparison unknown.', 'Base différente : comparaison inconnue.'))
            lines.append(tr('Observation coverage: ', 'Couverture observée : ') + p['inspection']['coverage']['status'])
    lines.append(tr('Memory effects and correctness remain unknown. This comparison is not causal Proof.',
                    'Effets sur la mémoire et correction inconnus. Cette comparaison n’est pas une preuve causale.'))
    return '\n'.join(lines)


def impact_cli(argv):
    parser = argparse.ArgumentParser(prog='dw task impact', description=tr('Record and compare anticipated scope.', 'Enregistrer et comparer le périmètre anticipé.'))
    sub = parser.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('anticipate'); plan.add_argument('task_id')
    plan.add_argument('--file', action='append', default=[]); plan.add_argument('--memory-event', action='append', default=[])
    plan.add_argument('--scope', choices=['partial', 'declared-complete'], default='partial')
    plan.add_argument('--unknown', action='append', default=[])
    comparison = sub.add_parser('compare'); comparison.add_argument('plan_id'); comparison.add_argument('change_id')
    show = sub.add_parser('show'); show.add_argument('identity')
    for command in (plan, comparison, show):
        command.add_argument('--repo', default='.'); command.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'anticipate':
            result = anticipate(args.repo, args.task_id, args.file, scope=args.scope, unknowns=args.unknown, memory_ids=args.memory_event)
        elif args.command == 'compare':
            result = compare(args.repo, args.plan_id, args.change_id)
        else:
            result = inspect_impact(args.repo, args.identity)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_impact(result))
        return 0
    except (ContinuityError, GitError, ValueError, OSError) as exc:
        print(tr('Impact rejected: ', 'Impact refusé : ') + str(exc), file=sys.stderr)
        return 2
