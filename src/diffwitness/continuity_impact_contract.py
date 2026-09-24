"""Immutable scope declarations and cited path comparisons; never causal Proof."""
from __future__ import annotations

import hashlib
import json
import re

from .continuity_lineage_contract import lineage_path

IMPACT_PROFILE = 'project-memory-impact-1'
MAX_IMPACT_PATHS = 64
MEMORY_KINDS = frozenset({'objective', 'decision', 'invariant', 'failed-approach', 'feature',
                          'component', 'symbol', 'dependency', 'debt', 'proof-certificate'})


def _check(ok, message):
    if not ok:
        raise ValueError('impact profile: ' + message)


def _oid(value):
    return isinstance(value, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value) is not None


def reference(event):
    return {'event_id': event['event_id'], 'event_hash': event['event_hash']}


def _ref(value):
    return (isinstance(value, dict) and set(value) == {'event_id', 'event_hash'}
            and isinstance(value['event_id'], str) and re.fullmatch(r'dwev_[0-9a-f]{24}', value['event_id'])
            and isinstance(value['event_hash'], str) and re.fullmatch(r'[0-9a-f]{64}', value['event_hash']))


def impact_subject(kind, payload):
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()[:24]
    prefix = 'dwimpact_' if kind == 'impact.planned' else 'dwimpactcmp_'
    return {'id': prefix + digest, 'kind': 'impact-plan' if kind == 'impact.planned' else 'impact-comparison'}


def comparison_delta(plan, change, inspection):
    planned = set(plan['payload']['expected_files'])
    actual = set(inspection['files'])
    matches = plan['payload']['base_tree'] == change['payload']['base_tree']
    complete = matches and inspection['coverage']['status'] == 'complete'
    return {'baseline_matches': matches, 'planned_observed': sorted(planned & actual) if matches else [],
            'outside_plan': sorted(actual - planned) if matches else [],
            'not_observed': sorted(planned - actual) if complete else [],
            'unknown_expected': sorted(planned - actual) if matches and not complete else sorted(planned) if not matches else [],
            'memory_effects': 'unknown', 'correctness': 'unknown', 'causal_proof': False}


def validate_impact(event):
    p, kind = event['payload'], event['event_type']
    _check(kind in ('impact.planned', 'impact.compared'), 'event type')
    _check(event['subject'] == impact_subject(kind, p), 'content-bound separate identity')
    planned = kind == 'impact.planned'
    _check(event['epistemic_status'] == ('DECLARED' if planned else 'OBSERVED'), 'authority')
    _check(event['provenance'] == {'producer': 'diffwitness', 'source': 'local-cli',
                                  'diffwitness_profile': IMPACT_PROFILE}, 'provenance')
    _check(event['actor'] == {'kind': 'unknown' if planned else 'system', 'id': 'diffwitness-impact'}, 'actor')
    _check(event.get('dedupe_key') == event['subject']['id'] and event.get('relations') == [], 'immutable dedupe/no unchecked edges')
    if planned:
        _check(set(p) == {'task_id', 'task', 'base_tree', 'expected_files', 'scope', 'unknowns', 'memory'}, 'plan fields')
        _check(isinstance(p['task_id'], str) and _ref(p['task']) and _oid(p['base_tree']), 'task and tree binding')
        files = p['expected_files']
        _check(isinstance(files, list) and len(files) <= MAX_IMPACT_PATHS
               and all(lineage_path(f) for f in files) and files == sorted(set(files)), 'bounded exact paths')
        _check(p['scope'] in ('partial', 'declared-complete'), 'scope declaration')
        _check(isinstance(p['unknowns'], list) and len(p['unknowns']) <= 16
               and all(isinstance(s, str) and 0 < len(s.strip()) <= 300 for s in p['unknowns']), 'bounded unknowns')
        _check(isinstance(p['memory'], list) and len(p['memory']) <= 32
               and all(_ref(r) for r in p['memory'])
               and len({r['event_id'] for r in p['memory']}) == len(p['memory']), 'memory citations')
    else:
        _check(set(p) == {'plan', 'change', 'change_id', 'base_tree', 'candidate_tree', 'inspection', 'delta'}, 'comparison fields')
        _check(_ref(p['plan']) and _ref(p['change']) and _oid(p['base_tree']) and _oid(p['candidate_tree']), 'cited tree pair')
        _check(isinstance(p['change_id'], str) and re.fullmatch(r'dwchg_[0-9a-f]{24}', p['change_id']), 'change identity')
        inspection = p['inspection']
        _check(isinstance(inspection, dict) and set(inspection) == {'files', 'coverage'}, 'inspection fields')
        files, coverage = inspection['files'], inspection['coverage']
        _check(isinstance(files, list) and len(files) <= 256 and all(isinstance(f, str) for f in files)
               and files == sorted(set(files)), 'observed file list')
        _check(isinstance(coverage, dict), 'coverage')
        if coverage.get('status') == 'complete':
            _check(coverage == {'status': 'complete', 'total': len(files), 'omitted': 0}, 'complete coverage counts')
        else:
            from .continuity_contract import _validate_change_path_coverage
            _validate_change_path_coverage(coverage, len(files))
        _check(isinstance(p['delta'], dict), 'delta')


class ImpactHistoryValidator:
    """Validate reference order and deterministic deltas on append and import."""
    def __init__(self):
        self.events = {}
        self.positions = {}
        self.count = 0

    def admit(self, event):
        if event['provenance'].get('diffwitness_profile') == IMPACT_PROFILE:
            p = event['payload']
            def cited(ref):
                previous = self.events.get(ref['event_id'])
                _check(previous is not None and reference(previous) == ref, 'reference must cite an earlier exact event')
                return previous
            if event['event_type'] == 'impact.planned':
                task = cited(p['task'])
                _check(task['event_type'] == 'task.recorded' and task['subject']['id'] == p['task_id']
                       and task['provenance'].get('diffwitness_profile') == 'project-memory-task-1', 'compatible task')
                for ref in p['memory']:
                    _check(cited(ref)['subject']['kind'] in MEMORY_KINDS, 'supported cited memory kind')
            else:
                plan, change = cited(p['plan']), cited(p['change'])
                _check(plan['event_type'] == 'impact.planned' and plan['provenance'].get('diffwitness_profile') == IMPACT_PROFILE, 'compatible plan')
                _check(change['event_type'] == 'change.observed' and change['provenance'].get('diffwitness_profile') == 'project-memory-artifact-1', 'compatible observed change')
                _check(self.positions[plan['event_id']] < self.positions[change['event_id']], 'plan must precede change observation')
                _check(change['subject']['id'] == p['change_id']
                       and all(change['payload'][key] == p[key] for key in ('base_tree', 'candidate_tree')), 'exact change binding')
                files = p['inspection']['files']
                if p['inspection']['coverage']['status'] != 'unavailable':
                    _check(files == sorted(change['payload']['changed_files']), 'inspection must agree with cited observation')
                    recorded_coverage = change['payload'].get('changed_files_coverage')
                    if recorded_coverage is not None:
                        _check(p['inspection']['coverage'] == recorded_coverage, 'cannot promote recorded path coverage')
                _check(p['delta'] == comparison_delta(plan, change, p['inspection']), 'derived comparison does not match sources')
        self.events[event['event_id']] = event
        self.positions[event['event_id']] = self.count
        self.count += 1


def impact_descriptor():
    return {'event_types': ['impact.planned', 'impact.compared'], 'plan_status': 'DECLARED',
            'comparison_status': 'OBSERVED', 'scope': 'exact files and cited advisory memory',
            'semantic_effects': 'unknown', 'grants_proof_authority': False,
            'ordering': 'plan before observed-change journal entry, not authenticated wall-clock evidence',
            'max_expected_files': MAX_IMPACT_PATHS, 'unknown_payload_fields': 'reject'}
