"""Backward-compatible import surface for the canonical attestation protocol.

The implementation lives in :mod:`diffwitness.attestation`. Keeping two independent certificate
hash/verifier implementations caused protocol drift, so this module intentionally contains no
certificate logic of its own.
"""

from .attestation import (
    AttestationError,
    expected_certificate_id,
    load_certificate,
    note_cli,
    verify_against_repo,
    verify_cli,
    verify_integrity,
)

__all__ = [
    "AttestationError",
    "expected_certificate_id",
    "load_certificate",
    "note_cli",
    "verify_against_repo",
    "verify_cli",
    "verify_integrity",
]
