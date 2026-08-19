from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True, slots=True)
class SecurityHit:
    rule_id: str
    severity: str
    title: str
    explanation: str
    line: int
    match: str


_RULE_META: dict[str, tuple[str, str, str]] = {
    "security.dynamic-eval": (
        "critical",
        "Dynamic code execution added",
        "Dynamic evaluation expands the code-execution surface.",
    ),
    "security.os-system": (
        "high",
        "Shell execution added",
        "os.system delegates parsing to a shell and deserves explicit review.",
    ),
    "security.shell-true": (
        "high",
        "shell=True added",
        "A subprocess configured with shell=True expands command-injection exposure.",
    ),
    "security.tls-verify-disabled": (
        "critical",
        "TLS verification disabled",
        "The change appears to disable transport certificate verification.",
    ),
    "security.wildcard-cors": (
        "high",
        "Wildcard CORS added",
        "A wildcard cross-origin policy broadens which origins may access the surface.",
    ),
    "security.raw-html": (
        "medium",
        "Raw HTML sink added",
        "Raw HTML rendering is an injection-sensitive sink that deserves explicit provenance and sanitization.",
    ),
}


_NON_PYTHON_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("security.dynamic-eval", re.compile(r"\b(?:eval|exec)\s*\(")),
    ("security.os-system", re.compile(r"\bos\.system\s*\(")),
    ("security.shell-true", re.compile(r"\bshell\s*=\s*True\b")),
    (
        "security.tls-verify-disabled",
        re.compile(r"\bverify\s*=\s*False\b|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0"),
    ),
    (
        "security.wildcard-cors",
        re.compile(r"Access-Control-Allow-Origin[^\n]*\*|allow_origins\s*=\s*\[[^\]]*['\"]\*['\"]"),
    ),
    ("security.raw-html", re.compile(r"dangerouslySetInnerHTML|v-html\s*=|innerHTML\s*=")),
]


def _hit(rule_id: str, *, line: int | None, match: str) -> SecurityHit:
    severity, title, explanation = _RULE_META[rule_id]
    return SecurityHit(
        rule_id=rule_id,
        severity=severity,
        title=title,
        explanation=explanation,
        line=max(1, int(line or 1)),
        match=match,
    )


def _is_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_false(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _contains_literal(node: ast.AST, wanted: object) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == wanted
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_contains_literal(value, wanted) for value in node.elts)
    return False


def _is_os_system(func: ast.AST) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "system"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    )


def _is_dynamic_eval(func: ast.AST) -> bool:
    if isinstance(func, ast.Name):
        return func.id in {"eval", "exec"}
    return (
        isinstance(func, ast.Attribute)
        and func.attr in {"eval", "exec"}
        and isinstance(func.value, ast.Name)
        and func.value.id == "builtins"
    )


def _tls_target(target: ast.AST) -> bool:
    if isinstance(target, ast.Name):
        return target.id == "NODE_TLS_REJECT_UNAUTHORIZED"
    if isinstance(target, ast.Subscript):
        value = target.value
        if not (
            isinstance(value, ast.Attribute)
            and value.attr == "environ"
            and isinstance(value.value, ast.Name)
            and value.value.id == "os"
        ):
            return False
        key = target.slice
        return isinstance(key, ast.Constant) and key.value == "NODE_TLS_REJECT_UNAUTHORIZED"
    return False


def _tls_disabled_value(value: ast.AST) -> bool:
    return isinstance(value, ast.Constant) and value.value in {0, "0"}


class _PythonSecurityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[SecurityHit] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast visitor API
        if _is_dynamic_eval(node.func):
            self.hits.append(_hit("security.dynamic-eval", line=node.lineno, match="eval/exec(...)"))
        if _is_os_system(node.func):
            self.hits.append(_hit("security.os-system", line=node.lineno, match="os.system(...)"))
        for keyword in node.keywords:
            if keyword.arg == "shell" and _is_true(keyword.value):
                self.hits.append(_hit("security.shell-true", line=keyword.value.lineno, match="shell=True"))
            elif keyword.arg == "verify" and _is_false(keyword.value):
                self.hits.append(_hit("security.tls-verify-disabled", line=keyword.value.lineno, match="verify=False"))
            elif keyword.arg == "allow_origins" and _contains_literal(keyword.value, "*"):
                self.hits.append(_hit("security.wildcard-cors", line=keyword.value.lineno, match='allow_origins=["*"]'))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802 - ast visitor API
        if _tls_disabled_value(node.value) and any(_tls_target(target) for target in node.targets):
            self.hits.append(
                _hit(
                    "security.tls-verify-disabled",
                    line=node.lineno,
                    match="NODE_TLS_REJECT_UNAUTHORIZED=0",
                )
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802 - ast visitor API
        if node.value is not None and _tls_target(node.target) and _tls_disabled_value(node.value):
            self.hits.append(
                _hit(
                    "security.tls-verify-disabled",
                    line=node.lineno,
                    match="NODE_TLS_REJECT_UNAUTHORIZED=0",
                )
            )
        self.generic_visit(node)


def _python_hits(text: str) -> list[SecurityHit]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        # A project can contain Python syntax newer than the interpreter running DiffWitness. In
        # that case we prefer no deterministic Python security claim over falling back to raw regex
        # matching that confuses strings/comments with executable syntax.
        return []
    visitor = _PythonSecurityVisitor()
    visitor.visit(tree)
    return visitor.hits


def _regex_hits(text: str) -> list[SecurityHit]:
    hits: list[SecurityHit] = []
    for rule_id, pattern in _NON_PYTHON_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append(_hit(rule_id, line=line, match=match.group(0)))
    return hits


def scan_security_text(path: str, text: str) -> list[SecurityHit]:
    """Return deterministic security-surface hits for executable source text.

    Python is parsed structurally so signatures inside strings, regex definitions, comments and
    fixtures are not mistaken for executable vulnerabilities. Other supported source languages keep
    the existing conservative regex rules until language-specific parsers are added; callers should
    label these results narrowly and keep test files out of project-level security accounting.
    """
    if PurePosixPath(path).suffix.lower() == ".py":
        return _python_hits(text)
    return _regex_hits(text)
