"""An sdist must carry exactly the canonical test assets, including fixtures."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'scripts/source_distribution_smoke.py'
spec = importlib.util.spec_from_file_location('source_distribution_smoke', MODULE)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SourceDistributionInventoryTests(unittest.TestCase):
    def test_exact_inventory_rejects_extras_omissions_and_byte_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, bundle = (Path(temporary) / name for name in ('source', 'bundle'))
            (source / 'tests/fixtures').mkdir(parents=True)
            (source / 'tests/test_example.py').write_bytes(b'pass\n')
            (source / 'tests/fixtures/data.bin').write_bytes(b'\x00\xff')
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            subprocess.run(['git', 'add', 'tests'], cwd=source, check=True)
            shutil.copytree(source / 'tests', bundle / 'tests')
            smoke.verify_test_inventory(bundle, source)
            for extra in ('tests/test_stale.py', 'tests/fixtures/untracked.bin'):
                with self.subTest(extra=extra):
                    path = bundle / extra
                    path.write_bytes(b'pass\n')
                    with self.assertRaisesRegex(ValueError, 'extra='):
                        smoke.verify_test_inventory(bundle, source)
                    path.unlink()
            fixture = bundle / 'tests/fixtures/data.bin'
            fixture.unlink()
            with self.assertRaisesRegex(ValueError, 'missing='):
                smoke.verify_test_inventory(bundle, source)
            fixture.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed test asset'):
                smoke.verify_test_inventory(bundle, source)
