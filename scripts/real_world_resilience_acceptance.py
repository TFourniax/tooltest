from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from real_world_acceptance_common import (
    assert_only_allowed_changes,
    assert_path_unchanged,
    assert_product_state,
    build_exact_consumers,
    check,
    claude_command,
    codex_command,
    command_available,
    continuity_ids,
    git,
    read_json,
    real_agent_env,
    require,
    run,
    shell_command,
    snapshot_path,
)


def write_project(repo: Path) -> None:
    shop = repo / "shop"
    shop.mkdir()
    (shop / "__init__.py").write_text("", encoding="utf-8")
    (shop / "pricing.py").write_text(
        "def apply_discount(subtotal, percent):\n"
        "    if not 0 <= percent <= 100:\n"
        "        raise ValueError('percent out of range')\n"
        "    return round(subtotal * (1 - percent / 100), 2)\n",
        encoding="utf-8",
    )
    (shop / "shipping.py").write_text(
        "def shipping_fee(express=False):\n"
        "    return 12.0 if express else 5.0\n",
        encoding="utf-8",
    )
    (shop / "receipt.py").write_text(
        "def render_receipt(total, currency='EUR'):\n"
        "    return f'{currency} {total:.2f}'\n",
        encoding="utf-8",
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_checkout.py").write_text(
        "import unittest\n"
        "from shop.pricing import apply_discount\n"
        "from shop.shipping import shipping_fee\n"
        "from shop.receipt import render_receipt\n\n"
        "class CheckoutTests(unittest.TestCase):\n"
        "    def test_discount(self):\n"
        "        self.assertEqual(apply_discount(100, 20), 80.0)\n"
        "        with self.assertRaises(ValueError):\n"
        "            apply_discount(100, 120)\n\n"
        "    def test_shipping(self):\n"
        "        self.assertEqual(shipping_fee(False), 5.0)\n"
        "        self.assertEqual(shipping_fee(True), 12.0)\n\n"
        "    def test_receipt(self):\n"
        "        self.assertEqual(render_receipt(42.5), 'EUR 42.50')\n"
        "        self.assertEqual(render_receipt(9, 'USD'), 'USD 9.00')\n",
        encoding="utf-8",
    )


def evidence_command(python: Path) -> list[str]:
    return [str(python), "-B", "-m", "unittest", "discover", "-s", "tests", "-q"]


def commit_paths(repo: Path, message: str, *paths: str) -> None:
    git(repo, "add", *paths)
    git(repo, "commit", "-qm", message)


def run_guard(
    *,
    repo: Path,
    python: Path,
    env: dict[str, str],
    agent_cmd: list[str],
    certificate: Path,
) -> None:
    guard = run(
        [
            str(python), "-m", "diffwitness.entry", "guard",
            "--repo", str(repo),
            "--test", shell_command(evidence_command(python)),
            "--policy", "strict",
            "--strategy", "exhaustive",
            "--stability-runs", "1",
            "--certificate", str(certificate),
            "--",
            *agent_cmd,
        ],
        cwd=repo,
        env=env,
        timeout=600,
    )
    require(guard.returncode == 0, "real-world resilience agent journey was not accepted", guard)
    require("PROOF ACCEPTED" in (guard.stdout + guard.stderr), "Guard returned success without visible accepted proof", guard)
    post = run(evidence_command(python), cwd=repo, env=env, timeout=45)
    require(post.returncode == 0, "accepted resilience candidate is not actually green", post)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a restarted, multi-task, dirty-worktree Claude-to-Codex acceptance journey."
    )
    parser.add_argument("--idleproof-repo", required=True, type=Path)
    parser.add_argument(
        "--claude-budget-usd",
        type=float,
        default=float(os.environ.get("REAL_RESILIENCE_CLAUDE_BUDGET_USD", "2.00")),
    )
    args = parser.parse_args(argv)
    require(0.10 <= args.claude_budget_usd <= 10.0, "Claude resilience budget must be between $0.10 and $10.00")
    idleproof_repo = args.idleproof_repo.resolve()
    require((idleproof_repo / "package.json").is_file(), "--idleproof-repo does not point to IdleProof")

    started_at = time.monotonic()
    tarball: Path | None = None
    with tempfile.TemporaryDirectory(prefix="real-world-resilience-") as td:
        root = Path(td)
        try:
            python, idleproof, tarball = build_exact_consumers(root, idleproof_repo)
            env = real_agent_env(idleproof)
            repo = root / "customer-project"
            repo.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.email", "resilience@diffwitness.local")
            git(repo, "config", "user.name", "DiffWitness Resilience Acceptance")
            write_project(repo)
            git(repo, "add", "shop", "tests")
            git(repo, "commit", "-qm", "healthy customer project")

            # Task 1: a normal single-file Claude repair establishes a real accepted state.
            pricing = repo / "shop" / "pricing.py"
            pricing.write_text(
                "def apply_discount(subtotal, percent):\n"
                "    if not 0 <= percent <= 100:\n"
                "        raise ValueError('percent out of range')\n"
                "    return round(subtotal * (1 + percent / 100), 2)\n",
                encoding="utf-8",
            )
            commit_paths(repo, "inject discount regression", "shop/pricing.py")
            baseline1 = run(evidence_command(python), cwd=repo, env=env, timeout=45)
            require(baseline1.returncode != 0, "task 1 baseline is unexpectedly green")

            claude = command_available("claude")
            check([claude, "--version"], cwd=repo, env=env, timeout=20)
            on1 = run([str(idleproof), "on", "--agent", "claude", "--no-open"], cwd=repo, env=env, timeout=30)
            require(on1.returncode == 0, "IdleProof could not start for task 1", on1)
            cert1 = root / "task-1-certificate.json"
            prompt1 = (
                "Fix the discount regression so a 20 percent discount on 100 returns 80, while preserving the existing "
                "range validation. Change shop/pricing.py only. Do not change tests, create files, commit, install "
                "dependencies, or alter agent/DiffWitness/IdleProof configuration."
            )
            try:
                run_guard(
                    repo=repo,
                    python=python,
                    env=env,
                    agent_cmd=claude_command(claude, prompt1, args.claude_budget_usd),
                    certificate=cert1,
                )
                assert_only_allowed_changes(repo, {"shop/pricing.py"})
                state1 = assert_product_state(repo, idleproof, "claude", env)
            finally:
                run([str(idleproof), "stop"], cwd=repo, env=env, timeout=15)
            require(cert1.is_file() and read_json(cert1).get("certificate_id"), "task 1 certificate is missing")
            change1 = state1["changeId"]
            commit_paths(repo, "accept first repaired task", "shop/pricing.py")

            # A real process restart must preserve the local project state before the next task.
            restart = run([str(idleproof), "on", "--agent", "claude", "--no-open"], cwd=repo, env=env, timeout=30)
            require(restart.returncode == 0, "IdleProof could not restart on an already-used project", restart)
            stopped = run([str(idleproof), "stop"], cwd=repo, env=env, timeout=15)
            require(stopped.returncode == 0, "IdleProof did not stop cleanly after restart", stopped)

            # Task 2: two-file bug + a pre-existing untracked user note. The note must survive and
            # must not be attributed to Codex or become required evidence for the proof.
            shipping = repo / "shop" / "shipping.py"
            receipt = repo / "shop" / "receipt.py"
            shipping.write_text(
                "def shipping_fee(express=False):\n"
                "    return 5.0 if express else 12.0\n",
                encoding="utf-8",
            )
            receipt.write_text(
                "def render_receipt(total, currency='EUR'):\n"
                "    return f'{total:.2f} {currency}'\n",
                encoding="utf-8",
            )
            commit_paths(repo, "inject shipping and receipt regressions", "shop/shipping.py", "shop/receipt.py")
            baseline2 = run(evidence_command(python), cwd=repo, env=env, timeout=45)
            require(baseline2.returncode != 0, "task 2 baseline is unexpectedly green")

            user_note = repo / "LOCAL_NOTES.md"
            user_note.write_text(
                "Customer note: keep the checkout messaging concise. This file predates the agent run.\n",
                encoding="utf-8",
            )
            note_before = snapshot_path(user_note)

            codex = command_available("codex")
            check([codex, "--version"], cwd=repo, env=env, timeout=20)
            cert2 = root / "task-2-certificate.json"
            prompt2 = (
                "Fix the checkout regressions: standard shipping must cost 5, express shipping 12, and receipt strings "
                "must place the currency before the two-decimal amount. Change only shop/shipping.py and shop/receipt.py. "
                "LOCAL_NOTES.md is a pre-existing user file: do not modify or delete it. Do not change tests, create other "
                "files, commit, install dependencies, or alter agent/DiffWitness/IdleProof configuration."
            )
            run_guard(
                repo=repo,
                python=python,
                env=env,
                agent_cmd=codex_command(idleproof, prompt2),
                certificate=cert2,
            )
            assert_path_unchanged(user_note, note_before)
            assert_only_allowed_changes(
                repo,
                {"shop/shipping.py", "shop/receipt.py"},
                preexisting_paths={"LOCAL_NOTES.md"},
            )
            state2 = assert_product_state(repo, idleproof, "codex", env)
            require(cert2.is_file() and read_json(cert2).get("certificate_id"), "task 2 certificate is missing")
            change2 = state2["changeId"]
            require(change2 != change1, "second real task reused the first canonical change id")

            journal = repo / ".git" / "diffwitness" / "events.jsonl"
            require(journal.is_file(), "multi-task project has no continuity journal")
            journal_text = journal.read_text(encoding="utf-8", errors="replace")
            require(change1 in journal_text and change2 in journal_text, "continuity journal does not retain both task identities")
            ids = continuity_ids(repo)
            require(change1 in ids and change2 in ids, "structured continuity parsing lost a task identity")
            require((repo / ".git" / "diffwitness" / "state.db").is_file(), "rebuildable continuity state is missing")

            ledger = run(
                [str(python), "-m", "diffwitness.entry", "ledger", "--repo", str(repo), "status"],
                cwd=repo,
                env=env,
                timeout=45,
            )
            require(ledger.returncode == 0, "Debt Ledger integrity/status failed after two real tasks", ledger)

            output = {
                "schema": "diffwitness.real-world-resilience-acceptance.v1",
                "ok": True,
                "durationSeconds": round(time.monotonic() - started_at, 2),
                "dirtyWorktreePreserved": True,
                "restartPassed": True,
                "taskCount": 2,
                "tasks": [
                    {
                        "agent": "claude",
                        "changeId": change1,
                        "certificateId": read_json(cert1).get("certificate_id"),
                        "files": state1.get("files", []),
                        "debtPoints": state1.get("debtPoints"),
                    },
                    {
                        "agent": "codex",
                        "changeId": change2,
                        "certificateId": read_json(cert2).get("certificate_id"),
                        "files": state2.get("files", []),
                        "debtPoints": state2.get("debtPoints"),
                    },
                ],
            }
            print(json.dumps(output, indent=2))
            return 0
        finally:
            if tarball is not None:
                try:
                    tarball.unlink(missing_ok=True)
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
