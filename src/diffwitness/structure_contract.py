"""Immutable, source-bound results shared by structural language providers."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

EXTRACTION_VERSION = "structure-extraction-1"


@dataclass(frozen=True)
class StructuralSymbol:
    qualified_name: str
    kind: str
    line: int
    end_line: int
    epistemic_status: str = "OBSERVED"
    local_call_name: str | None = None


@dataclass(frozen=True)
class StructuralImport:
    target: str
    epistemic_status: str = "OBSERVED"
    source_target: str | None = None
    members: tuple[str, ...] | None = None
    line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True)
class StructuralCall:
    name: str
    line: int
    epistemic_status: str = "INFERRED"


@dataclass(frozen=True)
class FileExtraction:
    path: str
    language: str
    provider: str
    source_sha256: str
    module: str
    parsed: bool
    symbols: tuple[StructuralSymbol, ...] = ()
    imports: tuple[StructuralImport, ...] = ()
    calls: tuple[StructuralCall, ...] = ()
    schema_version: str = EXTRACTION_VERSION


def validate_extraction(result: FileExtraction, path: str, content: bytes,
                        *, language: str = "python", provider: str = "python-ast") -> None:
    """Coordinator admission; a provider never allocates tree identity or Proof."""
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError("invalid structure extraction: " + message)

    def text(value: object) -> bool:
        return isinstance(value, str) and bool(value) and len(value) <= 8192

    require(type(result) is FileExtraction, "result type")
    require(result.schema_version == EXTRACTION_VERSION, "schema version")
    require(result.path == path and result.source_sha256 == hashlib.sha256(content).hexdigest(), "source binding")
    require(result.language == language and result.provider == provider, "provider binding")
    require(isinstance(result.module, str) and len(result.module) <= 8192, "module")
    require(type(result.parsed) is bool, "parse status")
    for facts in (result.symbols, result.imports, result.calls):
        require(type(facts) is tuple and len(facts) <= 100000, "fact collection")
    require(result.parsed or not (result.symbols or result.imports or result.calls), "facts from unparsed source")
    max_line = content.count(b"\n") + content.count(b"\r") - content.count(b"\r\n") + 1
    for symbol in result.symbols:
        require(type(symbol) is StructuralSymbol, "symbol type")
        require(text(symbol.qualified_name) and text(symbol.kind), "symbol name/kind")
        require(symbol.local_call_name is None or text(symbol.local_call_name), "local symbol name")
        require(isinstance(symbol.epistemic_status, str) and symbol.epistemic_status in {"OBSERVED", "INFERRED"}, "symbol authority")
        require(type(symbol.line) is int and type(symbol.end_line) is int
                and 1 <= symbol.line <= symbol.end_line <= max_line, "symbol position")
    for item in result.imports:
        require(type(item) is StructuralImport and text(item.target), "import target")
        require(isinstance(item.epistemic_status, str) and item.epistemic_status in {"OBSERVED", "INFERRED"}, "import authority")
        require(item.source_target is None or text(item.source_target), "import source target")
        require(item.members is None or (type(item.members) is tuple and len(item.members) <= 100000
                and all(text(member) for member in item.members)), "import members")
        require((item.line is None and item.end_line is None)
                or (type(item.line) is int and type(item.end_line) is int
                    and 1 <= item.line <= item.end_line <= max_line), "import position")
    for call in result.calls:
        require(type(call) is StructuralCall and text(call.name), "call target")
        require(call.epistemic_status == "INFERRED", "name-call authority")
        require(type(call.line) is int and 1 <= call.line <= max_line, "call position")
