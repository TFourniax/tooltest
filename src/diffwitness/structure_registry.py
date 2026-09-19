"""One provider selection/admission path for Git indexing and byte transport."""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath

from .structure_contract import FileExtraction, validate_extraction
from .structure_python import extract_python
from .structure_syntax import PINNED, SPECS, extract_syntax, installed_version

SUPPORTED_SUFFIXES = ('.py', *SPECS)
# Bump when extraction/resolution semantics change even with identical grammars.
PROVIDER_PROFILE = 'structure-providers-6'


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
