from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.semantic_redundancy import SemanticRedundancySensor


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init_repo(repo: Path, files: dict[str, str]) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "sensor-precision@example.com", cwd=repo)
    git("config", "user.name", "Sensor Precision Test", cwd=repo)
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


AUTH = """\
def verify_session_token(raw_token, expected_secret):
    if not raw_token:
        return False
    pieces = raw_token.split(".")
    if len(pieces) != 3:
        return False
    payload = pieces[1]
    signature = pieces[2]
    if not payload or not signature:
        return False
    normalized = signature.strip().lower()
    expected = expected_secret.strip().lower()
    if normalized != expected:
        return False
    return True
"""

UNRELATED = """\
def average_active_price(rows):
    total = 0.0
    count = 0
    for row in rows:
        if row.get("active"):
            price = row.get("price", 0.0)
            total += float(price)
            count += 1
    if count == 0:
        return 0.0
    return total / count
"""


class SemanticRedundancyPrecisionTests(unittest.TestCase):
    def test_structurally_unrelated_function_is_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init_repo(repo, {"auth.py": AUTH})
            (repo / "pricing.py").write_text(UNRELATED, encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "add unrelated pricing logic", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            result = SemanticRedundancySensor(threshold=0.85).scan_change(
                repo=repo,
                base_sha=base,
                candidate_sha=candidate,
            )
            self.assertEqual(result.signals, [])


if __name__ == "__main__":
    unittest.main()
