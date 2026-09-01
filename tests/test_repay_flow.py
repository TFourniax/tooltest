from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from diffwitness.config import load_config
from diffwitness.debt_budget import ledger_path, merged_debt_config
from diffwitness.debt_cli import debt_cli
from diffwitness.entry import main
from diffwitness.ledger import DebtLedger


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return proc.stdout.strip()


def init(repo: Path) -> str:
    git("init", "-q", cwd=repo)
    git("config", "user.email", "repay@example.com", cwd=repo)
    git("config", "user.name", "Repay Test", cwd=repo)
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / ".diffwitness.toml").write_text(
        "[diffwitness]\n"
        "stability_runs = 1\n"
        "\n[debt]\n"
        "max_total = 100\n"
        "max_per_change = 20\n",
        encoding="utf-8",
    )
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "baseline", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def test_agent_script() -> str:
    return (
        "from pathlib import Path; "
        "t=Path('tests/test_app.py'); t.parent.mkdir(exist_ok=True); "
        "t.write_text(\"import unittest\\nfrom app import add\\n\\nclass T(unittest.TestCase):\\n    def test_add(self):\\n        self.assertEqual(add(2, 3), 5)\\n\", encoding='utf-8')"
    )


class RepayFlowTests(unittest.TestCase):
    def test_repay_closes_historical_test_debt_only_after_discriminating_replay(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            base = init(repo)
            (repo / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            git("add", "app.py", cwd=repo)
            git("commit", "-q", "-m", "feature without regression test", cwd=repo)
            candidate = git("rev-parse", "HEAD", cwd=repo)

            self.assertEqual(
                debt_cli(
                    [
                        "--repo", str(repo), "--base", base, "--candidate", candidate,
                    ]
                ),
                0,
            )
            config = load_config(repo)
            ledger_file = ledger_path(repo, merged_debt_config(config.get("debt") or {}))
            ledger = DebtLedger.load(ledger_file)
            test_debt = next(
                item for item in ledger.active_items()
                if item.rule_id == "change.no-changed-test-surface"
            )
            self.assertEqual(test_debt.verification["type"], "historical-discrimination")

            command = f'"{sys.executable}" -m unittest discover -s tests -q'
            rc = main(
                [
                    "repay",
                    test_debt.debt_id,
                    "--repo", str(repo),
                    "--test", command,
                    "--",
                    sys.executable,
                    "-c",
                    test_agent_script(),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((repo / "tests/test_app.py").exists())

            final = DebtLedger.load(ledger_file)
            resolved = final.items()[test_debt.debt_id]
            self.assertEqual(resolved.status, "resolved")
            self.assertIsNotNone(resolved.resolution)
            verification = (resolved.resolution or {}).get("verification") or {}
            self.assertEqual(verification.get("type"), "historical-discrimination")
            self.assertEqual(
                verification.get("base_with_current_tests", {}).get("classification"),
                "stable-fail",
            )
            self.assertEqual(
                verification.get("candidate_with_current_tests", {}).get("classification"),
                "stable-pass",
            )

            # The independent unverified-change obligation remains open: repaying one debt must not
            # silently forgive a different historical claim.
            self.assertTrue(
                any(item.rule_id == "change.no-proof-certificate" for item in final.active_items())
            )


if __name__ == "__main__":
    unittest.main()
