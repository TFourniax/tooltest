from __future__ import annotations

import json
import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class EvidencePlan:
    command: str
    ecosystem: str
    confidence: str
    reason: str


def _package_manager(repo: Path) -> str:
    if (repo / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (repo / "yarn.lock").exists():
        return "yarn"
    if (repo / "bun.lockb").exists() or (repo / "bun.lock").exists():
        return "bun"
    return "npm"


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return []


def command_executable(command: str, *, cwd: Path | None = None) -> str | None:
    """Resolve the executable an evidence command would start, without executing evidence."""
    tokens = _split_command(command)
    if not tokens:
        return None
    executable = tokens[0]
    if os.path.sep in executable or (os.path.altsep and os.path.altsep in executable):
        base = (cwd or Path.cwd()).resolve()
        path = Path(executable).expanduser()
        if not path.is_absolute():
            path = base / path
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return None
        if not resolved.is_file():
            return None
        if os.name != "nt" and not os.access(resolved, os.X_OK):
            return None
        return str(resolved)
    return shutil.which(executable)


def command_available(command: str, *, cwd: Path | None = None) -> bool:
    return command_executable(command, cwd=cwd) is not None


def suggested_available_command(command: str) -> str | None:
    """Return one unambiguous executable-only repair suggestion without mutating project config."""
    tokens = _split_command(command)
    if not tokens:
        return None
    first = tokens[0]
    if first in {"python", "python.exe"} and not shutil.which(first):
        if shutil.which("python3"):
            tokens[0] = "python3"
            return shlex.join(tokens)
    if first == "python3" and not shutil.which(first):
        if shutil.which("python"):
            tokens[0] = "python"
            return shlex.join(tokens)
    return None


def _python_launcher() -> str:
    # Preserve the long-standing command when a `python` launcher exists.  On WSL/Linux systems
    # that expose only `python3`, generate a command that can actually start instead of a false-ready
    # `python ...` command.
    if shutil.which("python"):
        return "python"
    if shutil.which("python3"):
        return "python3"
    return "python"


def _root_unittest_files(repo: Path) -> bool:
    try:
        files = [*repo.glob("test_*.py"), *repo.glob("*_test.py")]
    except OSError:
        return False
    return any(path.is_file() for path in files)


def detect_evidence(repo: Path) -> list[EvidencePlan]:
    """Return conservative, ordered evidence commands inferred from repository metadata.

    Detection intentionally prefers explicit project scripts/configuration over guesses. Commands
    use an actually available Python launcher when one can be resolved. Metadata detection itself
    never executes the test suite.
    """
    repo = repo.resolve()
    plans: list[EvidencePlan] = []

    package_json = repo / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
            manager = _package_manager(repo)
            if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
                command = {
                    "npm": "npm test",
                    "pnpm": "pnpm test",
                    "yarn": "yarn test",
                    "bun": "bun test",
                }[manager]
                plans.append(EvidencePlan(command, "javascript", "high", "package.json defines a test script"))
            if isinstance(scripts, dict) and isinstance(scripts.get("typecheck"), str):
                command = {
                    "npm": "npm run typecheck",
                    "pnpm": "pnpm typecheck",
                    "yarn": "yarn typecheck",
                    "bun": "bun run typecheck",
                }[manager]
                plans.append(EvidencePlan(command, "javascript", "high", "package.json defines a typecheck script"))
        except (OSError, json.JSONDecodeError):
            pass

    python = _python_launcher()
    pyproject = repo / "pyproject.toml"
    pytest_markers = [repo / "pytest.ini", repo / "conftest.py"]
    pyproject_text = ""
    if pyproject.exists():
        try:
            pyproject_text = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            pass
    if any(path.exists() for path in pytest_markers) or "pytest" in pyproject_text:
        plans.append(EvidencePlan(f"{python} -m pytest -q", "python", "high", "pytest configuration/dependency detected"))
    elif (repo / "tests").is_dir():
        plans.append(EvidencePlan(f"{python} -m unittest discover -s tests -q", "python", "medium", "tests/ directory detected"))
    elif _root_unittest_files(repo):
        plans.append(
            EvidencePlan(
                f"{python} -m unittest -q",
                "python",
                "medium",
                "conventional root-level unittest test_*.py/*_test.py files detected",
            )
        )

    if (repo / "Cargo.toml").exists():
        plans.append(EvidencePlan("cargo test --quiet", "rust", "high", "Cargo.toml detected"))
    if (repo / "go.mod").exists():
        plans.append(EvidencePlan("go test ./...", "go", "high", "go.mod detected"))
    if (repo / "pom.xml").exists():
        plans.append(EvidencePlan("mvn test -q", "java", "high", "pom.xml detected"))
    if (repo / "gradlew").exists():
        plans.append(EvidencePlan("./gradlew test", "jvm", "high", "Gradle wrapper detected"))
    elif (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        plans.append(EvidencePlan("gradle test", "jvm", "medium", "Gradle build detected without wrapper"))
    if (repo / "composer.json").exists():
        plans.append(EvidencePlan("composer test", "php", "medium", "composer.json detected"))
    if (repo / "Gemfile").exists() and (repo / "spec").is_dir():
        plans.append(EvidencePlan("bundle exec rspec", "ruby", "medium", "Gemfile and spec/ detected"))

    seen: set[str] = set()
    return [plan for plan in plans if not (plan.command in seen or seen.add(plan.command))]


def default_evidence(repo: Path) -> EvidencePlan | None:
    plans = detect_evidence(repo)
    for plan in plans:
        if command_available(plan.command, cwd=repo):
            return plan
    return plans[0] if plans else None


__all__ = [
    "EvidencePlan",
    "command_available",
    "command_executable",
    "default_evidence",
    "detect_evidence",
    "suggested_available_command",
]
