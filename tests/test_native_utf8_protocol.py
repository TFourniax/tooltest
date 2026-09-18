from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_plugin_context_hook as fixtures
from diffwitness.continuity_events import continuity_paths, read_project_events
from diffwitness.continuity_task_session import stable_task_id, cleanup_task_session
from diffwitness.ide_plugin import _read_payload


class NativeUtf8ProtocolTests(unittest.TestCase):
    def test_real_adapters_ignore_locale_for_native_utf8_input_and_output(self):
        import tempfile
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            repo = fixtures.PluginContextHookTests().repo(Path(td))
            prompt = 'Créer 🧪 ' + '𐐀' * 12000
            accepted = prompt[:12000]
            for name, command in (
                ('public', [sys.executable, '-m', 'diffwitness.entry', 'ide-hook', 'user-prompt-submit']),
                ('plugin', [sys.executable, str(source / 'integrations/plugin_hook.py'), 'user-prompt-submit']),
            ):
                with self.subTest(adapter=name):
                    sid = 'utf8-' + name
                    self.addCleanup(cleanup_task_session, repo, sid)
                    env = {**os.environ, 'PYTHONUTF8':'0', 'PYTHONIOENCODING':'cp1252', 'PLUGIN_ROOT':str(source)}
                    raw = json.dumps({'cwd':str(repo), 'session_id':sid, 'prompt':prompt}, ensure_ascii=False).encode('utf-8')
                    proc = subprocess.run(command, input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          cwd=repo, env=env, timeout=10)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    rendered = json.loads(proc.stdout.decode('utf-8'))['hookSpecificOutput']['additionalContext']
                    identity = stable_task_id(sid, 1, accepted)
                    self.assertIn('ACTIVE TASK ' + identity, rendered)
                    self.assertIn('Créer 🧪 𐐀', rendered)
                    event = next(e for e in read_project_events(continuity_paths(repo).events)
                                 if e['subject']['id'] == identity and e['event_type'] == 'task.recorded')
                    self.assertEqual(event['payload']['anchor_chars'], 12000)
                    self.assertEqual(event['payload']['anchor_sha256'], hashlib.sha256(accepted.encode('utf-8')).hexdigest())
                    self.assertNotIn('Créer', continuity_paths(repo).events.read_text(encoding='utf-8'))

    def test_invalid_bytes_are_not_reinterpreted_as_locale_text(self):
        stream = io.TextIOWrapper(io.BytesIO(b'{"prompt":"\xff"}'), encoding='cp1252')
        with stream, patch('sys.stdin', stream):
            self.assertEqual(_read_payload(), {})

    def test_text_streams_and_non_object_payloads_keep_existing_contract(self):
        for raw, expected in [('{"prompt":"é"}', {'prompt':'é'}), ('[]', {}), ('broken', {})]:
            with patch('sys.stdin', io.StringIO(raw)):
                self.assertEqual(_read_payload(), expected)
