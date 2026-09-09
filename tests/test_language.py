"""Language is explicit presentation; all machine facts and authority stay canonical."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from diffwitness.entry import main
from diffwitness.gitops import git, git_metadata_path, snapshot_worktree
from diffwitness.language import presentation, saved_language, tr
from diffwitness.status_cli import build_project_status, render_project_status


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve()
        git(self.repo, 'init', '-q')
        self.env = patch.dict(os.environ, {'LANG':'fr_FR.UTF-8', 'LC_ALL':'fr_FR.UTF-8',
            'LANGUAGE':'fr_FR:fr', 'OS':'Windows_NT'})
        self.env.start(); self.addCleanup(self.env.stop)

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.chdir(self.repo), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = main(args)
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def test_french_environment_defaults_to_english_without_persisting_language(self):
        expected = [([], 'Guided view'), (['status'], 'One configuration step remains'),
            (['doctor'], 'Project verification is not ready yet'),
            (['setup','status'], 'Integration configured'),
            (['protect','status'], 'Live protection is off'),
            (['ledger','list'], 'No open technical obligations'),
            (['status','--view','technical'], 'TECHNICAL VIEW')]
        for args, marker in expected:
            with self.subTest(args=args):
                rc,out,err = self.invoke(args)
                self.assertIn(rc,(0,1),err)
                self.assertIn(marker,out)
                for french in ('État du projet','Prochaine étape','Vérification prête','Arbre de travail propre','Commande:'):
                    self.assertNotIn(french,out)
        self.assertFalse(git_metadata_path(self.repo,'diffwitness/ui-preferences.json').exists())

    def test_explicit_french_and_precedence_preserve_view_and_never_leak(self):
        self.assertEqual(self.invoke(['view','technical'])[0],0)
        self.assertEqual(self.invoke(['language','fr'])[0],0)
        path = git_metadata_path(self.repo,'diffwitness/ui-preferences.json')
        saved = path.read_bytes()
        self.assertEqual(json.loads(saved)['view'],'technical')
        self.assertEqual(saved_language(self.repo),'fr')
        self.assertIn('VUE TECHNIQUE',self.invoke(['status'])[1])
        self.assertIn('TECHNICAL VIEW',self.invoke(['--language','en','status'])[1])
        self.assertEqual(path.read_bytes(),saved)
        self.invoke(['view','guided'])
        self.assertEqual(saved_language(self.repo),'fr')
        self.assertIn('Il reste une étape',self.invoke(['status'])[1])
        self.assertIn('One configuration step',self.invoke(['--language=en','status'])[1])
        self.assertEqual(tr('English','Français'),'English')
        self.invoke(['language','en'])
        self.assertIn('One configuration step',self.invoke(['status'])[1])

    def test_french_human_surfaces_and_json_are_language_and_view_invariant(self):
        pairs=[(['status'],'One configuration step','Il reste une étape'),
               (['doctor'],'GUIDED CHECK-UP','CHECK-UP GUIDÉ'),
               (['setup','status'],'Verification still','Vérification encore'),
               (['protect','status'],'LIVE PROTECTION','PROTECTION LIVE')]
        for args,en,fr in pairs:
            a=self.invoke(['--language','en',*args]);b=self.invoke(['--language','fr',*args])
            self.assertEqual(a[0],b[0]);self.assertIn(en,a[1]);self.assertIn(fr,b[1])
            docs=[]
            for language in ('en','fr'):
                rc,out,err=self.invoke(['--language',language,*args,'--json'])
                docs.append((rc,json.loads(out)))
            self.assertEqual(docs[0],docs[1])
        model=build_project_status(self.repo);before=copy.deepcopy(model)
        for language in ('en','fr'):
            with presentation(language):
                for view in ('guided','technical'):
                    text=render_project_status(model,view=view)
                    self.assertIn('dw doctor',text)
                    self.assertIn('Proof',text)
                    self.assertEqual(model,before)
        self.assertFalse(model['readiness']['currentProof']['currentTreeVerified'])

    def test_same_executed_evidence_produces_identical_certificates_in_both_languages(self):
        import subprocess
        import sys
        from diffwitness import cli
        git(self.repo, 'config', 'user.name', 'Language Fixture')
        git(self.repo, 'config', 'user.email', 'language@example.invalid')
        (self.repo / 'app.py').write_bytes(b'def add(a,b):\n    return a-b\n')
        (self.repo / 'tests').mkdir()
        (self.repo / 'tests/test_app.py').write_bytes(b'import unittest\nfrom app import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2,3),5)\n')
        git(self.repo, 'add', '.'); git(self.repo, 'commit', '-qm', 'baseline')
        (self.repo / 'app.py').write_bytes(b'def add(a,b):\n    return a+b\n')
        command = subprocess.list2cmdline([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'])
        outcomes=[]
        real=cli.run_analysis
        def execute(**kwargs):
            outcome=real(**kwargs);outcomes.append(outcome);return outcome
        with tempfile.TemporaryDirectory() as output:
            cert=Path(output)/'proof.json'
            # Fix the snapshot commit too: separate WORKTREE snapshots may have different timestamps.
            candidate=snapshot_worktree(self.repo)
            args=['prove','--candidate',candidate,'--test',command,'--certificate',str(cert)]
            with patch.object(cli,'run_analysis',side_effect=execute):
                en=self.invoke(['--language','en',*args])
            self.assertEqual(en[0],0,en)
            before=json.loads(cert.read_bytes())
            self.assertEqual(outcomes[0].baseline.classification,'stable-fail')
            self.assertEqual(outcomes[0].candidate.classification,'stable-pass')
            with patch.object(cli,'run_analysis',return_value=outcomes[0]):
                fr=self.invoke(['--language','fr',*args])
            self.assertEqual(fr[0],en[0],fr)
            after=json.loads(cert.read_bytes())
            before.pop('generated_at');after.pop('generated_at')
            self.assertEqual(after,before)
            self.assertIn('counterfactual patch evidence',en[1])
            self.assertIn('preuves contrefactuelles',fr[1])

    def test_invalid_choice_and_missing_repo_do_not_save_or_leak(self):
        rc,out,err=self.invoke(['--language','de','status'])
        self.assertEqual(rc,2);self.assertIn('en or fr',err)
        with tempfile.TemporaryDirectory() as td, contextlib.chdir(td), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['--language','fr','--help']),0)
            self.assertIn('Vue guidée',out.getvalue())
        self.assertEqual(tr('English','Français'),'English')
        self.assertFalse(git_metadata_path(self.repo,'diffwitness/ui-preferences.json').exists())

    def test_native_protocol_and_agent_arguments_do_not_inherit_ui_language(self):
        self.invoke(['language','fr'])
        seen=[]
        def native(args):
            seen.append((args,tr('canonical','localisé')));return 0
        with patch('diffwitness.ide_plugin.ide_hook_cli',side_effect=native):
            self.assertEqual(self.invoke(['--language','fr','ide-hook','session-stop'])[0],0)
        self.assertEqual(seen,[(['session-stop'],'canonical')])
        with patch('diffwitness.entry._guard_with_continuity',return_value=0) as guard:
            self.invoke(['--language','fr','guard','--','agent','--language','de'])
            guard.assert_called_once_with(['--','agent','--language','de'])
