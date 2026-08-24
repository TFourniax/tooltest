from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from real_world_acceptance_common import (
    ROOT,
    assert_no_false_acceptance,
    assert_only_allowed_changes,
    assert_product_state,
    build_exact_consumers,
    check,
    claude_command,
    codex_command,
    command_available,
    git,
    read_json,
    real_agent_env,
    require,
    run,
    shell_command,
)

MANIFEST = ROOT / "scripts" / "real_repo_corpus_manifest.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def load_manifest() -> list[dict]:
    payload = read_json(MANIFEST)
    require(payload.get("schema") == "diffwitness.real-repo-corpus.v1", "unexpected corpus manifest schema")
    cases = payload.get("cases")
    require(isinstance(cases, list) and len(cases) >= 2, "real-repo corpus must contain at least two cases")
    seen: set[str] = set()
    required = {"id", "repository", "sha", "target", "pythonpath", "needle", "replacement", "validation", "task"}
    for case in cases:
        require(isinstance(case, dict), "corpus case must be an object")
        missing = sorted(required - set(case))
        require(not missing, f"corpus case is missing fields: {missing}")
        case_id = str(case["id"])
        require(case_id and case_id not in seen, f"duplicate/empty corpus case id: {case_id!r}")
        seen.add(case_id)
        repo = str(case["repository"])
        require(repo.startswith("https://github.com/") and repo.endswith(".git"), f"untrusted corpus repository URL: {repo}")
        require(bool(SHA_RE.fullmatch(str(case["sha"]))), f"case {case_id}: SHA must be exact 40-hex")
        target = Path(str(case["target"]))
        require(not target.is_absolute() and ".." not in target.parts, f"case {case_id}: unsafe target path")
        require(case["needle"] != case["replacement"], f"case {case_id}: mutation is a no-op")
        require(isinstance(case["pythonpath"], list) and case["pythonpath"], f"case {case_id}: pythonpath must be non-empty")
        for raw_path in case["pythonpath"]:
            python_path = Path(str(raw_path))
            require(
                str(raw_path) and not python_path.is_absolute() and ".." not in python_path.parts,
                f"case {case_id}: pythonpath entries must stay repo-relative: {raw_path!r}",
            )
    return cases


def validation_env(base_env: dict[str, str], repo: Path, case: dict) -> dict[str, str]:
    env = base_env.copy()
    # Evidence must resolve imports relative to the *current* worktree. DiffWitness executes the
    # same command in detached base/candidate sandboxes; absolute paths back to the live worktree
    # would make both variants import the candidate and destroy causal contrast.
    del repo  # kept in the signature to make the call-site contract explicit
    paths = [str(Path(str(item))) for item in case["pythonpath"]]
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def validation_command(python: Path, case: dict) -> list[str]:
    return [str(python), "-B", "-c", str(case["validation"])]


def clone_and_break(root: Path, case: dict, agent: str, python: Path, base_env: dict[str, str]) -> tuple[Path, dict[str, str], str]:
    repo = root / f"{case['id']}-{agent}"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", str(case["repository"]))
    check(["git", "fetch", "--depth", "1", "origin", str(case["sha"])], cwd=repo, timeout=180)
    git(repo, "checkout", "-q", "--detach", "FETCH_HEAD")
    require(git(repo, "rev-parse", "HEAD") == str(case["sha"]), f"{case['id']}: checkout is not pinned SHA")
    git(repo, "config", "user.email", "real-repo-corpus@diffwitness.local")
    git(repo, "config", "user.name", "DiffWitness Real Repo Corpus")

    # Do not execute repository-provided agent hooks/configuration in the controlled corpus.
    for unsafe in ("AGENTS.md", ".claude/settings.json", ".claude/settings.local.json", ".codex/config.toml"):
        require(not (repo / unsafe).exists(), f"{case['id']}: pinned corpus snapshot contains agent-control file {unsafe}")

    env = validation_env(base_env, repo, case)
    original = run(validation_command(python, case), cwd=repo, env=env, timeout=45)
    require(original.returncode == 0, f"{case['id']}: pinned upstream behavior is not green before mutation", original)

    target = repo / str(case["target"])
    require(target.is_file(), f"{case['id']}: target file is missing at pinned SHA")
    text = target.read_text(encoding="utf-8")
    needle = str(case["needle"])
    require(text.count(needle) == 1, f"{case['id']}: mutation needle is not unique at pinned SHA")
    target.write_text(text.replace(needle, str(case["replacement"]), 1), encoding="utf-8")
    git(repo, "add", str(case["target"]))
    git(repo, "commit", "-qm", "inject deterministic DiffWitness acceptance regression")

    broken = run(validation_command(python, case), cwd=repo, env=env, timeout=45)
    require(broken.returncode != 0, f"{case['id']}: injected regression did not break its behavior")
    evidence = shell_command(validation_command(python, case))
    return repo, env, evidence


def safe_failure_class(guard: subprocess.CompletedProcess[str], *, candidate_green: bool) -> str:
    text = (guard.stdout + "\n" + guard.stderr).lower()
    if "cannot start agent command" in text:
        return "agent-start-failure"
    if "agent exited with code" in text:
        return "agent-exit"
    if "proof rejected" in text:
        return "proof-rejected"
    if candidate_green:
        return "green-candidate-not-accepted"
    return "candidate-not-green"


def exercise_agent(
    case: dict,
    agent: str,
    *,
    root: Path,
    python: Path,
    idleproof: Path,
    base_env: dict[str, str],
    claude_budget: float,
) -> dict:
    repo, env, evidence = clone_and_break(root, case, agent, python, base_env)
    target = str(case["target"]).replace("\\", "/")
    certificate = root / f"{case['id']}-{agent}-certificate.json"
    prompt = (
        f"You are working in a pinned checkout of the real public project used by this acceptance lab. "
        f"{case['task']} Do not create files, do not commit, do not install dependencies, and do not change "
        f"Git, agent, DiffWitness, or IdleProof configuration. The external harness will run the behavioral check."
    )
    server_started = False
    if agent == "claude":
        claude = command_available("claude")
        version = check([claude, "--version"], cwd=repo, env=env, timeout=20)
        require(version.strip(), "Claude CLI returned no version")
        started = run([str(idleproof), "on", "--agent", "claude", "--no-open"], cwd=repo, env=env, timeout=30)
        require(started.returncode == 0, f"{case['id']}: IdleProof could not start Claude adapter", started)
        server_started = True
        agent_cmd = claude_command(claude, prompt, claude_budget)
    elif agent == "codex":
        codex = command_available("codex")
        version = check([codex, "--version"], cwd=repo, env=env, timeout=20)
        require(version.strip(), "Codex CLI returned no version")
        agent_cmd = codex_command(idleproof, prompt)
    else:
        raise ValueError(agent)

    try:
        guard = run(
            [
                str(python), "-m", "diffwitness.entry", "guard",
                "--repo", str(repo),
                "--test", evidence,
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
        post = run(validation_command(python, case), cwd=repo, env=env, timeout=45)
        candidate_green = post.returncode == 0

        if guard.returncode != 0:
            assert_no_false_acceptance(repo, guard)
            scope_clean = True
            try:
                assert_only_allowed_changes(repo, {target})
            except RuntimeError:
                scope_clean = False
            # A behaviorally correct, in-scope candidate rejected by Guard is a product failure,
            # not an agent-quality failure, and must fail the corpus gate.
            require(
                not (candidate_green and scope_clean),
                f"{case['id']}/{agent}: DiffWitness rejected a green in-scope real-repo candidate",
                guard,
            )
            return {
                "case": case["id"],
                "repository": case["repository"],
                "sha": case["sha"],
                "agent": agent,
                "accepted": False,
                "candidateGreen": candidate_green,
                "scopeClean": scope_clean,
                "failureClass": safe_failure_class(guard, candidate_green=candidate_green),
                "guardExit": guard.returncode,
            }

        require("PROOF ACCEPTED" in (guard.stdout + guard.stderr), f"{case['id']}/{agent}: Guard returned 0 without accepted proof", guard)
        require(candidate_green, f"{case['id']}/{agent}: accepted candidate is not actually behaviorally green", post)
        assert_only_allowed_changes(repo, {target})
        summary = assert_product_state(repo, idleproof, agent, env)
        require(certificate.is_file(), f"{case['id']}/{agent}: accepted real-repo change has no certificate")
        cert = read_json(certificate)
        require(bool(cert.get("certificate_id")), f"{case['id']}/{agent}: certificate has no identity")
        return {
            "case": case["id"],
            "repository": case["repository"],
            "sha": case["sha"],
            "agent": agent,
            "accepted": True,
            "candidateGreen": True,
            "scopeClean": True,
            "certificateId": cert.get("certificate_id"),
            **summary,
        }
    finally:
        if server_started:
            run([str(idleproof), "stop"], cwd=repo, env=env, timeout=15)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run authenticated agents through pinned real public repositories.")
    parser.add_argument("--idleproof-repo", required=True, type=Path)
    parser.add_argument("--agents", choices=["claude", "codex", "both"], default="both")
    parser.add_argument("--claude-budget-usd", type=float, default=float(os.environ.get("REAL_CORPUS_CLAUDE_BUDGET_USD", "2.00")))
    args = parser.parse_args(argv)
    require(0.10 <= args.claude_budget_usd <= 10.0, "Claude corpus budget must be between $0.10 and $10.00")
    idleproof_repo = args.idleproof_repo.resolve()
    require((idleproof_repo / "package.json").is_file(), "--idleproof-repo does not point to IdleProof")
    cases = load_manifest()
    selected = ["claude", "codex"] if args.agents == "both" else [args.agents]

    started = time.monotonic()
    tarball: Path | None = None
    with tempfile.TemporaryDirectory(prefix="real-repo-corpus-") as td:
        root = Path(td)
        try:
            python, idleproof, tarball = build_exact_consumers(root, idleproof_repo)
            env = real_agent_env(idleproof)
            results: list[dict] = []
            for case in cases:
                for agent in selected:
                    print(f"[real-corpus] {case['id']} / {agent}", flush=True)
                    result = exercise_agent(
                        case,
                        agent,
                        root=root,
                        python=python,
                        idleproof=idleproof,
                        base_env=env,
                        claude_budget=args.claude_budget_usd,
                    )
                    results.append(result)
                    if result["accepted"]:
                        print(f"[real-corpus] PASS · {case['id']} / {agent}", flush=True)
                    else:
                        print(
                            f"[real-corpus] AGENT-NO-ACCEPT · {case['id']} / {agent} · "
                            f"candidateGreen={str(result['candidateGreen']).lower()} · "
                            f"scopeClean={str(result['scopeClean']).lower()} · "
                            f"failureClass={result['failureClass']} · guardExit={result['guardExit']}",
                            flush=True,
                        )

            for case in cases:
                case_results = [r for r in results if r["case"] == case["id"]]
                require(any(r["accepted"] for r in case_results), f"{case['id']}: no real agent produced an accepted fix")
            if set(selected) == {"claude", "codex"}:
                require(any(r["accepted"] and r["agent"] == "claude" for r in results), "Claude accepted no real-repo case")
                require(any(r["accepted"] and r["agent"] == "codex" for r in results), "Codex accepted no real-repo case")

            output = {
                "schema": "diffwitness.real-repo-corpus-acceptance.v1",
                "ok": True,
                "durationSeconds": round(time.monotonic() - started, 2),
                "caseCount": len(cases),
                "attemptCount": len(results),
                "acceptedCount": sum(1 for r in results if r["accepted"]),
                "results": results,
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
