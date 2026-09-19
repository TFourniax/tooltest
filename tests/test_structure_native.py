from __future__ import annotations

import base64
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
                ('tree_sitter', 'tree_sitter_go', 'tree_sitter_rust'))
if os.environ.get('DIFFWITNESS_REQUIRE_SYNTAX') == '1' and not AVAILABLE:
    raise RuntimeError('Go/Rust qualification requires actual optional grammar packages')

GO = '''package payment
import (
  "fmt"
  web "net/http"
)
type Gateway struct { Name string }
type Amount int
type Alias = string
func (g *Gateway) Charge(value int) int { return helper(value) }
func café(value int) { fmt.Println(value) }
var decoy = `func invented() {}`
// func forged() {}
'''
RUST = '''use std::collections::{HashMap, HashSet};
use crate::worker as jobs;
extern crate alloc;
pub struct Gateway { pub value: i32 }
pub enum Status { Ready, Done }
pub trait Pay { fn charge(&self); }
pub type Amount = i32;
impl Gateway { pub fn refund(&self) { helper(); } }
pub async fn café() { helper(); }
pub mod local { pub fn actual() {} }
const DECOY: &str = r#"fn invented() {}"#;
macro_rules! fake { () => { fn forged() {} } }
'''


class NativeSyntaxTests(unittest.TestCase):
    def extract(self, path, source):
        from diffwitness.structure_registry import extract_structure
        return extract_structure(path, source.encode() if isinstance(source, str) else source)

    @unittest.skipUnless(AVAILABLE, 'optional actual Go/Rust grammars not installed')
    def test_go_functions_receivers_types_and_grouped_imports(self):
        value = self.extract('src/payment.go', GO)
        self.assertTrue(value.parsed)
        self.assertEqual(value.language, 'go')
        self.assertEqual({s.qualified_name for s in value.symbols}, {
            'src/payment.go::Gateway', 'src/payment.go::Amount', 'src/payment.go::Alias',
            'src/payment.go::Gateway.Charge', 'src/payment.go::café'})
        self.assertEqual([item.target for item in value.imports], ['fmt', 'net/http'])
        self.assertTrue(all(s.epistemic_status == 'OBSERVED' for s in value.symbols))
        self.assertEqual({call.name for call in value.calls}, {'helper'})
        self.assertTrue(all(call.epistemic_status == 'INFERRED' for call in value.calls))
        commented = self.extract('a.go', 'package p\ntype Gateway[T any] struct{}\n'
                                 'func (/* decoy */ g *Gateway[T]) Charge() {}\n')
        self.assertTrue(commented.parsed)
        self.assertEqual({s.qualified_name for s in commented.symbols},
                         {'a.go::Gateway', 'a.go::Gateway.Charge'})

    @unittest.skipUnless(AVAILABLE, 'optional actual Go/Rust grammars not installed')
    def test_rust_scopes_import_groups_and_macro_decoys(self):
        value = self.extract('src/payment.rs', RUST)
        self.assertTrue(value.parsed)
        self.assertEqual(value.language, 'rust')
        names = {s.qualified_name for s in value.symbols}
        self.assertTrue({'src/payment.rs::Gateway', 'src/payment.rs::Status', 'src/payment.rs::Pay',
                         'src/payment.rs::Amount', 'src/payment.rs::Gateway.refund',
                         'src/payment.rs::café', 'src/payment.rs::local',
                         'src/payment.rs::local.actual'}.issubset(names), names)
        self.assertFalse(any('invented' in name or 'forged' in name for name in names))
        self.assertEqual([i.target for i in value.imports],
                         ['std::collections::HashMap', 'std::collections::HashSet', 'crate::worker', 'alloc'])
        self.assertTrue(all(i.epistemic_status == 'OBSERVED' for i in value.imports))

    def test_missing_grammars_preserve_recognized_empty_unparsed_coverage(self):
        for path, source, package, language in [('a.go', GO, 'tree_sitter_go', 'go'),
                                                 ('a.rs', RUST, 'tree_sitter_rust', 'rust')]:
            with self.subTest(language=language), patch.dict(sys.modules, {package: None}):
                value = self.extract(path, source)
                self.assertEqual(value.language, language)
                self.assertFalse(value.parsed)
                self.assertEqual((value.symbols, value.imports, value.calls), ((), (), ()))

    @unittest.skipUnless(AVAILABLE, 'optional actual Go/Rust grammars not installed')
    def test_malformed_syntax_encoding_and_transport_source_binding(self):
        from diffwitness.structure_transport import extract_request
        for path, source in [('a.go', b'package p\nfunc broken('), ('a.rs', b'fn broken('), ('a.go', b'\xff')]:
            value = self.extract(path, source)
            self.assertFalse(value.parsed)
            self.assertEqual(value.symbols, ())
        sources = [('a.go', GO.encode()), ('b.rs', RUST.encode())]
        response = extract_request({'schema_version': 'structure-request-1', 'files': [
            {'path': path, 'content_base64': base64.b64encode(content).decode()} for path, content in sources]})
        self.assertEqual(response['coverage'], {'files': 2, 'parsed': 2, 'unparsed': 0, 'unsupported': 0})
        for item, (path, content) in zip(response['files'], sources):
            self.assertEqual(item['path'], path)
            self.assertEqual(item['source_sha256'], hashlib.sha256(content).hexdigest())

    def test_new_suffixes_cannot_forge_javascript_local_import_resolution(self):
        from diffwitness.structure_provider import _syntax_import_component
        self.assertIsNone(_syntax_import_component('src/main.ts', './other',
                                                 {'src/other.go': 'go', 'src/other.rs': 'rust'}))
        self.assertIsNone(_syntax_import_component('src/main.ts', './other.rs', {'src/other.rs': 'rust'}))

    @unittest.skipUnless(AVAILABLE, 'optional actual Go/Rust grammars not installed')
    def test_qualified_rust_impl_and_trait_names_preserve_owner_scope(self):
        value = self.extract('a.rs', 'impl other::Gateway { fn refund() {} }\nimpl Pay for Gateway { fn charge() {} }')
        self.assertTrue(value.parsed)
        self.assertEqual({symbol.qualified_name for symbol in value.symbols},
                         {'a.rs::other::Gateway.refund', 'a.rs::Gateway as Pay.charge'})

    @unittest.skipUnless(AVAILABLE, 'optional actual Go/Rust grammars not installed')
    def test_comments_inside_rust_paths_do_not_become_names_or_dependencies(self):
        value = self.extract('a.rs', 'use std /* decoy */ ::collections::HashMap;\n'
                             'impl other /* decoy */ ::Gateway { fn refund() {} }')
        self.assertTrue(value.parsed)
        self.assertEqual([item.target for item in value.imports], ['std::collections::HashMap'])
        self.assertEqual([symbol.qualified_name for symbol in value.symbols], ['a.rs::other::Gateway.refund'])
        grouped = self.extract('a.rs', 'use std::{self, fmt as output, collections::{HashMap, HashSet}};\nuse std::collections::*;')
        self.assertEqual([item.target for item in grouped.imports],
                         ['std', 'std::fmt', 'std::collections::HashMap', 'std::collections::HashSet', 'std::collections::*'])
        unsupported = self.extract('a.rs', 'impl Pay for (A, B) { fn charge() {} }')
        self.assertTrue(unsupported.parsed)
        self.assertEqual(unsupported.symbols, (), 'do not invent A as the tuple receiver name')

    @unittest.skipUnless(AVAILABLE, 'optional actual Go/Rust grammars not installed')
    def test_parenthesized_named_receivers_preserve_methods_without_guessing_tuple_types(self):
        for path, source in [('a.go', 'package p\ntype Gateway struct{}\nfunc (g (/* note */ *Gateway)) Charge() {}'),
                             ('a.rs', 'struct Gateway; impl (/* note , */ (Gateway)) { fn charge() {} }')]:
            with self.subTest(path=path):
                value = self.extract(path, source)
                self.assertTrue(value.parsed)
                self.assertEqual({s.qualified_name for s in value.symbols},
                                 {path+'::Gateway', path+'::Gateway.'+('Charge' if path.endswith('.go') else 'charge')})
        for owner in ['(A, B)', '(A,)', '()']:
            tuple_owner = self.extract('a.rs', 'impl Pay for '+owner+' { fn charge() {} }')
            self.assertTrue(tuple_owner.parsed)
            self.assertEqual(tuple_owner.symbols, ())

    @unittest.skipUnless(AVAILABLE, 'optional actual Go/Rust grammars not installed')
    def test_index_binds_go_and_rust_facts_to_captured_tree(self):
        from diffwitness.continuity_state import rebuild_state
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            def git(*args):
                return subprocess.check_output(['git', '-C', td, *args], stderr=subprocess.PIPE).decode().strip()
            git('init', '-q'); git('config', 'user.name', 'Native syntax'); git('config', 'user.email', 'native@example.invalid')
            (repo / 'a.go').write_bytes(GO.encode()); (repo / 'b.rs').write_bytes(RUST.encode())
            git('add', '.'); git('commit', '-qm', 'native syntax')
            tree = git('rev-parse', 'HEAD^{tree}')
            (repo / 'a.go').write_text('package p\nfunc dirty() {}\n')
            state = rebuild_state(repo, include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                self.assertEqual({row[0] for row in conn.execute('select language from structure_components')}, {'go', 'rust'})
                names = {row[0] for row in conn.execute('select qualified_name from structure_symbols')}
                self.assertIn('a.go::Gateway.Charge', names)
                self.assertFalse(any('dirty' in name for name in names))
                self.assertEqual(conn.execute('select distinct tree_sha from structure_symbols').fetchall(), [(tree,)])


if __name__ == '__main__':
    unittest.main()
