from __future__ import annotations
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import test_plugin_context_hook as fixtures
from diffwitness import gitops
from diffwitness.continuity_events import continuity_paths, read_project_events
from diffwitness.continuity_task_session import cleanup_task_session
from diffwitness.ide_plugin import session_start, user_prompt_submit


class NativeResolutionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.fixture=fixtures.PluginContextHookTests()
        self.repo=self.fixture.repo(self.root);self.sid='scoped-resolution'
        self.addCleanup(cleanup_task_session,self.repo,self.sid)

    def test_native_prompt_reuses_only_repository_paths_within_one_invocation(self):
        session_start({'cwd':str(self.repo),'session_id':self.sid})
        for prompt in ('Implement partial refunds safely','continue'):
            with patch('subprocess.run',wraps=subprocess.run) as run:
                result=user_prompt_submit({'cwd':str(self.repo),'session_id':self.sid,'prompt':prompt})
            commands=[call.args[0] for call in run.call_args_list]
            roots=sum(command[1:]==['rev-parse','--show-toplevel'] for command in commands)
            common=sum(command[1:]==['rev-parse','--git-common-dir'] for command in commands)
            self.assertIn('OBJ-REFUND',result['hookSpecificOutput']['additionalContext'])
            self.assertLessEqual(roots,2);self.assertGreaterEqual(roots,1)
            self.assertEqual(common,1)
        tasks=[event for event in read_project_events(continuity_paths(self.repo).events) if event['event_type']=='task.recorded']
        self.assertEqual(len(tasks),1)

    def test_scoped_paths_are_discarded_on_exit_and_exception(self):
        scope=gitops.repository_resolution_scope
        for failure in (False,True):
            with patch.object(gitops,'_run',wraps=gitops._run) as run:
                try:
                    with scope():
                        self.assertEqual(gitops.repo_root(self.repo),self.repo.resolve())
                        self.assertEqual(gitops.repo_root(self.repo),self.repo.resolve())
                        if failure:raise RuntimeError('fixture')
                except RuntimeError:pass
                self.assertEqual(run.call_count,1)
                gitops.repo_root(self.repo);gitops.repo_root(self.repo)
                self.assertEqual(run.call_count,3)

    def test_linked_worktree_roots_are_distinct_but_journal_is_shared(self):
        linked=self.root/'linked';self.fixture.git(self.repo,'worktree','add','--detach',str(linked))
        with gitops.repository_resolution_scope():
            self.assertEqual(gitops.repo_root(self.repo),self.repo.resolve())
            self.assertEqual(gitops.repo_root(linked),linked.resolve())
            self.assertEqual(continuity_paths(self.repo).events,continuity_paths(linked).events)

    def test_a_new_scope_never_reuses_a_previous_git_resolution(self):
        with gitops.repository_resolution_scope():
            gitops.repo_root(self.repo)
        with gitops.repository_resolution_scope(), patch.object(gitops,'_run',return_value=subprocess.CompletedProcess(['git'],128,'','not a repository')):
            with self.assertRaises(gitops.GitError):gitops.repo_root(self.repo)

    def test_historical_corruption_between_prompts_cannot_reuse_advisory_memory(self):
        payload={'cwd':str(self.repo),'session_id':self.sid,'prompt':'Implement partial refunds safely'}
        first=user_prompt_submit(payload)
        self.assertIn('OBJ-REFUND',first['hookSpecificOutput']['additionalContext'])
        events=continuity_paths(self.repo).events
        raw=events.read_bytes()
        changed=raw.replace(b'Support safe partial refunds',b'Tampered objective contents')
        self.assertNotEqual(raw,changed);events.write_bytes(changed)
        result=user_prompt_submit({**payload,'prompt':'continue'})
        text=result['hookSpecificOutput']['additionalContext']
        self.assertNotIn('OBJ-REFUND',text)
        self.assertNotIn('Tampered objective contents',text)
