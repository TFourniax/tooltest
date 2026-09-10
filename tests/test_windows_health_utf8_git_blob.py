from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_cli import health_cli


@unittest.skipUnless(os.name == "nt", "Windows legacy-codepage reproduction")
class WindowsHealthUtf8GitBlobTests(unittest.TestCase):
    def test_health_semantic_sensor_reads_utf8_git_blob_without_degrading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dw-health-utf8-") as td:
            repo = Path(td)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", *args],
                    cwd=repo,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            git("init", "-q")
            git("config", "user.name", "DiffWitness UTF8 Reproduction")
            git("config", "user.email", "utf8-repro@example.invalid")
            # U+010F encodes as C4 8F in UTF-8; 0x8F is undefined in cp1252.
            # The path stays ASCII so the failure is specifically Git blob-content decoding.
            (repo / "app.py").write_text(
                "def describe():\n"
                "    # UTF-8 sentinel: ď\n"
                "    return 'semantic redundancy sensor should read this blob'\n",
                encoding="utf-8",
            )
            git("add", "app.py")
            git("commit", "-qm", "utf8 source fixture")

            output = repo / "health.json"
            rc = health_cli([
                "--repo", str(repo),
                "--no-record",
                "--json", str(output),
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            sensors = payload["project_scan"]["metadata"].get("debt_sensors") or {}
            semantic = sensors.get("semantic-redundancy-v1")
            self.assertIsNotNone(semantic, sensors)
            self.assertNotEqual(
                semantic.get("status"),
                "degraded",
                f"UTF-8 Git blob caused semantic sensor degradation: {semantic}",
            )


if __name__ == "__main__":
    unittest.main()
