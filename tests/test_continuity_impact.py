from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import test_continuity_kernel as fixtures
from diffwitness.continuity_bridge import record_change_envelope
from diffwitness.continuity_events import (ContinuityError, append_project_events, continuity_paths,
                                         read_project_events, _event_id, _event_hash)
from diffwitness.continuity_impact import anticipate, compare, inspect_impact, _spec
from diffwitness.continuity_impact_contract import reference, impact_subject
from diffwitness.continuity_state import rebuild_state
from diffwitness.continuity_tasks import _spec as task_spec
from diffwitness.continuity_transport import _parse, _serialize
from diffwitness.gitops import snapshot_worktree

class ImpactTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.fixture=fixtures.ContinuityKernelTests();self.repo=self.fixture.repo(Path(temporary.name))
        self.path=continuity_paths(self.repo).events
        self.task=append_project_events(repo=self.repo,events=[task_spec('task.recorded','TASK-IMPACT',
            {'origin':'explicit-declaration','anchor_sha256':None,'anchor_chars':None,
             'session_sha256':None,'ordinal':None,'why':None},label='Expected scope',dedupe='task:TASK-IMPACT')])[0][0]
    def plan(self,paths=None,**kwargs):
        return anticipate(self.repo,'TASK-IMPACT',paths if paths is not None else ['payments/refund path.py','not-changed.py'],**kwargs)['event']
    def change(self):
        envelope,cid=self.fixture.envelope(self.repo);record_change_envelope(repo=self.repo,envelope=envelope);return cid
    def test_actual_git_delta_is_durable_cited_bidirectional_and_not_proof(self):
        initial=self.path.read_bytes();plan=self.plan();planned_bytes=self.path.read_bytes();cid=self.change()
        event=compare(self.repo,plan['subject']['id'],cid)['event'];delta=event['payload']['delta']
        self.assertEqual(delta['planned_observed'],['payments/refund path.py']);self.assertEqual(delta['not_observed'],['not-changed.py'])
        self.assertEqual(delta['outside_plan'],[]);self.assertEqual(delta['unknown_expected'],[])
        self.assertFalse(delta['causal_proof']);self.assertEqual(delta['correctness'],'unknown')
        self.assertEqual(event['epistemic_status'],'OBSERVED');self.assertEqual(plan['epistemic_status'],'DECLARED')
        before=self.path.read_bytes();self.assertFalse(compare(self.repo,plan['subject']['id'],cid)['created'])
        self.assertEqual(self.path.read_bytes(),before)
        for identity in ('TASK-IMPACT',plan['subject']['id'],cid,event['subject']['id']):
            view=inspect_impact(self.repo,identity);self.assertEqual(view['plans'],[plan]);self.assertEqual(view['comparisons'],[event])
        self.assertEqual(self.path.read_bytes(),before);self.assertTrue(before.startswith(planned_bytes));self.assertTrue(planned_bytes.startswith(initial))
        events=read_project_events(self.path);self.assertEqual(_parse(_serialize(events)),events)
        rebuild_state(self.repo);self.assertEqual(self.path.read_bytes(),before)
        observed=next(e for e in events if e['event_type']=='change.observed');self.assertEqual(event['payload']['change'],reference(observed))
    def test_unanticipated_path_and_partial_scope_are_explicit(self):
        plan=self.plan(['payments/rules.py'],unknowns=['Dependency behavior not modeled']);cid=self.change()
        delta=compare(self.repo,plan['subject']['id'],cid)['event']['payload']['delta']
        self.assertEqual(delta['outside_plan'],['payments/refund path.py']);self.assertEqual(delta['not_observed'],['payments/rules.py'])
        self.assertEqual(plan['payload']['scope'],'partial');self.assertEqual(delta['memory_effects'],'unknown')
    def test_dirty_plan_uses_exact_worktree_without_mutating_user_index(self):
        (self.repo/'payments/rules.py').write_text('MAX_REFUND = 200\n')
        before=self.fixture.git(self.repo,'ls-files','--stage');commit=snapshot_worktree(self.repo);plan=self.plan()
        self.assertEqual(plan['payload']['base_tree'],self.fixture.git(self.repo,'rev-parse',commit+'^{tree}'))
        self.assertEqual(self.fixture.git(self.repo,'ls-files','--stage'),before)
        cid=self.change();delta=compare(self.repo,plan['subject']['id'],cid)['event']['payload']['delta']
        self.assertFalse(delta['baseline_matches']);self.assertEqual(delta['not_observed'],[])
        self.assertEqual(delta['unknown_expected'],plan['payload']['expected_files'])
    def test_missing_git_objects_produce_unknown_not_false_absence(self):
        plan=self.plan();cid=self.change()
        with patch('diffwitness.continuity_bridge._changed_files',return_value=([],{'status':'unavailable','reason':'tree-identity-unavailable'})):
            delta=compare(self.repo,plan['subject']['id'],cid)['event']['payload']['delta']
        self.assertEqual(delta['not_observed'],[]);self.assertEqual(delta['planned_observed'],[])
        self.assertEqual(delta['unknown_expected'],plan['payload']['expected_files'])
    def test_recording_plan_after_observed_change_is_not_anticipation(self):
        cid=self.change();plan=self.plan();before=self.path.read_bytes()
        with self.assertRaisesRegex(ContinuityError,'precede'):compare(self.repo,plan['subject']['id'],cid)
        self.assertEqual(self.path.read_bytes(),before)
    def test_invalid_inputs_fail_before_journal_write_and_no_path_aliases(self):
        for paths in [['../escape.py'],['a'*501],['a\\b.py'],['\n.py'],['é'*300+'.py'],[f'{i}.py' for i in range(65)]]:
            before=self.path.read_bytes()
            with self.subTest(paths=paths),self.assertRaises((ValueError,ContinuityError)):self.plan(paths)
            self.assertEqual(self.path.read_bytes(),before)
        exact='x'*497+'.py';self.assertEqual(self.plan([exact])['payload']['expected_files'],[exact])
    def test_import_rejects_forged_delta_reference_hash_and_authority(self):
        plan=self.plan();cid=self.change();event=compare(self.repo,plan['subject']['id'],cid)['event'];original=read_project_events(self.path)
        for mutate in [lambda p:p['delta']['not_observed'].clear(),lambda p:p['plan'].update(event_hash='0'*64),
                       lambda p:p.update(change_id='dwchg_'+'0'*24),lambda p:p.update(candidate_tree='0'*40)]:
            events=copy.deepcopy(original);row=events[-1];mutate(row['payload']);row['subject']=impact_subject(row['event_type'],row['payload']);row['dedupe_key']=row['subject']['id']
            core={k:v for k,v in row.items() if k not in ('event_id','event_hash')};row['event_id']=_event_id(core);row['event_hash']=_event_hash(row)
            with self.assertRaisesRegex(ContinuityError,'impact'):_parse(_serialize(events))
        before=self.path.read_bytes();spec=_spec('impact.compared',event['payload']);spec['epistemic_status']='VERIFIED'
        with self.assertRaises(ContinuityError):append_project_events(repo=self.repo,events=[spec])
        self.assertEqual(self.path.read_bytes(),before)
    def test_real_cli_french_english_show_is_read_only_and_help_has_no_effects(self):
        plan=self.plan();cid=self.change();compare(self.repo,plan['subject']['id'],cid);before=self.path.read_bytes()
        for language,word in [('en','Anticipated'),('fr','anticipés')]:
            args=[sys.executable,'-m','diffwitness.entry','--language',language,'task','impact','show',cid,'--repo',str(self.repo)]
            result=subprocess.run(args,capture_output=True,encoding="utf-8",timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn(word.lower(),result.stdout.lower())
            result=subprocess.run(args+['--json'],capture_output=True,encoding="utf-8",timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['plans'],[plan])
        result=subprocess.run([sys.executable,'-m','diffwitness.entry','task','impact','anticipate','MISSING','--help'],cwd=self.repo,capture_output=True,encoding="utf-8",timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(self.path.read_bytes(),before)

    def test_actual_unavailable_git_tree_and_exact_cited_memory(self):
        from diffwitness.engine_protocol import change_id, repository_fingerprint
        from diffwitness.continuity_cli import invariant_cli
        invariant_cli(['add','Keep identity','--id','INV-IMPACT','--repo',str(self.repo)])
        memory=read_project_events(self.path)[-1]
        plan=self.plan(memory_ids=[memory['event_id']])
        self.assertEqual(plan['payload']['memory'],[reference(memory)])
        base=plan['payload']['base_tree'];candidate='0'*40;repository=repository_fingerprint(self.repo)
        cid=change_id(repository=repository,base_tree=base,candidate_tree=candidate)
        envelope={'schema_version':'change-envelope-1','change_id':cid,'repository':{'fingerprint':repository,'vcs':'git'},
            'base':{'sha':None,'tree':base,'dirty':False},'candidate':{'sha':None,'tree':candidate,'dirty':False},
            'privacy':{'code_uploaded':False,'contains_paths':False,'contains_prompt_text':False},'proof':None,'debt':None,'understanding':None}
        record_change_envelope(repo=self.repo,envelope=envelope)
        result=compare(self.repo,plan['subject']['id'],cid)['event']['payload']
        self.assertEqual(result['inspection']['coverage']['status'],'unavailable')
        self.assertEqual(result['delta']['not_observed'],[])
        self.assertEqual(result['delta']['unknown_expected'],plan['payload']['expected_files'])

    def test_actual_partial_path_coverage_keeps_unobserved_expectations_unknown(self):
        from diffwitness.engine_protocol import change_id, repository_fingerprint
        plan=self.plan(['z-last.py']);base=self.fixture.git(self.repo,'rev-parse','HEAD')
        for i in range(256):(self.repo/f'a-{i:03d}.py').write_text('value = 1\n')
        (self.repo/'z-last.py').write_text('value = 1\n')
        self.fixture.git(self.repo,'add','.');self.fixture.git(self.repo,'commit','-qm','many paths')
        candidate=self.fixture.git(self.repo,'rev-parse','HEAD');tree=self.fixture.git(self.repo,'rev-parse','HEAD^{tree}')
        repository=repository_fingerprint(self.repo);cid=change_id(repository=repository,base_tree=plan['payload']['base_tree'],candidate_tree=tree)
        envelope={'schema_version':'change-envelope-1','change_id':cid,'repository':{'fingerprint':repository,'vcs':'git'},
            'base':{'sha':base,'tree':plan['payload']['base_tree'],'dirty':False},'candidate':{'sha':candidate,'tree':tree,'dirty':False},
            'privacy':{'code_uploaded':False,'contains_paths':False,'contains_prompt_text':False},'proof':None,'debt':None,'understanding':None}
        record_change_envelope(repo=self.repo,envelope=envelope)
        event=compare(self.repo,plan['subject']['id'],cid)['event']
        self.assertEqual(event['payload']['inspection']['coverage'],{'status':'partial','total':257,'omitted':1,'reasons':{'path_limit':1}})
        self.assertEqual(event['payload']['delta']['unknown_expected'],['z-last.py']);self.assertEqual(event['payload']['delta']['not_observed'],[])
        rows=read_project_events(self.path);row=rows[-1]
        row['payload']['inspection']['coverage']={'status':'complete','total':256,'omitted':0}
        row['subject']=impact_subject(row['event_type'],row['payload']);row['dedupe_key']=row['subject']['id']
        row['event_id']=_event_id(row);row['event_hash']=_event_hash(row)
        with self.assertRaisesRegex(ContinuityError,'coverage'):_parse(_serialize(rows))
