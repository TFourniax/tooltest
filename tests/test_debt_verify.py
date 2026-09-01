from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.debt_models import DebtSignal
from diffwitness.debt_verify import recheck_discrimination, recheck_mutation_necessity
from diffwitness.diffing import make_mutations, parse_file_patches
from diffwitness.gitops import diff_text
from diffwitness.ledger import LedgerItem


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode: raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init(repo: Path, files: dict[str, str]) -> str:
    git("init", "-q", cwd=repo); git("config", "user.email", "v@example.com", cwd=repo); git("config", "user.name", "V", cwd=repo)
    for name, content in files.items():
        path = repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo); git("commit", "-q", "-m", "base", cwd=repo); return git("rev-parse", "HEAD", cwd=repo)


def commit(repo: Path, message: str) -> str:
    git("add", "-A", cwd=repo); git("commit", "-q", "-m", message, cwd=repo); return git("rev-parse", "HEAD", cwd=repo)


def item_from(signal: DebtSignal) -> LedgerItem:
    return LedgerItem.from_signal(signal, timestamp="now")


class DebtVerifyTests(unittest.TestCase):
    def test_mutation_debt_resolves_when_current_tests_make_it_necessary(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init(repo, {"app.py": "def add(a,b):\n    return a+b\n\ndef label():\n    return 'calc'\n", "tests/test_app.py": "import unittest\nfrom app import add\nclass T(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n"})
            (repo / "app.py").write_text("def add(a,b):\n    return a+b\n\ndef label():\n    return 'calculator'\n", encoding="utf-8"); candidate = commit(repo, "label")
            mutations = make_mutations(parse_file_patches(diff_text(repo, base, candidate))); self.assertEqual(len(mutations), 1); mutation = mutations[0]
            signal = DebtSignal(category="evidence", rule_id="proof.unwitnessed-mutation", title="x", severity="medium", measurement="causal", anchor=mutation.id, explanation="x", path=mutation.path, verification={"type": "mutation-necessity", "mutation_patch": mutation.patch})
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            first = recheck_mutation_necessity(item_from(signal), repo=repo, current_sha=candidate, test_command=command, stability_runs=1, timeout=10, prepare_command=None, shared_paths=[])
            self.assertEqual(first.status, "open")
            (repo / "tests/test_app.py").write_text("import unittest\nfrom app import add,label\nclass T(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n def test_label(self): self.assertEqual(label(),'calculator')\n", encoding="utf-8"); current = commit(repo, "prove label")
            second = recheck_mutation_necessity(item_from(signal), repo=repo, current_sha=current, test_command=command, stability_runs=1, timeout=10, prepare_command=None, shared_paths=[])
            self.assertEqual(second.status, "resolved")

    def test_historical_test_debt_resolves_when_current_tests_discriminate_origin(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); base = init(repo, {"app.py": "def add(a,b):\n    return a-b\n"}); (repo / "app.py").write_text("def add(a,b):\n    return a+b\n", encoding="utf-8"); candidate = commit(repo, "fix")
            signal = DebtSignal(category="test", rule_id="change.no-changed-test-surface", title="x", severity="medium", measurement="deterministic", anchor="change", explanation="x", verification={"type": "historical-discrimination", "origin_base_sha": base, "origin_candidate_sha": candidate})
            tests = repo / "tests"; tests.mkdir(); (tests / "test_app.py").write_text("import unittest\nfrom app import add\nclass T(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n", encoding="utf-8"); current = commit(repo, "tests")
            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            result = recheck_discrimination(item_from(signal), repo=repo, current_sha=current, test_command=command, stability_runs=1, timeout=10, prepare_command=None, shared_paths=[])
            self.assertEqual(result.status, "resolved")


if __name__ == "__main__": unittest.main()
