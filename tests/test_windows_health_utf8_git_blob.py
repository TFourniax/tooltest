from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_cli import health_cli
from diffwitness.runner import run_command


@unittest.skipUnless(os.name == "nt", "Windows legacy-codepage regression")
class WindowsUtf8SubprocessBoundaryTests(unittest.TestCase):
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
            git("config", "user.name", "DiffWitness UTF8 Regression")
            git("config", "user.email", "utf8-regression@example.invalid")
            # U+010F encodes as C4 8F in UTF-8; 0x8F is undefined in cp1252.
            # The path stays ASCII so the contract isolates Git blob-content decoding.
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

    def test_proof_runner_preserves_utf8_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dw-runner-utf8-") as td:
            repo = Path(td)
            script = (
                "import sys; "
                "sys.stdout.buffer.write('stdout ď\\n'.encode('utf-8')); "
                "sys.stdout.flush(); "
                "sys.stderr.buffer.write('stderr ď\\n'.encode('utf-8')); "
                "sys.stderr.flush()"
            )
            command = subprocess.list2cmdline([sys.executable, "-c", script])
            result = run_command(
                command,
                cwd=repo,
                source_repo=repo,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0)
            self.assertFalse(result.timed_out)
            self.assertEqual(result.stdout_tail, "stdout ď\n")
            self.assertEqual(result.stderr_tail, "stderr ď\n")

    def test_proof_runner_keeps_non_utf8_diagnostic_bytes_reversible(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dw-runner-bytes-") as td:
            repo = Path(td)
            script = (
                "import sys; "
                "sys.stdout.buffer.write(b'raw \\xff\\n'); "
                "sys.stdout.flush()"
            )
            command = subprocess.list2cmdline([sys.executable, "-c", script])
            result = run_command(
                command,
                cwd=repo,
                source_repo=repo,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0)
            self.assertFalse(result.timed_out)
            self.assertEqual(
                result.stdout_tail.encode("utf-8", errors="surrogateescape"),
                b"raw \xff\n",
            )


if __name__ == "__main__":
    unittest.main()
