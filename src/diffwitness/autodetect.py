from __future__ import annotations

import json
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


def detect_evidence(repo: Path) -> list[EvidencePlan]:
    """Return conservative, ordered evidence commands inferred from repository metadata.

    Detection intentionally prefers explicit project scripts/configuration over guesses. The first
    entry is safe to use as the zero-config default; remaining entries are useful as extra lanes.
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

    pyproject = repo / "pyproject.toml"
    pytest_markers = [repo / "pytest.ini", repo / "conftest.py"]
    pyproject_text = ""
    if pyproject.exists():
        try:
            pyproject_text = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            pass
    if any(path.exists() for path in pytest_markers) or "pytest" in pyproject_text:
        plans.append(EvidencePlan("python -m pytest -q", "python", "high", "pytest configuration/dependency detected"))
    elif (repo / "tests").is_dir():
        plans.append(EvidencePlan("python -m unittest discover -s tests -q", "python", "medium", "tests/ directory detected"))

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
    return plans[0] if plans else None
