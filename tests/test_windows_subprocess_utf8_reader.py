from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

from scripts.installation_resolution_acceptance import run


@unittest.skipUnless(os.name == "nt", "Windows legacy-codepage reproduction")
class WindowsSubprocessUtf8ReaderRegressionTests(unittest.TestCase):
    def test_acceptance_runner_decodes_utf8_child_output_without_locale_loss(self) -> None:
        """A UTF-8 child must not be decoded through the host's legacy Windows code page."""
        with tempfile.TemporaryDirectory(prefix="dw-utf8-reader-") as td:
            root = Path(td)
            env = {**os.environ, "PYTHONUTF8": "1"}
            # U+010F encodes as C4 8F in UTF-8. Byte 0x8F is undefined in cp1252,
            # matching the reader-thread failure observed in hosted Windows CI.
            payload = "ď\n"
            output = run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write('ď\\n'.encode('utf-8'))",
                ],
                cwd=root,
                env=env,
            )
            self.assertEqual(output, payload)


if __name__ == "__main__":
    unittest.main()
