import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from diffwitness.structure_scan import capture, page, step, storage, load, source_lines, lock

class ProjectStructureScanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dw-scan-fixture-')
        self.root=Path(self.temp.name).resolve()
        self.git('init','-q','-b','main')
        self.git('config','user.name','Scan Fixture')
        self.git('config','user.email','scan@example.invalid')
        self.git('config','gc.auto','0')
        self.git('config','core.autocrlf','false')
        self.write('pricing.py','def price(value):\n    return value * 0.9 if value >= 100 else value\n')
        self.write('tests/test_pricing.py','from pricing import price\ndef test_threshold():\n    assert price(100) == 90\n')
        self.write('unseen/session.py','def permitted(role):\n    return role == "operator"\n')
        self.write('README.md','# Intent\nKeep calculations independent.\n')
        self.write('.env','PRIVATE_SECRET_SENTINEL')
        self.write('credentials.json','{"token":"PRIVATE_SECRET_SENTINEL"}')
        self.write('.github/workflows/check.yml','jobs:\n  check:\n    runs-on: ubuntu-latest\n')
        self.write('node_modules/lib/a.py','SECRET_SENTINEL')
        self.git('add','-A');self.git('commit','-qm','fixture')
    def tearDown(self):self.temp.cleanup()
    def write(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    def git(self,*args):
        return subprocess.check_output(['git',*args],cwd=self.root,stderr=subprocess.PIPE).decode().strip()
    def finish(self,**kwargs):
        result=capture(self.root,**kwargs)
        for _ in range(100):
            if result['state']=='complete':break
            result=step(self.root,result['snapshotId'],batch=2)
        self.assertEqual(result['state'],'complete')
        return result
    def pages(self,sid):
        result=[];cursor=None
        for _ in range(100):
            value=page(self.root,sid,cursor=cursor,limit=2);result.extend(value['files']);cursor=value['nextCursor']
            self.assertEqual(value['snapshotId'],sid)
            if not cursor:return result
        self.fail('pagination did not terminate')
    def test_initial_global_inventory_is_source_bound_and_never_proof(self):
        before=self.git('status','--porcelain')
        result=self.finish(documents=['README.md'],ci=True)
        rows={r['path']:r for r in self.pages(result['snapshotId'])}
        self.assertEqual(rows['unseen/session.py']['status'],'parsed')
        self.assertEqual(rows['tests/test_pricing.py']['role'],'test')
        self.assertEqual(rows['README.md']['extraction']['description']['intent'][0]['authority'],'DECLARED')
        self.assertEqual(rows['.github/workflows/check.yml']['role'],'ci')
        for p in ('.env','credentials.json','node_modules/lib/a.py'):
            self.assertEqual(rows[p]['status'],'excluded');self.assertNotIn('sourceSha256',rows[p])
        self.assertNotIn('PRIVATE_SECRET_SENTINEL',json.dumps(rows))
        self.assertEqual(result['proof'],'UNKNOWN');self.assertFalse(result['runtimeGraph'])
        self.assertEqual(self.git('status','--porcelain'),before)
        self.assertFalse((self.root/'.git/diffwitness/project-events.jsonl').exists())
    def test_same_content_commit_and_unchanged_rerun_reuse_snapshot(self):
        one=self.finish();self.git('commit','--allow-empty','-qm','metadata only')
        two=self.finish();self.assertEqual(one['snapshotId'],two['snapshotId'])
        with patch('diffwitness.structure_scan.extract_structure',side_effect=AssertionError('must reuse')):
            three=self.finish()
        self.assertEqual(two['snapshotId'],three['snapshotId'])
    def test_worktree_overlay_is_separate_and_invalidation_reuses_untouched_facts(self):
        head=self.finish()
        self.write('pricing.py','def price(value):\n    return value * 0.8\n')
        self.write('new.py','def first():\n    return 1\n')
        (self.root/'unseen/session.py').unlink()
        work=self.finish(source='WORKTREE')
        self.assertNotEqual(head['snapshotId'],work['snapshotId']);self.assertIsNone(work['tree'])
        rows={r['path']:r for r in self.pages(work['snapshotId'])}
        self.assertIn('new.py',rows);self.assertNotIn('unseen/session.py',rows)
        self.assertGreater(work['coverage']['reused'],0)
        self.assertEqual(self.finish()['snapshotId'],head['snapshotId'])
    def test_cancel_resume_limits_and_cursor_binding(self):
        one=capture(self.root,max_files=1)
        sid=one['snapshotId'];self.assertEqual(step(self.root,sid,action='cancel')['state'],'cancelled')
        self.assertEqual(step(self.root,sid)['state'],'cancelled')
        step(self.root,sid,action='resume')
        while step(self.root,sid)['state']!='complete':pass
        result=page(self.root,sid,limit=1)
        self.assertFalse(result['coverage']['complete']);self.assertGreater(result['coverage']['statuses']['omitted'],0)
        with self.assertRaises(ValueError):page(self.root,sid,cursor='dwscan_'+'0'*64+':1')
        with patch('diffwitness.structure_scan.MAX_INVENTORY',2):
            limited=self.finish()
        self.assertFalse(limited['coverage']['inventoryComplete'])
    def test_symlinks_never_admitted(self):
        link=self.root/'outside.py'
        try:link.symlink_to(self.root/'pricing.py')
        except OSError as exc:self.skipTest(f'OS did not permit fixture symlink: {exc.errno}')
        else:
            rows={r['path']:r for r in self.pages(self.finish(source='WORKTREE')['snapshotId'])}
            self.assertEqual(rows['outside.py']['reason'],'link-or-special')
    def test_worktree_mutation_restarts(self):
        from diffwitness.structure_scan import work_inventory
        calls=0
        def mutate(root,selection):
            nonlocal calls
            calls+=1
            if calls==2:self.write('new-during-capture.py','VALUE=7\n')
            return work_inventory(root,selection)
        with patch('diffwitness.structure_scan.work_inventory',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'changed during capture'):capture(self.root,source='WORKTREE')

    def test_empty_directory_fanout_is_also_bounded(self):
        from diffwitness.structure_scan import work_inventory
        for i in range(30):(self.root/f'empty-{i}').mkdir()
        with patch('diffwitness.structure_scan.MAX_INVENTORY',10):
            rows,complete=work_inventory(self.root,{'documents':[],'ci':False})
        self.assertFalse(complete);self.assertLessEqual(len(rows),10)
    def test_captured_git_pages_stay_on_original_tree(self):
        one=self.finish();self.write('pricing.py','VALUE=3\n');self.git('add','.');self.git('commit','-qm','new')
        old=self.pages(one['snapshotId']);new=self.finish()
        self.assertNotEqual(one['snapshotId'],new['snapshotId'])
        self.assertEqual(old,self.pages(one['snapshotId']))
    def test_optional_provider_change_invalidates_snapshot(self):
        one=self.finish()
        with patch('diffwitness.structure_scan.provider_profile',return_value='{"schema":"changed-test-profile"}'):
            two=self.finish()
        self.assertNotEqual(one['snapshotId'],two['snapshotId'])

    def test_published_manifest_and_source_tampering_fail_closed(self):
        one=self.finish();base=storage(self.root);sid=one['snapshotId']
        original=load(base,sid)
        manifest=base/'snapshots'/(sid+'.json')
        altered=copy.deepcopy(original);altered['files'][0]['path']='forged.py'
        manifest.write_text(json.dumps(altered),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'integrity'):page(self.root,sid)
        manifest.write_text(json.dumps(original),encoding='utf-8')
        row=next(r for r in original['files'] if r['path']=='pricing.py')
        (base/'blobs'/row['sourceSha256']).write_bytes(b'forged')
        with self.assertRaisesRegex(ValueError,'integrity'):source_lines(self.root,sid,'pricing.py')

    def test_live_writer_is_not_stolen(self):
        base=storage(self.root)
        with lock(base):
            with self.assertRaisesRegex(ValueError,'busy'):
                with lock(base):pass

    def test_dense_import_page_fits_wire_budget_without_losing_omission_count(self):
        from diffwitness.structure_scan import canonical, MAX_PAGE_BYTES
        # Long valid module identifiers exercise expansion from extraction into
        # source-bound relation rows, including the first row of a page.
        self.write('dense.py',''.join('import module_'+str(i)+'_'+'a'*1500+'\n' for i in range(500)))
        self.git('add','.');self.git('commit','-qm','dense import fixture')
        value=self.finish();cursor=None;found=None
        while True:
            result=page(self.root,value['snapshotId'],cursor=cursor,limit=100)
            self.assertLessEqual(len(canonical(result)),MAX_PAGE_BYTES)
            found=next((r for r in result['files'] if r['path']=='dense.py'),found)
            cursor=result['nextCursor']
            if cursor is None:break
        if found['status']=='parsed':
            self.assertEqual(len(found['relations'])+found['relationsOmitted'],500)
        else:
            self.assertEqual(found['reason'],'extraction-output-limit')

class AdvisoryTriageTests(unittest.TestCase):
    def test_conflicting_literals_and_complementary_layers_are_only_candidates(self):
        from diffwitness.structure_triage import triage_captured
        import hashlib
        sources={'a.py':b'def total(value):\n    return value * 0.9 if value >= 100 else value\n',
                 'b.py':b'def total(value):\n    return value * 0.8 if value >= 120 else value\n',
                 'c.py':b'def adapter(value):\n    return total(value)\n'}
        rows=[{'path':p,'role':'production','status':'parsed','sourceSha256':hashlib.sha256(v).hexdigest()} for p,v in sources.items()]
        result=triage_captured(rows,lambda r:sources[r['path']])
        pair=next(f for f in result['findings'] if {x['path'] for x in f['locations']}=={'a.py','b.py'})
        self.assertEqual(pair['kind'],'potential-behavior-conflict')
        self.assertTrue(pair['differences']['literalValuesDiffer'])
        self.assertTrue(pair['differences']['conditionsDiffer'])
        self.assertEqual(pair['authority'],'INFERRED');self.assertEqual(pair['debt'],'NOT_MEASURED')
        self.assertIn('UNKNOWN',result['unusedCode'])

if __name__=='__main__':unittest.main()
