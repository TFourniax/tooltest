import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diffwitness.guard import _sync_idleproof_assurance


class IdleProofAttributionTests(unittest.TestCase):
    def test_automatic_bridge_passes_ide_origin_without_changing_envelope(self):
        with tempfile.TemporaryDirectory(prefix='dw-attribution-') as td:
            root=Path(td);(root/'.idleproof').mkdir()
            (root/'.idleproof/receipt.json').write_text('{}',encoding='utf-8')
            envelope=root/'envelope.json';envelope.write_bytes(b'{"synthetic":"unchanged"}')
            with patch('diffwitness.guard.shutil.which',return_value='fixture-idleproof'), patch('diffwitness.guard.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
                _sync_idleproof_assurance(root,envelope)
            self.assertEqual(run.call_args.args[0],['fixture-idleproof','portal','assurance','--envelope',str(envelope),'--source','ide','--quiet'])
            self.assertEqual(envelope.read_bytes(),b'{"synthetic":"unchanged"}')
