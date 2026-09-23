from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
import subprocess

from diffwitness.semantic_redundancy import _source_paths, _changed_added_lines, SemanticRedundancySensor
from test_debt_sensors import git, init_repo, LEGACY, REIMPLEMENTED


class SensorNativePathTests(unittest.TestCase):
    def test_enumeration_is_exact_independent_of_git_quote_configuration(self):
        names = ["plain.py", "café.py", "with space.py"]
        if os.name != "nt":
            names += ["with\ttab.py", "with\nline.py", "literal\\name.py"]
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            candidate = init_repo(repo, {name: LEGACY for name in names})
            for quoting in ("true", "false"):
                git("config", "core.quotePath", quoting, cwd=repo)
                with self.subTest(quotePath=quoting, platform=os.name):
                    paths = _source_paths(repo, candidate, max_files=100)
                    self.assertEqual(set(paths), set(names))
                    self.assertEqual(len(paths), len(names))
                    limited = _source_paths(repo, candidate, max_files=2)
                    self.assertEqual(limited, paths[:2])

    def test_real_sensor_preserves_unicode_identity_and_advisory_authority(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"legacy.py": LEGACY})
            (repo / "réimplementation.py").write_text(REIMPLEMENTED, encoding="utf-8")
            (repo / "unrelated.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
            git("add", ".", cwd=repo)
            git("commit", "-qm", "add implementation", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)
            sensor = SemanticRedundancySensor()
            for mode in ("project", "change"):
                result = (sensor.scan_project(repo=repo, candidate_sha=candidate) if mode == "project"
                          else sensor.scan_change(repo=repo, base_sha=base, candidate_sha=candidate))
                with self.subTest(mode=mode):
                    self.assertEqual(result.metadata["scanned_files"], 3)
                    self.assertEqual(len(result.signals), 1)
                    signal = result.signals[0]
                    self.assertEqual({loc["path"] for loc in signal.evidence["locations"]},
                                     {"legacy.py", "réimplementation.py"})
                    self.assertEqual(signal.points, 0)
                    self.assertEqual(signal.measurement, "heuristic")
                    self.assertEqual(signal.introduced_by["candidate_sha"], candidate)
                    self.assertFalse(signal.evidence["source_code_exported"])

    def test_changed_lines_and_detection_keep_native_paths(self):
        names = ["with space.py", "café.py", "a b/new implementation.py"]
        if os.name != "nt":
            names += ["with\ttab.py", "with\nline.py", "literal\\name.py", 'with"quote.py']
        for name in names:
            with tempfile.TemporaryDirectory() as td:
                repo = Path(td)
                base = init_repo(repo, {"legacy.py": LEGACY, "unchanged.py": "def answer():\n    return 42\n"})
                destination = repo / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(REIMPLEMENTED, encoding="utf-8")
                git("add", ".", cwd=repo)
                git("commit", "-qm", "native addition", cwd=repo)
                candidate = git("rev-parse", "HEAD", cwd=repo)
                for quoting in ("true", "false"):
                    git("config", "core.quotePath", quoting, cwd=repo)
                    with self.subTest(path=repr(name), quotePath=quoting, phase="added"):
                        added = _changed_added_lines(repo, base, candidate)
                        self.assertEqual(set(added), {name})
                        self.assertEqual(added[name], set(range(1, len(REIMPLEMENTED.splitlines()) + 1)))
                        result = SemanticRedundancySensor().scan_change(repo=repo, base_sha=base, candidate_sha=candidate)
                        self.assertEqual(result.metadata["changed_units"], 1)
                        self.assertEqual(len(result.signals), 1)
                        self.assertEqual({x["path"] for x in result.signals[0].evidence["locations"]}, {"legacy.py", name})
                # Only the edited function's line is changed, not the whole file.
                destination.write_text(REIMPLEMENTED + "\ndef unrelated():\n    return 99\n", encoding="utf-8")
                git("add", ".", cwd=repo)
                git("commit", "-qm", "unrelated addition", cwd=repo)
                current = git("rev-parse", "HEAD", cwd=repo)
                with self.subTest(path=repr(name), phase="modified"):
                    added = _changed_added_lines(repo, candidate, current)
                    self.assertEqual(set(added), {name})
                    self.assertEqual(added[name], set(range(len(REIMPLEMENTED.splitlines()) + 1, len(destination.read_text().splitlines()) + 1)))
                    self.assertEqual(SemanticRedundancySensor().scan_change(repo=repo, base_sha=candidate, candidate_sha=current).signals, [])

    def test_limit_is_visible_in_actual_sensor_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            candidate = init_repo(repo, {"a.py": LEGACY, "b.py": REIMPLEMENTED})
            result = SemanticRedundancySensor(max_files=1).scan_project(repo=repo, candidate_sha=candidate)
            self.assertEqual(result.metadata["scanned_files"], 1)
            self.assertEqual(result.metadata["source_coverage"]["omitted_by_limit"], 1)
            self.assertFalse(result.metadata["source_coverage"]["complete"])

    def test_non_utf8_git_identity_is_explicitly_unsupported_without_an_alias(self):
        # Git objects can represent this name on every host without asking the
        # local filesystem to create a Windows-incompatible file.
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            candidate = init_repo(repo, {"good.py": LEGACY})
            blob = git("rev-parse", "HEAD:good.py", cwd=repo)
            manifest = (f"100644 blob {blob}\tgood.py\0".encode()
                        + f"100644 blob {blob}\t".encode() + b"bad\xff.py\0")
            tree = subprocess.check_output(["git", "mktree", "-z"], cwd=repo, input=manifest).decode().strip()
            candidate = subprocess.check_output(["git", "commit-tree", tree, "-p", candidate, "-m", "raw name"], cwd=repo).decode().strip()
            result = SemanticRedundancySensor().scan_project(repo=repo, candidate_sha=candidate)
            self.assertEqual(result.metadata["scanned_files"], 1)
            self.assertEqual(result.metadata["source_coverage"]["unsupported_paths"], 1)
            self.assertFalse(result.metadata["source_coverage"]["complete"])
            self.assertEqual(_source_paths(repo, candidate, max_files=10), ["good.py"])


if __name__ == "__main__":
    unittest.main()
