from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


AVAILABLE = all(importlib.util.find_spec(name) is not None for name in
                ('tree_sitter', 'tree_sitter_javascript', 'tree_sitter_typescript'))
if os.environ.get('DIFFWITNESS_REQUIRE_SYNTAX') == '1' and not AVAILABLE:
    raise RuntimeError('syntax qualification requires all actual pinned parser packages')


class StructureSyntaxTests(unittest.TestCase):
    def extract(self, path, text):
        from diffwitness.structure_registry import extract_structure
        return extract_structure(path, text.encode() if isinstance(text, str) else text)

    def test_python_and_unknown_fallback_keep_existing_contract(self):
        from diffwitness.structure_python import extract_python
        source = b'def current(): pass\n'
        self.assertEqual(self.extract('a.py', source), extract_python('a.py', source))
        fallback = self.extract('opaque.unknown', b'\xff')
        self.assertEqual(fallback.provider, 'file-only')
        self.assertFalse(fallback.parsed)
        self.assertEqual(fallback.symbols, ())

    @unittest.skipUnless(AVAILABLE, 'optional actual JS/TS parsers not installed')
    def test_javascript_uses_syntax_not_strings_comments_or_template_text(self):
        source = '''// function invented() {}
const note = "function forged() {}";
const template = `function imaginary() {} ${helper(1)}`;
import { value } from './util.js';
export * from 'external';
export async function café(x) { return helper(x); }
export class Service { pay(x) { return x; } }
export const next = (x) => café(x);
const dynamic = import(computeTarget());
'''
        value = self.extract('src/main.js', source)
        self.assertTrue(value.parsed)
        self.assertEqual(value.source_sha256, hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual({s.qualified_name for s in value.symbols},
                         {'src/main.js::café', 'src/main.js::Service', 'src/main.js::Service.pay', 'src/main.js::next'})
        self.assertEqual([i.target for i in value.imports], ['./util.js', 'external'])
        self.assertTrue(all(s.epistemic_status == 'OBSERVED' for s in value.symbols))
        self.assertTrue(all(c.epistemic_status == 'INFERRED' for c in value.calls))
        self.assertIn('helper', {c.name for c in value.calls})
        self.assertNotIn('import', {c.name for c in value.calls})

    @unittest.skipUnless(AVAILABLE, 'optional actual JS/TS parsers not installed')
    def test_typescript_declarations_and_jsx_tsx_have_real_syntax_coverage(self):
        source = '''import type { Invoice } from './invoice';
export interface Payment { id: string }
type Key = string;
enum Status { OK }
export class Gateway<T> { async refund(value: T): Promise<T> { return value; } }
export const settle = (value: number): number => value;
'''
        value = self.extract('src/main.ts', source)
        self.assertTrue(value.parsed)
        self.assertEqual({s.kind for s in value.symbols},
                         {'interface', 'type-alias', 'enum', 'class', 'async-method', 'function'})
        for path, text in [('View.tsx', 'export const View = (x: Props) => <div>{x.name}</div>;'),
                           ('View.jsx', 'export function View(x) { return <div>{x.name}</div>; }')]:
            result = self.extract(path, text)
            self.assertTrue(result.parsed, path)
            self.assertEqual(result.symbols[0].qualified_name, path + '::View')

    def test_missing_optional_package_is_unparsed_not_heuristic_facts(self):
        with patch.dict(sys.modules, {'tree_sitter': None}):
            value = self.extract('app.ts', 'export function real() {}')
        self.assertEqual(value.language, 'typescript')
        self.assertFalse(value.parsed)
        self.assertEqual((value.symbols, value.imports, value.calls), ((), (), ()))

    @unittest.skipUnless(AVAILABLE, 'optional actual JS/TS parsers not installed')
    def test_ambient_typescript_declarations_are_observed_syntax(self):
        value = self.extract('api.d.ts', 'declare function load(): void;\nexport declare class Service { run(): void; }\n')
        self.assertTrue(value.parsed)
        self.assertEqual({symbol.qualified_name for symbol in value.symbols},
                         {'api.d.ts::load', 'api.d.ts::Service', 'api.d.ts::Service.run'})
        self.assertTrue(all(symbol.epistemic_status == 'OBSERVED' for symbol in value.symbols))
        self.assertTrue(all(symbol.local_call_name is None for symbol in value.symbols))

    def test_dotted_basename_import_resolves_only_one_supported_source(self):
        from diffwitness.structure_provider import _syntax_import_component
        self.assertEqual(_syntax_import_component('lib/main.ts', './widget.test',
                                                 {'lib/widget.test.ts': 'target'}), 'target')
        self.assertIsNone(_syntax_import_component('lib/main.ts', './widget.test',
                                                  {'lib/widget.test.ts': 'ts', 'lib/widget.test.js': 'js'}))
        self.assertIsNone(_syntax_import_component('lib/main.ts', './worker.py', {'lib/worker.py': 'python'}))

    @unittest.skipUnless(AVAILABLE, 'optional actual JS/TS parsers not installed')
    def test_malformed_encoding_syntax_and_bounds_fail_empty(self):
        from diffwitness import structure_syntax
        for source in [b'\xff', b'function good() {}\nfunction broken(', b'const note = "unterminated;',
                       b'function duplicate() {}\nfunction duplicate() {}']:
            value = self.extract('bad.js', source)
            self.assertFalse(value.parsed)
            self.assertEqual((value.symbols, value.imports, value.calls), ((), (), ()))
        with patch.object(structure_syntax, 'MAX_NODES', 2):
            value = self.extract('large.ts', 'export function f(value: string) { return value; }')
            self.assertFalse(value.parsed)
            self.assertEqual(value.symbols, ())
        slow = ''.join(f'export function fn_{index}() {{ return 1; }}\n' for index in range(1000))
        self.assertTrue(self.extract('slow.ts', slow).parsed)
        with patch.object(structure_syntax, 'MAX_PARSE_MICROS', 1):
            value = self.extract('slow.ts', slow)
            self.assertFalse(value.parsed)
            self.assertEqual(value.symbols, ())
        source = '/* é */\r\nexport function actual() {\r\n return 1;\r\n}\r\n'
        value = self.extract('lines.mjs', source)
        self.assertEqual((value.symbols[0].line, value.symbols[0].end_line), (2, 4))

    @unittest.skipUnless(AVAILABLE, 'optional actual JS/TS parsers not installed')
    def test_index_uses_immutable_tree_and_refreshes_provider_profile(self):
        from diffwitness.continuity_state import rebuild_state, ensure_state
        from diffwitness import structure_provider
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            def git(*args):
                return subprocess.check_output(['git', '-C', td, *args], stderr=subprocess.PIPE).decode().strip()
            git('init', '-q'); git('config', 'user.name', 'Syntax test'); git('config', 'user.email', 'syntax@example.invalid')
            (repo / 'main.ts').write_text('import { helper } from "./util.ts";\nexport function actual() { return helper(); }\n')
            (repo / 'util.ts').write_text('export function helper() { return 1; }\n')
            git('add', '.'); git('commit', '-qm', 'fixture')
            tree = git('rev-parse', 'HEAD^{tree}')
            (repo / 'main.ts').write_text('export function dirty() {}\n')
            state = rebuild_state(repo, include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                names = {row[0] for row in conn.execute('select qualified_name from structure_symbols')}
                self.assertIn('main.ts::actual', names)
                self.assertNotIn('main.ts::dirty', names)
                self.assertEqual(conn.execute('select distinct tree_sha from structure_symbols').fetchall(), [(tree,)])
                self.assertEqual(conn.execute("select count(*) from structure_edges where predicate='imports' and target_kind='component'").fetchone()[0], 1)
                self.assertFalse(structure_provider.structure_index_needs_refresh(repo, conn))
                conn.execute("update meta set value='outdated' where key='structure_provider_profile'")
                conn.commit()
                self.assertTrue(structure_provider.structure_index_needs_refresh(repo, conn))
            ensure_state(repo, include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                self.assertFalse(structure_provider.structure_index_needs_refresh(repo, conn))
            # A changed installed capability profile must invalidate the same
            # immutable tree, then recover when the actual parser is available.
            with patch('diffwitness.structure_registry.installed_version', return_value=None), \
                 patch('diffwitness.structure_syntax.installed_version', return_value=None):
                ensure_state(repo, include_structure=True)
                with contextlib.closing(sqlite3.connect(state)) as conn:
                    self.assertEqual(conn.execute('select count(*) from structure_symbols').fetchone()[0], 0)
                    self.assertFalse(structure_provider.structure_index_needs_refresh(repo, conn))
            ensure_state(repo, include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                self.assertGreater(conn.execute('select count(*) from structure_symbols').fetchone()[0], 0)

    @unittest.skipUnless(AVAILABLE, 'optional actual JS/TS parsers not installed')
    def test_syntax_authority_admission_and_ambiguous_import_resolution(self):
        from dataclasses import replace
        from diffwitness.structure_registry import extract_structure
        from diffwitness.structure_provider import _syntax_import_component
        source = b'export function actual() {}'
        good = self.extract('source.js', source)
        bad = replace(good, symbols=(replace(good.symbols[0], epistemic_status='VERIFIED'),))
        with patch('diffwitness.structure_registry.extract_syntax', return_value=bad), self.assertRaises(ValueError):
            extract_structure('source.js', source)
        files = {'lib/a.ts': 'typescript', 'lib/a.js': 'javascript'}
        self.assertIsNone(_syntax_import_component('lib/main.ts', './a', files))
        self.assertEqual(_syntax_import_component('lib/main.ts', './a.ts', files), 'typescript')
        self.assertIsNone(_syntax_import_component('lib/main.ts', '../../escape', files))


if __name__ == '__main__':
    unittest.main()
