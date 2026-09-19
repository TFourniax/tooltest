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

PACKAGES=('tree_sitter','tree_sitter_ruby','tree_sitter_php')
AVAILABLE=all(importlib.util.find_spec(name) is not None for name in PACKAGES)
if os.environ.get('DIFFWITNESS_REQUIRE_SYNTAX')=='1' and not AVAILABLE:
    raise RuntimeError('Ruby/PHP qualification requires actual optional grammars')

RUBY='''require "json"
require_relative "local"
module Shop
  class Gateway
    def charge(value); helper(value); end
    def self.refund(); done(); end
    bait = "def invented(); end"
    # def forged(); end
  end
end
def café(); finish(); end
'''
PHP=r'''<?php
namespace Shop\Payments;
use Vendor\Client as SDK;
use Vendor\{One, Two as Alias};
require_once 'client.php';
class Gateway { public function charge($x) { helper($x); } }
interface Port { public function refund(); }
trait Helpful { function help() {} }
enum Status { case Ready; }
function café() { finish(); }
$bait = 'function invented() {}';
// function forged() {}
'''
FIXTURES=[('src/gateway.rb',RUBY,'ruby','tree-sitter-ruby'),('src/gateway.php',PHP,'php','tree-sitter-php')]

class DynamicSyntaxTests(unittest.TestCase):
    def extract(self,path,source):
        from diffwitness.structure_registry import extract_structure
        return extract_structure(path,source.encode() if isinstance(source,str) else source)

    @unittest.skipUnless(AVAILABLE,'actual optional Ruby/PHP grammars not installed')
    def test_ruby_lexical_types_methods_and_literal_require(self):
        v=self.extract('src/gateway.rb',RUBY)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name:s.kind for s in v.symbols},{'src/gateway.rb::'+n:k for n,k in
            [('Shop','module'),('Shop.Gateway','class'),('Shop.Gateway.charge','method'),
             ('Shop.Gateway.refund','singleton-method'),('café','function')]})
        self.assertEqual([i.target for i in v.imports],['json','./local'])
        self.assertTrue({'helper','done','finish'}<={c.name for c in v.calls})

    @unittest.skipUnless(AVAILABLE,'actual optional Ruby/PHP grammars not installed')
    def test_php_namespace_types_signatures_and_grouped_use(self):
        v=self.extract('src/gateway.php',PHP)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name:s.kind for s in v.symbols},{'src/gateway.php::Shop.Payments.'+n:k for n,k in
            [('Gateway','class'),('Gateway.charge','method'),('Port','interface'),('Port.refund','method-signature'),
             ('Helpful','trait'),('Helpful.help','method'),('Status','enum'),('café','function')]})
        self.assertEqual([i.target for i in v.imports],[r'Vendor\Client',r'Vendor\One',r'Vendor\Two','client.php'])
        self.assertTrue({'helper','finish'}<={c.name for c in v.calls})

    @unittest.skipUnless(AVAILABLE,'actual optional Ruby/PHP grammars not installed')
    def test_absolute_and_sequential_namespaces_and_unresolved_receivers(self):
        ruby=self.extract('a.rb','module A\n class ::Root\n def self.ok(); end\n end\nend\ndef obj.maybe(); end\n')
        self.assertTrue(ruby.parsed)
        self.assertEqual({s.qualified_name for s in ruby.symbols},{'a.rb::A','a.rb::Root','a.rb::Root.ok'})
        php=self.extract('a.php',r'<?php namespace A { class One {} } namespace B { class Two {} } namespace { function root() {} }')
        self.assertTrue(php.parsed)
        self.assertEqual({s.qualified_name for s in php.symbols},{'a.php::A.One','a.php::B.Two','a.php::root'})
        sequential=self.extract('b.php',r'<?php namespace A; class One {} namespace B; class Two {}')
        self.assertTrue(sequential.parsed)
        self.assertEqual({s.qualified_name for s in sequential.symbols},{'b.php::A.One','b.php::B.Two'})

    @unittest.skipUnless(AVAILABLE,'actual optional Ruby/PHP grammars not installed')
    def test_heredoc_decoys_dynamic_paths_and_actual_interpolation_calls(self):
        ruby=self.extract('a.rb','bait = <<~TEXT\ndef invented(); end\n#{helper()}\nTEXT\nrequire "#{chosen}"\nrequire escaped\ndef actual(); end\n')
        self.assertTrue(ruby.parsed)
        self.assertEqual([s.qualified_name for s in ruby.symbols],['a.rb::actual'])
        self.assertEqual(ruby.imports,())
        self.assertIn('helper',{c.name for c in ruby.calls})
        php=self.extract('a.php',"<?php\n$bait = <<<'TEXT'\nfunction invented() {}\nTEXT;\ninclude $chosen;\nrequire __DIR__ . '/x.php';\nfunction actual() {}\n")
        self.assertTrue(php.parsed)
        self.assertEqual([s.qualified_name for s in php.symbols],['a.php::actual'])
        self.assertEqual(php.imports,())

    @unittest.skipUnless(AVAILABLE,'actual optional Ruby/PHP grammars not installed')
    def test_actual_transport_source_and_authority(self):
        from diffwitness.structure_transport import extract_request
        response=extract_request({'schema_version':'structure-request-1','files':[
            {'path':p,'content_base64':base64.b64encode(s.encode()).decode()} for p,s,_,_ in FIXTURES]})
        self.assertEqual(response['coverage'],{'files':2,'parsed':2,'unparsed':0,'unsupported':0})
        for value,(p,s,language,provider) in zip(response['files'],FIXTURES):
            self.assertEqual((value['path'],value['language'],value['provider'],value['module']),(p,language,provider,p))
            self.assertEqual(value['source_sha256'],hashlib.sha256(s.encode()).hexdigest())
            self.assertTrue(all(v['epistemic_status']=='OBSERVED' for v in value['symbols']+value['imports']))
            self.assertTrue(all(v['epistemic_status']=='INFERRED' for v in value['calls']))

    @unittest.skipUnless(AVAILABLE,'actual optional Ruby/PHP grammars not installed')
    def test_php_namespace_calls_do_not_bind_to_an_arbitrary_same_name(self):
        value=self.extract('a.php',r'<?php namespace A { function work() {} work(); } namespace B { function work() {} work(); }')
        self.assertTrue(value.parsed)
        self.assertEqual({s.qualified_name for s in value.symbols},{'a.php::A.work','a.php::B.work'})
        self.assertTrue(all(s.local_call_name is None for s in value.symbols),
                        'the name-only call contract has no namespace and cannot select a target')
        self.assertEqual([c.name for c in value.calls],['work','work'])
        from diffwitness.continuity_state import rebuild_state
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)
            def git(*args):return subprocess.check_output(['git','-C',td,*args],stderr=subprocess.PIPE)
            git('init','-q');git('config','user.name','Namespace fixture');git('config','user.email','fixture@example.invalid')
            (repo/'a.php').write_text(r'<?php namespace A { function work() {} work(); } namespace B { function work() {} work(); }',encoding='utf-8')
            git('add','.');git('commit','-qm','namespace calls')
            state=rebuild_state(repo,include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                self.assertEqual(conn.execute("select count(*) from structure_edges where predicate='calls-name'").fetchone()[0],0)


    def test_missing_grammars_are_recognized_empty(self):
        for (p,s,language,provider),package in zip(FIXTURES,PACKAGES[1:]):
            with self.subTest(path=p),patch.dict(sys.modules,{package:None}):
                v=self.extract(p,s)
                self.assertEqual((v.language,v.provider),(language,provider))
                self.assertFalse(v.parsed)
                self.assertEqual((v.symbols,v.imports,v.calls),((),(),()))

    @unittest.skipUnless(AVAILABLE,'actual optional Ruby/PHP grammars not installed')
    def test_invalid_utf8_syntax_and_reopened_identity_fail_closed(self):
        for p,source in [('a.rb','class A'),('a.php','<?php function unfinished(')]:
            for content in [source,b'\xff']:
                v=self.extract(p,content)
                self.assertFalse(v.parsed)
                self.assertEqual((v.symbols,v.imports,v.calls),((),(),()))
        self.assertFalse(self.extract('a.rb','class A; end\nclass A; end\n').parsed)

    @unittest.skipUnless(AVAILABLE,'actual optional Ruby/PHP grammars not installed')
    def test_immutable_git_tree_index_ignores_dirty_sources(self):
        from diffwitness.continuity_state import rebuild_state
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)
            def git(*args):return subprocess.check_output(['git','-C',td,*args],stderr=subprocess.PIPE).decode().strip()
            git('init','-q');git('config','user.name','Dynamic fixture');git('config','user.email','fixture@example.invalid')
            (repo/'src').mkdir()
            for p,s,_,_ in FIXTURES:(repo/p).write_text(s,encoding='utf-8')
            git('add','.');git('commit','-qm','syntax');tree=git('rev-parse','HEAD^{tree}')
            (repo/FIXTURES[0][0]).write_text('class Dirty; end',encoding='utf-8')
            state=rebuild_state(repo,include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                self.assertEqual({r[0]for r in conn.execute('select language from structure_components')},{'ruby','php'})
                self.assertFalse(any('Dirty' in r[0]for r in conn.execute('select qualified_name from structure_symbols')))
                self.assertEqual(conn.execute('select distinct tree_sha from structure_symbols').fetchall(),[(tree,)])

if __name__=='__main__':unittest.main()
