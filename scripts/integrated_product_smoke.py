from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def check(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: float = 120.0) -> str:
    proc = run(args, cwd=cwd, env=env, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def require(condition: bool, message: str, proc: subprocess.CompletedProcess[str] | None = None) -> None:
    if condition:
        return
    detail = "" if proc is None else f"\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    raise RuntimeError(message + detail)


def git(repo: Path, *args: str) -> str:
    return check(["git", *args], cwd=repo)


def executable_in_venv(venv_dir: Path, name: str) -> Path:
    scripts = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_dir / scripts / f"{name}{suffix}"


def evidence_command(python: Path) -> str:
    parts = [str(python), "-m", "unittest", "discover", "-s", "tests", "-q"]
    return subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)


def install_exact_artifacts(root: Path, idleproof_repo: Path) -> tuple[Path, Path, Path, Path | None]:
    artifacts = root / "artifacts"
    artifacts.mkdir()
    check([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "--wheel-dir", str(artifacts)], cwd=ROOT, timeout=180)
    wheels = sorted(artifacts.glob("diffwitness-*.whl"))
    require(len(wheels) == 1, f"expected exactly one DiffWitness wheel, found {len(wheels)}")

    pyenv = root / "python-consumer"
    venv.EnvBuilder(with_pip=True, clear=True).create(pyenv)
    python = executable_in_venv(pyenv, "python")
    check([str(python), "-m", "pip", "install", "--no-deps", "--no-index", str(wheels[0])], cwd=root, timeout=120)

    npm = shutil.which("npm")
    node = shutil.which("node")
    require(bool(npm), "npm is required for the exact IdleProof artifact journey")
    require(bool(node), "node is required for the exact IdleProof artifact journey")
    packed = json.loads(check([str(npm), "pack", "--json"], cwd=idleproof_repo, timeout=120))
    require(isinstance(packed, list) and packed and packed[0].get("filename"), "npm pack did not return an IdleProof artifact")
    tarball = idleproof_repo / packed[0]["filename"]

    consumer = root / "node-consumer"
    consumer.mkdir()
    check([str(npm), "init", "-y"], cwd=consumer)
    check([str(npm), "install", "--ignore-scripts", "--no-audit", "--no-fund", str(tarball)], cwd=consumer, timeout=120)
    idleproof_bin = consumer / "node_modules" / "idleproof" / "bin" / "idleproof.mjs"
    require(idleproof_bin.is_file(), "installed IdleProof npm artifact has no CLI")
    return python, Path(str(node)), idleproof_bin, tarball


def create_idleproof_shim(root: Path, *, node: Path, idleproof_bin: Path, invocation_log: Path) -> Path:
    shim_dir = root / "shim"
    shim_dir.mkdir()
    if os.name == "nt":
        shim = shim_dir / "idleproof.cmd"
        shim.write_text(
            f'@echo off\r\necho %*>>"{invocation_log}"\r\n"{node}" "{idleproof_bin}" %*\r\n',
            encoding="utf-8",
        )
    else:
        shim = shim_dir / "idleproof"
        shim.write_text(
            "#!/usr/bin/env sh\n"
            f"printf '%s\\n' \"$*\" >> {shlex.quote(str(invocation_log))}\n"
            f"exec {shlex.quote(str(node))} {shlex.quote(str(idleproof_bin))} \"$@\"\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)
    return shim_dir


def write_agent_script(path: Path, *, mode: str) -> None:
    if mode == "fix":
        replacement = "def add(a, b):\n    return a + b\n"
        prompt = "Fix add so the regression test passes without unrelated changes"
    elif mode == "refactor":
        replacement = "def add(a, b):\n    return sum((a, b))\n"
        prompt = "Refactor add without changing its behavior"
    else:
        raise ValueError(mode)
    path.write_text(
        textwrap.dedent(
            f"""
            import json
            import os
            import subprocess
            from pathlib import Path

            project = Path(os.environ["INTEGRATED_PROJECT"])
            node = os.environ["INTEGRATED_NODE"]
            idleproof = os.environ["INTEGRATED_IDLEPROOF_BIN"]
            session = os.environ["INTEGRATED_SESSION"]

            def hook(event):
                proc = subprocess.run(
                    [node, idleproof, "hook"], cwd=project,
                    input=json.dumps({{"cwd":str(project), "session_id":session, **event}}) + "\\n",
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                if proc.returncode:
                    raise SystemExit(f"IdleProof hook failed: {{proc.returncode}}\\n{{proc.stderr}}")

            hook({{"hook_event_name":"UserPromptSubmit", "prompt":{prompt!r}}})
            hook({{"hook_event_name":"PreToolUse", "tool_name":"Edit", "tool_input":{{"file_path":str(project / "app.py")}}}})
            (project / "app.py").write_text({replacement!r}, encoding="utf-8")
            hook({{"hook_event_name":"PostToolUse", "tool_name":"Edit", "tool_input":{{"file_path":str(project / "app.py")}}}})
            hook({{"hook_event_name":"Stop"}})
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_integrated_envelope(repo: Path) -> str:
    envelope_path = repo / ".git" / "diffwitness" / "change-envelope.json"
    receipt_path = repo / ".idleproof" / "receipt.json"
    require(envelope_path.is_file(), "Guard did not persist the integrated change envelope")
    require(receipt_path.is_file(), "IdleProof did not persist its exact task receipt")
    envelope = read_json(envelope_path)
    receipt = read_json(receipt_path)
    change_id = str(envelope.get("change_id") or "")
    require(change_id.startswith("dwchg_") and len(change_id) == 30, "integrated envelope has no canonical change id")
    require(envelope.get("proof", {}).get("accepted") is True, "integrated envelope lost accepted DiffWitness proof")
    require(isinstance(envelope.get("debt", {}).get("points"), int), "integrated envelope has no bounded Debt Ledger points")
    require(isinstance(envelope.get("debt", {}).get("open_lineages"), list), "integrated envelope has no bounded debt lineage list")
    understanding = envelope.get("understanding")
    require(isinstance(understanding, dict), "exact IdleProof receipt was not correlated into the envelope")
    require(str(understanding.get("receipt_digest") or "").startswith("sha256:"), "understanding receipt is not digest-bound")
    require(envelope.get("privacy", {}).get("code_uploaded") is False, "envelope privacy boundary claims source upload")
    require(envelope.get("privacy", {}).get("contains_prompt_text") is False, "envelope privacy boundary contains prompt text")
    receipt_change = receipt.get("session", {}).get("change", {})
    require(receipt_change.get("changeId") == change_id, "IdleProof and DiffWitness did not converge on the same dwchg identity")
    receipt_proof = receipt.get("session", {}).get("proof", {})
    require(receipt_proof.get("changeId") == change_id, "IdleProof receipt proof identity diverges from exact change identity")
    return change_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exercise the exact installed IdleProof + DiffWitness + Debt Ledger golden path.")
    parser.add_argument("--idleproof-repo", required=True, type=Path)
    args = parser.parse_args(argv)
    idleproof_repo = args.idleproof_repo.resolve()
    require((idleproof_repo / "package.json").is_file(), "--idleproof-repo does not contain package.json")

    tarball: Path | None = None
    server_started = False
    with tempfile.TemporaryDirectory(prefix="integrated-product-smoke-") as td:
        root = Path(td)
        try:
            python, node, idleproof_bin, tarball = install_exact_artifacts(root, idleproof_repo)
            invocation_log = root / "idleproof-invocations.log"
            shim_dir = create_idleproof_shim(root, node=node, idleproof_bin=idleproof_bin, invocation_log=invocation_log)
            env = os.environ.copy()
            env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")

            project = root / "project"
            project.mkdir()
            git(project, "init", "-q")
            git(project, "config", "user.email", "integrated-smoke@diffwitness.local")
            git(project, "config", "user.name", "Integrated Product Smoke")
            (project / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            tests = project / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text(
                "import unittest\nfrom app import add\n\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )
            git(project, "add", "-A")
            git(project, "commit", "-qm", "buggy baseline")

            on = run([str(node), str(idleproof_bin), "on", "--agent", "claude", "--no-open"], cwd=project, env=env, timeout=20)
            require(on.returncode == 0, "IdleProof exact npm artifact did not start", on)
            server_started = True

            agent = root / "agent-fix.py"
            write_agent_script(agent, mode="fix")
            first_env = env | {
                "INTEGRATED_PROJECT": str(project),
                "INTEGRATED_NODE": str(node),
                "INTEGRATED_IDLEPROOF_BIN": str(idleproof_bin),
                "INTEGRATED_SESSION": "integrated-fix-session",
            }
            cert = root / "integrated-proof.json"
            first = run(
                [
                    str(python), "-m", "diffwitness.entry", "guard",
                    "--repo", str(project), "--test", evidence_command(python),
                    "--policy", "strict", "--strategy", "exhaustive", "--stability-runs", "1",
                    "--certificate", str(cert), "--", str(python), str(agent),
                ],
                cwd=project,
                env=first_env,
                timeout=180,
            )
            require(first.returncode == 0, "integrated exact-artifact bugfix journey was rejected", first)
            require("PROOF ACCEPTED" in (first.stdout + first.stderr), "user-visible proof acceptance is missing", first)
            first_change_id = assert_integrated_envelope(project)
            invocations = invocation_log.read_text(encoding="utf-8") if invocation_log.exists() else ""
            require("portal assurance --envelope" in invocations, "Guard never exercised the installed IdleProof assurance bridge")

            stale_receipt = read_json(project / ".idleproof" / "receipt.json")
            stale_id = stale_receipt.get("session", {}).get("change", {}).get("changeId")
            require(stale_id == first_change_id, "fixture lost the first exact receipt identity")
            agent2 = root / "agent-refactor.py"
            agent2.write_text(
                "from pathlib import Path\nPath('app.py').write_text('def add(a, b):\\n    return sum((a, b))\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            second = run(
                [
                    str(python), "-m", "diffwitness.entry", "guard",
                    "--repo", str(project), "--test", evidence_command(python),
                    "--policy", "balanced", "--strategy", "exhaustive", "--stability-runs", "1",
                    "--", str(python), str(agent2),
                ],
                cwd=project,
                env=env,
                timeout=180,
            )
            require(second.returncode == 0, "preservation change failed while testing stale IdleProof handling", second)
            require("IdleProof correlation skipped:" in second.stderr, "stale IdleProof receipt was not visibly rejected", second)
            second_envelope = read_json(project / ".git" / "diffwitness" / "change-envelope.json")
            second_id = str(second_envelope.get("change_id") or "")
            require(second_id.startswith("dwchg_") and second_id != first_change_id, "second real change reused the stale change identity")
            require(second_envelope.get("understanding") is None, "stale understanding was falsely attached to a new change")
            require(second_envelope.get("proof", {}).get("accepted") is True, "stale IdleProof incorrectly erased valid DiffWitness proof")
            require(isinstance(second_envelope.get("debt", {}).get("points"), int), "stale IdleProof incorrectly erased valid Debt Ledger evidence")

            require(cert.is_file() and read_json(cert).get("certificate_id"), "later user work rewrote or removed the original proof certificate")
            print(
                "INTEGRATED PRODUCT SMOKE PASS · exact wheel + exact npm artifact · "
                "UNDERSTAND/PROVE/OWE exact identity · assurance bridge · stale-correlation fail-safe"
            )
            return 0
        finally:
            if server_started:
                try:
                    run([str(node), str(idleproof_bin), "stop"], cwd=project, env=env, timeout=10)
                except Exception:
                    pass
            if tarball is not None:
                try:
                    tarball.unlink(missing_ok=True)
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
