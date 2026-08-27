from __future__ import annotations

import ast
import hashlib
import json
import posixpath
import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .debt_models import DebtSignal
from .debt_sensor import DebtSensorResult
from .diffing import is_documentation_path, is_test_path, parse_file_patches
from .gitops import diff_text, git, git_result

LAYER_BYPASS_SENSOR_ID = "layer-bypass-v1"
LAYER_BYPASS_RULE_ID = "sensor.layer-bypass"
PARALLEL_ABSTRACTION_SENSOR_ID = "parallel-abstraction-v1"
PARALLEL_ABSTRACTION_RULE_ID = "sensor.parallel-abstraction"
DEPENDENCY_SPRAW_SENSOR_ID = "dependency-sprawl-v1"
DEPENDENCY_SPRAW_RULE_ID = "sensor.dependency-sprawl"
ORPHAN_CODE_SENSOR_ID = "orphan-code-v1"
ORPHAN_CODE_RULE_ID = "sensor.orphan-code"

GRAPH_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_IMPORT_RE = re.compile(
    r"""(?:\bfrom\s*['\"]([^'\"]+)['\"]|\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)|\bimport\(\s*['\"]([^'\"]+)['\"]\s*\))"""
)

PRESENTATION_MARKERS = {
    "ui", "view", "views", "component", "components", "page", "pages", "route", "routes",
    "controller", "controllers", "handler", "handlers", "presentation",
}
SERVICE_MARKERS = {
    "service", "services", "usecase", "usecases", "use_case", "application", "domain",
    "interactor", "interactors",
}
PERSISTENCE_MARKERS = {
    "repository", "repositories", "repo", "repos", "db", "database", "storage", "persistence",
    "datasource", "data_source", "orm", "supabase", "sql",
}
ABSTRACTION_ROLES = {
    "service", "manager", "client", "repository", "repo", "store", "provider", "gateway",
    "adapter", "controller", "handler", "coordinator", "engine", "registry", "factory",
}
ENTRY_BASENAMES = {
    "__init__.py", "index.js", "index.jsx", "index.ts", "index.tsx", "main.py", "main.js",
    "main.ts", "app.py", "app.js", "app.ts", "server.py", "server.js", "server.ts",
    "config.py", "config.js", "config.ts", "settings.py", "settings.js", "settings.ts",
}

MANIFEST_NAMES = {"package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod", "composer.json"}
DEPENDENCY_FAMILIES: dict[str, dict[str, set[str]]] = {
    "npm": {
        "http-client": {"axios", "node-fetch", "got", "ky", "superagent", "undici"},
        "date-time": {"moment", "dayjs", "date-fns", "luxon"},
        "validation": {"zod", "yup", "joi", "ajv", "valibot"},
        "logging": {"winston", "pino", "bunyan"},
    },
    "python": {
        "http-client": {"requests", "httpx", "aiohttp"},
        "date-time": {"arrow", "pendulum"},
        "validation": {"pydantic", "marshmallow", "cerberus"},
        "logging": {"loguru", "structlog"},
    },
    "rust": {
        "http-client": {"reqwest", "ureq", "attohttpc"},
        "logging": {"tracing", "log", "slog"},
    },
    "go": {
        "http-client": {"github.com/go-resty/resty/v2", "github.com/hashicorp/go-retryablehttp"},
        "logging": {"go.uber.org/zap", "github.com/sirupsen/logrus", "github.com/rs/zerolog"},
    },
    "composer": {
        "http-client": {"guzzlehttp/guzzle", "symfony/http-client"},
        "logging": {"monolog/monolog", "laminas/laminas-log"},
    },
}


@dataclass(frozen=True, slots=True)
class GraphContext:
    base_paths: frozenset[str]
    candidate_paths: frozenset[str]
    base_edges: frozenset[tuple[str, str]]
    candidate_edges: frozenset[tuple[str, str]]
    base_digests: dict[str, str]
    candidate_digests: dict[str, str]
    changed_paths: frozenset[str]


def _blob_text(repo: Path, sha: str, path: str) -> str | None:
    result = git_result(repo, "show", f"{sha}:{path}")
    if result.returncode != 0 or len(result.stdout) > 768_000:
        return None
    return result.stdout


def _source_paths(repo: Path, sha: str, *, max_files: int) -> list[str]:
    raw = git(repo, "ls-tree", "-r", "--name-only", sha)
    result: list[str] = []
    for path in raw.splitlines():
        if PurePosixPath(path).suffix.lower() not in GRAPH_SUFFIXES:
            continue
        if is_test_path(path) or is_documentation_path(path):
            continue
        result.append(path)
        if len(result) >= max_files:
            break
    return result


def _path_words(path: str) -> set[str]:
    raw = path.replace("\\", "/")
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw)
    return {part.lower() for part in re.split(r"[^A-Za-z0-9]+", expanded) if part}


def _layer(path: str) -> str | None:
    words = _path_words(path)
    hits: list[str] = []
    if words & PRESENTATION_MARKERS:
        hits.append("presentation")
    if words & SERVICE_MARKERS:
        hits.append("service")
    if words & PERSISTENCE_MARKERS:
        hits.append("persistence")
    return hits[0] if len(hits) == 1 else None


def _candidate_module_paths(module: str) -> list[str]:
    stem = module.replace(".", "/").strip("/")
    candidates: list[str] = []
    for prefix in ("", "src/"):
        base = prefix + stem
        for suffix in sorted(GRAPH_SUFFIXES):
            candidates.append(base + suffix)
        candidates.append(base + "/__init__.py")
        for suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
            candidates.append(base + "/index" + suffix)
    return candidates


def _resolve_python_module(module: str, paths: set[str]) -> str | None:
    matches = [candidate for candidate in _candidate_module_paths(module) if candidate in paths]
    return matches[0] if len(matches) == 1 else None


def _resolve_relative(spec: str, source: str, paths: set[str]) -> str | None:
    if not spec.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(source), spec))
    candidates: list[str] = []
    if PurePosixPath(base).suffix.lower() in GRAPH_SUFFIXES:
        candidates.append(base)
    else:
        for suffix in sorted(GRAPH_SUFFIXES):
            candidates.append(base + suffix)
        candidates.append(base + "/__init__.py")
        for suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
            candidates.append(base + "/index" + suffix)
    matches = [candidate for candidate in candidates if candidate in paths]
    return matches[0] if len(matches) == 1 else None


def _python_import_targets(path: str, text: str, paths: set[str]) -> set[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    parent = PurePosixPath(path).parent
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _resolve_python_module(alias.name, paths)
                if target:
                    targets.add(target)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = parent
                for _ in range(max(0, node.level - 1)):
                    base = base.parent
                raw = base.as_posix()
                if node.module:
                    raw = posixpath.join(raw, node.module.replace(".", "/"))
                candidates: list[str] = []
                if raw not in {"", "."}:
                    for suffix in sorted(GRAPH_SUFFIXES):
                        candidates.append(raw + suffix)
                    candidates.append(raw + "/__init__.py")
                if not node.module:
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        child = posixpath.join(raw, alias.name.replace(".", "/"))
                        for suffix in sorted(GRAPH_SUFFIXES):
                            candidates.append(child + suffix)
                        candidates.append(child + "/__init__.py")
                matches = [candidate for candidate in candidates if candidate in paths]
                if len(matches) == 1:
                    targets.add(matches[0])
            elif node.module:
                target = _resolve_python_module(node.module, paths)
                if target:
                    targets.add(target)
    return targets


def _js_import_targets(path: str, text: str, paths: set[str]) -> set[str]:
    targets: set[str] = set()
    for match in JS_IMPORT_RE.finditer(text):
        spec = next((value for value in match.groups() if value), "")
        target = _resolve_relative(spec, path, paths)
        if target:
            targets.add(target)
    return targets


def _graph(repo: Path, sha: str, *, max_files: int) -> tuple[set[str], set[tuple[str, str]], dict[str, str]]:
    paths = set(_source_paths(repo, sha, max_files=max_files))
    edges: set[tuple[str, str]] = set()
    digests: dict[str, str] = {}
    for path in sorted(paths):
        text = _blob_text(repo, sha, path)
        if text is None:
            continue
        digests[path] = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        suffix = PurePosixPath(path).suffix.lower()
        targets = _python_import_targets(path, text, paths) if suffix == ".py" else _js_import_targets(path, text, paths)
        edges.update((path, target) for target in targets if target != path)
    return paths, edges, digests


def build_graph_context(repo: Path, *, base_sha: str, candidate_sha: str, max_files: int = 500) -> GraphContext:
    base_paths, base_edges, base_digests = _graph(repo, base_sha, max_files=max_files)
    candidate_paths, candidate_edges, candidate_digests = _graph(repo, candidate_sha, max_files=max_files)
    changed = {
        patch.path
        for patch in parse_file_patches(diff_text(repo, base_sha, candidate_sha))
        if not patch.is_test and not is_documentation_path(patch.path)
    }
    return GraphContext(
        base_paths=frozenset(base_paths),
        candidate_paths=frozenset(candidate_paths),
        base_edges=frozenset(base_edges),
        candidate_edges=frozenset(candidate_edges),
        base_digests=base_digests,
        candidate_digests=candidate_digests,
        changed_paths=frozenset(changed),
    )


def _incoming(edges: frozenset[tuple[str, str]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        result[target].add(source)
    return result


def _layer_bypass_signal(source: str, target: str, mediator_targets: list[str], *, candidate_sha: str) -> DebtSignal:
    anchor = hashlib.sha256(f"{source}\0{target}".encode("utf-8")).hexdigest()[:24]
    return DebtSignal(
        category="architecture",
        rule_id=LAYER_BYPASS_RULE_ID,
        title="Possible architectural layer bypass",
        severity="medium",
        measurement="heuristic",
        anchor=anchor,
        path=source,
        points=0,
        explanation=(
            "This presentation-layer file now imports a local persistence-layer module directly, while its historical version already depended on a service/application mediator. "
            "The direct edge may be intentional, but it can bypass validation, policy, transaction or domain boundaries that the previous route preserved."
        ),
        evidence={
            "sensor": LAYER_BYPASS_SENSOR_ID,
            "source": source,
            "new_direct_target": target,
            "historical_mediators": mediator_targets[:8],
            "candidate_sha": candidate_sha,
            "source_code_exported": False,
        },
        verification={"type": "change-rule", "sensor": LAYER_BYPASS_SENSOR_ID},
        tags=["debt-sensor", "architecture", "layer-bypass", "advisory"],
    )


def _orphan_signal(target: str, previous_importers: list[str], *, candidate_sha: str) -> DebtSignal:
    anchor = hashlib.sha256(target.encode("utf-8")).hexdigest()[:24]
    return DebtSignal(
        category="architecture",
        rule_id=ORPHAN_CODE_RULE_ID,
        title="Possible orphaned implementation after rewiring",
        severity="low",
        measurement="heuristic",
        anchor=anchor,
        path=target,
        points=0,
        explanation=(
            "This unchanged production module had local importers before the change and has none in the candidate after those importers were modified. "
            "It may be migration residue, but dynamic imports, framework discovery and external consumers are outside this static observation and must be checked before removal."
        ),
        evidence={
            "sensor": ORPHAN_CODE_SENSOR_ID,
            "path": target,
            "previous_importers": previous_importers[:12],
            "candidate_sha": candidate_sha,
            "static_import_graph_only": True,
            "source_code_exported": False,
        },
        verification={"type": "change-rule", "sensor": ORPHAN_CODE_SENSOR_ID},
        tags=["debt-sensor", "architecture", "orphan-code", "migration-residue", "advisory"],
    )


def architecture_change_results(
    context: GraphContext,
    *,
    candidate_sha: str,
    max_layer_signals: int = 20,
    max_orphan_signals: int = 20,
) -> tuple[DebtSensorResult, DebtSensorResult]:
    base_by_source: dict[str, set[str]] = defaultdict(set)
    for source, target in context.base_edges:
        base_by_source[source].add(target)

    layer_signals: list[DebtSignal] = []
    for source, target in sorted(context.candidate_edges - context.base_edges):
        if source not in context.changed_paths:
            continue
        if _layer(source) != "presentation" or _layer(target) != "persistence":
            continue
        mediators = sorted(path for path in base_by_source.get(source, set()) if _layer(path) == "service")
        if not mediators:
            continue
        layer_signals.append(_layer_bypass_signal(source, target, mediators, candidate_sha=candidate_sha))
        if len(layer_signals) >= max_layer_signals:
            break

    base_incoming = _incoming(context.base_edges)
    candidate_incoming = _incoming(context.candidate_edges)
    orphan_signals: list[DebtSignal] = []
    for target in sorted(context.base_paths & context.candidate_paths):
        previous = base_incoming.get(target, set())
        if not previous or candidate_incoming.get(target):
            continue
        if not any(importer in context.changed_paths for importer in previous):
            continue
        if context.base_digests.get(target) != context.candidate_digests.get(target):
            continue
        if PurePosixPath(target).name.lower() in ENTRY_BASENAMES:
            continue
        if len(previous) < 2 and _layer(target) not in {"service", "persistence"}:
            continue
        orphan_signals.append(_orphan_signal(target, sorted(previous), candidate_sha=candidate_sha))
        if len(orphan_signals) >= max_orphan_signals:
            break

    common_meta = {"status": "ok", "measurement": "heuristic", "points_authoritative": False, "source_code_exported": False}
    return (
        DebtSensorResult(sensor_id=LAYER_BYPASS_SENSOR_ID, signals=layer_signals, metadata={**common_meta, "scope": "change"}),
        DebtSensorResult(sensor_id=ORPHAN_CODE_SENSOR_ID, signals=orphan_signals, metadata={**common_meta, "scope": "change", "static_import_graph_only": True}),
    )


def _abstraction_roles(location: dict[str, Any]) -> set[str]:
    words = _path_words(f"{location.get('path') or ''} {location.get('name') or ''}")
    return words & ABSTRACTION_ROLES


def parallel_abstraction_from_semantic(result: DebtSensorResult, *, max_signals: int = 20) -> DebtSensorResult:
    signals: list[DebtSignal] = []
    for source in result.signals:
        evidence = source.evidence if isinstance(source.evidence, dict) else {}
        try:
            score = float(evidence.get("similarity") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score < 0.92:
            continue
        locations = evidence.get("locations")
        if not isinstance(locations, list) or len(locations) < 2:
            continue
        normalized = [item for item in locations if isinstance(item, dict)]
        if len(normalized) < 2 or len({str(item.get("path") or "") for item in normalized}) < 2:
            continue
        roles = [_abstraction_roles(item) for item in normalized]
        if any(not value for value in roles):
            continue
        derived_evidence = dict(evidence)
        derived_evidence.update({
            "sensor": PARALLEL_ABSTRACTION_SENSOR_ID,
            "derived_from_sensor": result.sensor_id,
            "abstraction_roles": [sorted(value) for value in roles],
            "source_code_exported": False,
        })
        signals.append(
            DebtSignal(
                category="architecture",
                rule_id=PARALLEL_ABSTRACTION_RULE_ID,
                title="Possible parallel architectural abstraction",
                severity="medium" if score >= 0.96 else "low",
                measurement="heuristic",
                anchor=source.anchor,
                path=source.path,
                line=source.line,
                end_line=source.end_line,
                points=0,
                explanation=(
                    "A high-confidence semantic reimplementation also sits behind abstraction-like names such as service, manager, client, repository, store or provider in separate files. "
                    "This can indicate two competing architectural entry points for the same responsibility; keep both only when the boundary is intentional."
                ),
                evidence=derived_evidence,
                verification={"type": "project-rule", "sensor": PARALLEL_ABSTRACTION_SENSOR_ID},
                tags=["debt-sensor", "architecture", "parallel-abstraction", "advisory"],
            )
        )
        if len(signals) >= max_signals:
            break
    return DebtSensorResult(
        sensor_id=PARALLEL_ABSTRACTION_SENSOR_ID,
        signals=signals,
        metadata={
            "status": "ok",
            "measurement": "heuristic",
            "derived_from": result.sensor_id,
            "points_authoritative": False,
            "source_code_exported": False,
        },
    )


def _manifest_paths(repo: Path, sha: str) -> list[str]:
    raw = git(repo, "ls-tree", "-r", "--name-only", sha)
    return [path for path in raw.splitlines() if PurePosixPath(path).name in MANIFEST_NAMES]


def _normalize_python_package(raw: str) -> str:
    value = raw.strip()
    value = re.split(r"[<>=!~;\[\s]", value, maxsplit=1)[0]
    return value.strip().lower().replace("_", "-")


def _manifest_dependencies(path: str, text: str) -> tuple[str, set[str]]:
    name = PurePosixPath(path).name
    if name == "package.json":
        value = json.loads(text)
        deps: set[str] = set()
        if isinstance(value, dict):
            for key in ("dependencies", "optionalDependencies"):
                section = value.get(key)
                if isinstance(section, dict):
                    deps.update(str(item).lower() for item in section)
        return "npm", deps
    if name == "requirements.txt":
        deps = set()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-", "git+", "http://", "https://")):
                continue
            package = _normalize_python_package(stripped)
            if package:
                deps.add(package)
        return "python", deps
    if name == "pyproject.toml":
        value = tomllib.loads(text)
        deps: set[str] = set()
        project = value.get("project") if isinstance(value, dict) else None
        if isinstance(project, dict):
            raw = project.get("dependencies")
            if isinstance(raw, list):
                deps.update(_normalize_python_package(str(item)) for item in raw if _normalize_python_package(str(item)))
        poetry = ((value.get("tool") or {}).get("poetry") or {}) if isinstance(value, dict) else {}
        if isinstance(poetry, dict):
            section = poetry.get("dependencies")
            if isinstance(section, dict):
                deps.update(str(item).lower().replace("_", "-") for item in section if str(item).lower() != "python")
        return "python", deps
    if name == "Cargo.toml":
        value = tomllib.loads(text)
        deps: set[str] = set()
        if isinstance(value, dict):
            section = value.get("dependencies")
            if isinstance(section, dict):
                deps.update(str(item).lower() for item in section)
        return "rust", deps
    if name == "go.mod":
        deps: set[str] = set()
        in_block = False
        for raw in text.splitlines():
            line = raw.strip()
            if line == "require (":
                in_block = True
                continue
            if in_block and line == ")":
                in_block = False
                continue
            if line.startswith("require "):
                line = line[len("require "):].strip()
            elif not in_block:
                continue
            if not line or line.startswith("//"):
                continue
            deps.add(line.split()[0].lower())
        return "go", deps
    if name == "composer.json":
        value = json.loads(text)
        section = value.get("require") if isinstance(value, dict) else None
        deps = {str(item).lower() for item in section} if isinstance(section, dict) else set()
        return "composer", {item for item in deps if item != "php" and not item.startswith("ext-")}
    return "unknown", set()


def _collect_dependency_groups(repo: Path, sha: str) -> dict[tuple[str, str, str], dict[str, set[str]]]:
    groups: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for path in _manifest_paths(repo, sha):
        text = _blob_text(repo, sha, path)
        if text is None:
            continue
        try:
            ecosystem, deps = _manifest_dependencies(path, text)
        except (ValueError, TypeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
            continue
        if ecosystem not in DEPENDENCY_FAMILIES:
            continue
        scope = PurePosixPath(path).parent.as_posix()
        for family, known in DEPENDENCY_FAMILIES[ecosystem].items():
            for dep in deps & known:
                groups[(scope, ecosystem, family)][dep].add(path)
    return groups


def _dependency_signal(
    key: tuple[str, str, str],
    packages: set[str],
    manifests: set[str],
    *,
    added: set[str],
    scope: str,
    candidate_sha: str,
) -> DebtSignal:
    package_scope, ecosystem, family = key
    anchor = hashlib.sha256(f"{package_scope}\0{ecosystem}\0{family}".encode("utf-8")).hexdigest()[:24]
    primary = sorted(manifests)[0] if manifests else None
    return DebtSignal(
        category="dependency",
        rule_id=DEPENDENCY_SPRAW_RULE_ID,
        title="Overlapping direct dependency family",
        severity="low",
        measurement="heuristic",
        anchor=anchor,
        path=primary,
        points=0,
        explanation=(
            f"This {ecosystem} package scope now carries multiple direct dependencies in the {family} family. "
            "Multiple libraries can be intentional, but overlapping toolchains raise upgrade, security and maintenance surface. Prefer one default when capabilities substantially overlap."
        ),
        evidence={
            "sensor": DEPENDENCY_SPRAW_SENSOR_ID,
            "scope": scope,
            "package_scope": package_scope,
            "ecosystem": ecosystem,
            "family": family,
            "packages": sorted(packages),
            "added_packages": sorted(added),
            "manifests": sorted(manifests),
            "candidate_sha": candidate_sha,
            "source_code_exported": False,
        },
        verification={"type": "project-rule", "sensor": DEPENDENCY_SPRAW_SENSOR_ID},
        tags=["debt-sensor", "dependency", "overlapping-toolchain", "advisory"],
    )


class DependencySprawlSensor:
    sensor_id = DEPENDENCY_SPRAW_SENSOR_ID

    def __init__(self, *, max_signals: int = 20) -> None:
        self.max_signals = max_signals

    def scan_change(self, *, repo: Path, base_sha: str, candidate_sha: str) -> DebtSensorResult:
        base = _collect_dependency_groups(repo, base_sha)
        candidate = _collect_dependency_groups(repo, candidate_sha)
        signals: list[DebtSignal] = []
        for key, packages_map in sorted(candidate.items()):
            packages = set(packages_map)
            if len(packages) < 2:
                continue
            previous = set(base.get(key, {}))
            added = packages - previous
            if not added or not previous:
                continue
            manifests = {path for paths in packages_map.values() for path in paths}
            signals.append(_dependency_signal(key, packages, manifests, added=added, scope="change", candidate_sha=candidate_sha))
            if len(signals) >= self.max_signals:
                break
        return DebtSensorResult(
            sensor_id=self.sensor_id,
            signals=signals,
            metadata={"status": "ok", "measurement": "heuristic", "points_authoritative": False, "source_code_exported": False},
        )

    def scan_project(self, *, repo: Path, candidate_sha: str) -> DebtSensorResult:
        candidate = _collect_dependency_groups(repo, candidate_sha)
        signals: list[DebtSignal] = []
        for key, packages_map in sorted(candidate.items()):
            packages = set(packages_map)
            if len(packages) < 2:
                continue
            manifests = {path for paths in packages_map.values() for path in paths}
            signals.append(_dependency_signal(key, packages, manifests, added=set(), scope="project", candidate_sha=candidate_sha))
            if len(signals) >= self.max_signals:
                break
        return DebtSensorResult(
            sensor_id=self.sensor_id,
            signals=signals,
            metadata={"status": "ok", "measurement": "heuristic", "points_authoritative": False, "source_code_exported": False},
        )
