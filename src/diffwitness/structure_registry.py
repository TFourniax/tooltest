"""One provider selection/admission path for Git indexing and byte transport."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath

from .structure_contract import FileExtraction, validate_extraction
from .structure_catalog import PINNED, SPECS

SUPPORTED_SUFFIXES = ('.py', *SPECS)
# Bump when extraction/resolution semantics change even with identical grammars.
PROVIDER_PROFILE = 'structure-providers-9a'



def extract_python(relative: str, content: bytes) -> FileExtraction:
    from .structure_python import extract_python as selected
    return selected(relative, content)


def extract_syntax(relative: str, content: bytes, spec: tuple[str, str, str, str]) -> FileExtraction:
    from .structure_syntax import extract_syntax as selected
    return selected(relative, content, spec)


def installed_version(distribution: str) -> str | None:
    from .structure_syntax import installed_version as selected
    return selected(distribution)


def provider_profile() -> str:
    return json.dumps({'schema': PROVIDER_PROFILE, 'python': 'python-ast',
                       'optional': {name: installed_version(name) for name in PINNED}}, sort_keys=True)


def extract_structure(path: str, content: bytes) -> FileExtraction:
    suffix = PurePosixPath(path).suffix
    if suffix == '.py':
        language, provider = 'python', 'python-ast'
        result = extract_python(path, content)
    elif suffix in SPECS:
        language, provider, _, _ = SPECS[suffix]
        result = extract_syntax(path, content, SPECS[suffix])
    else:
        language, provider = 'unknown', 'file-only'
        result = FileExtraction(path, language, provider, hashlib.sha256(content).hexdigest(), '', False)
    validate_extraction(result, path, content, language=language, provider=provider)
    return result
