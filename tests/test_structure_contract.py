from __future__ import annotations

import contextlib
from dataclasses import replace
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_continuity_kernel as fixtures
from diffwitness import structure_provider as coordinator
from diffwitness.structure_contract import EXTRACTION_VERSION, validate_extraction
from diffwitness.structure_python import extract_python
from diffwitness.continuity_state import rebuild_state


SOURCE = b'from . import rules\nimport json\n\nasync def refund(value):\n    return normalize(value)\n\ndef normalize(value):\n    return value\n\nclass Service:\n    async def send(self):\n        return normalize(1)\n'


class StructureContractTests(unittest.TestCase):
    def test_python_provider_exposes_source_bound_typed_facts_and_existing_names(self):
        result = extract_python('payments/refund.py', SOURCE)
        validate_extraction(result, 'payments/refund.py', SOURCE)
        self.assertEqual(result.schema_version, EXTRACTION_VERSION)
        self.assertEqual(result.source_sha256, hashlib.sha256(SOURCE).hexdigest())
        self.assertEqual(result.module, 'payments.refund')
        self.assertTrue(result.parsed)
        self.assertEqual([(s.qualified_name,s.kind,s.line,s.epistemic_status) for s in result.symbols], [
            ('payments.refund.refund','async-function',4,'OBSERVED'),
            ('payments.refund.normalize','function',7,'OBSERVED'),
            ('payments.refund.Service','class',10,'OBSERVED'),
            ('payments.refund.Service.send','async-method',11,'OBSERVED')])
        self.assertEqual([i.target for i in result.imports], ['payments','json'])
        self.assertEqual([(c.name,c.line,c.epistemic_status) for c in result.calls], [('normalize',5,'INFERRED'),('normalize',12,'INFERRED')])

    def test_parse_failure_has_no_symbol_or_relation_claims(self):
        for content in (b'def broken(:', b'\xff'):
            with self.subTest(content=content):
                result = extract_python('broken.py', content)
                validate_extraction(result, 'broken.py', content)
                self.assertFalse(result.parsed)
                self.assertEqual((result.symbols,result.imports,result.calls), ((),(),()))

    def test_line_positions_accept_python_universal_newlines(self):
        for separator in (b'\n', b'\r\n', b'\r'):
            content = separator.join([b'class Service:', b'    def send(self):', b'        return 1', b''])
            result = extract_python('service.py', content)
            validate_extraction(result, 'service.py', content)
            self.assertEqual(result.symbols[1].line, 2)
            self.assertEqual(result.symbols[1].end_line, 3)

    def test_contract_rejects_path_digest_authority_and_invalid_positions(self):
        result = extract_python('payments/refund.py', SOURCE)
        for changed in (
            replace(result, path='other.py'), replace(result, source_sha256='0'*64),
            replace(result, schema_version='unknown'),
            replace(result, symbols=(replace(result.symbols[0],epistemic_status='VERIFIED'),)),
            replace(result, imports=(replace(result.imports[0],epistemic_status='DECLARED'),)),
            replace(result, calls=(replace(result.calls[0],epistemic_status='OBSERVED'),)),
            replace(result, symbols=(replace(result.symbols[0],line=0),)),
            replace(result, symbols=(replace(result.symbols[0],epistemic_status=[]),)),
            replace(result, parsed=False), replace(result, provider='unbound-provider'),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_extraction(changed, 'payments/refund.py', SOURCE)

    def test_invalid_provider_result_cannot_delete_previous_index(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = fixtures.ContinuityKernelTests()
            repo = fixture.repo(Path(td))
            state = rebuild_state(repo, include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                before = conn.execute('select * from structure_symbols order by symbol_id').fetchall()
                invalid = replace(extract_python('other.py', b'def bad(): pass'), source_sha256='0'*64)
                with patch.object(coordinator, 'extract_python', return_value=invalid), self.assertRaises(ValueError):
                    coordinator.refresh_structure_index(repo, conn=conn)
                self.assertEqual(conn.execute('select * from structure_symbols order by symbol_id').fetchall(), before)

    def test_missing_extraction_contract_stamp_forces_refresh_at_same_tree(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = fixtures.ContinuityKernelTests()
            repo = fixture.repo(Path(td))
            state = rebuild_state(repo, include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                self.assertFalse(coordinator.structure_index_needs_refresh(repo, conn))
                conn.execute("delete from meta where key='structure_extraction_version'")
                self.assertTrue(coordinator.structure_index_needs_refresh(repo, conn))
