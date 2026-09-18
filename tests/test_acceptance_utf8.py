from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


class AcceptanceEncodingTests(unittest.TestCase):
    def test_acceptance_harnesses_preserve_utf8_subprocess_output(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("integrated_product_smoke", "real_agent_acceptance"):
            with self.subTest(harness=name):
                spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                expected = 'Mémoire → “contexte” 日本語\n'
                code = f"import sys; sys.stdout.buffer.write({expected.encode('utf-8')!r})"
                result = module.run([sys.executable, "-c", code], cwd=root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
