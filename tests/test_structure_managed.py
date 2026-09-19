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

PACKAGES=('tree_sitter','tree_sitter_java','tree_sitter_c_sharp','tree_sitter_kotlin')
AVAILABLE=all(importlib.util.find_spec(name) is not None for name in PACKAGES)
if os.environ.get('DIFFWITNESS_REQUIRE_SYNTAX')=='1' and not AVAILABLE:
    raise RuntimeError('Java/Kotlin/C# qualification requires actual optional grammars')

JAVA='''package com.example;
import java.util.List;
import static java.util.Collections.emptyList;
public class Gateway {
    public Gateway() {}
    public void charge() { helper(); }
    public static class Inner { void café() {} }
    String bait = "void invented() {}";
    // void forged() {}
}
interface Pay { void refund(); }
record Money(int value) {}
'''
CSHARP='''global using System.Collections.Generic;
using alias = System.Text;
namespace Payments;
public class Gateway {
    public Gateway() {}
    public async Task Charge() { Helper(); }
    public class Inner { void Café() {} }
    string bait = "void Invented() {}";
    // void Forged() {}
}
public interface Pay { void Refund(); }
public record Money(int Value);
'''
KOTLIN='''package com.example
import java.util.List
import other.worker as job
class Gateway {
    fun charge() { helper() }
    class Inner {
        fun café() {}
    }
    val bait = "fun invented() {}"
    // fun forged() {}
}
object Helpers {
    fun help() {}
}
fun refund() {}
typealias Money = Int
'''
FIXTURES=[('src/Gateway.java',JAVA,'java','tree-sitter-java'),
          ('src/Gateway.cs',CSHARP,'csharp','tree-sitter-c-sharp'),
          ('src/Gateway.kt',KOTLIN,'kotlin','tree-sitter-kotlin')]

class ManagedSyntaxTests(unittest.TestCase):
    def extract(self,path,source):
        from diffwitness.structure_registry import extract_structure
        return extract_structure(path,source.encode() if isinstance(source,str) else source)

    @unittest.skipUnless(AVAILABLE,'actual optional Java/Kotlin/C# grammars not installed')
    def test_java_package_types_nested_members_and_static_imports(self):
        v=self.extract('src/Gateway.java',JAVA)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name for s in v.symbols},{'src/Gateway.java::com.example.'+name for name in
            ['Gateway','Gateway.Gateway','Gateway.charge','Gateway.Inner','Gateway.Inner.café','Pay','Pay.refund','Money']})
        self.assertEqual([i.target for i in v.imports],['java.util.List','java.util.Collections.emptyList'])

    @unittest.skipUnless(AVAILABLE,'actual optional Java/Kotlin/C# grammars not installed')
    def test_csharp_file_namespace_nested_members_and_aliases(self):
        v=self.extract('src/Gateway.cs',CSHARP)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name for s in v.symbols},{'src/Gateway.cs::Payments.'+name for name in
            ['Gateway','Gateway.Gateway','Gateway.Charge','Gateway.Inner','Gateway.Inner.Café','Pay','Pay.Refund','Money']})
        self.assertEqual([i.target for i in v.imports],['System.Collections.Generic','System.Text'])

    @unittest.skipUnless(AVAILABLE,'actual optional Java/Kotlin/C# grammars not installed')
    def test_kotlin_package_named_objects_aliases_and_decoys(self):
        v=self.extract('src/Gateway.kt',KOTLIN)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name for s in v.symbols},{'src/Gateway.kt::com.example.'+name for name in
            ['Gateway','Gateway.charge','Gateway.Inner','Gateway.Inner.café','Helpers','Helpers.help','refund','Money']})
        self.assertEqual([i.target for i in v.imports],['java.util.List','other.worker'])

    @unittest.skipUnless(AVAILABLE,'actual optional Java/Kotlin/C# grammars not installed')
    def test_actual_transport_source_binding_and_authority(self):
        from diffwitness.structure_transport import extract_request
        response=extract_request({'schema_version':'structure-request-1','files':[
            {'path':p,'content_base64':base64.b64encode(s.encode()).decode()} for p,s,_,_ in FIXTURES]})
        self.assertEqual(response['coverage'],{'files':3,'parsed':3,'unparsed':0,'unsupported':0})
        for value,(p,s,language,provider) in zip(response['files'],FIXTURES):
            self.assertEqual((value['path'],value['language'],value['provider'],value['module']),(p,language,provider,p))
            self.assertEqual(value['source_sha256'],hashlib.sha256(s.encode()).hexdigest())
            self.assertTrue(all(item['epistemic_status']=='OBSERVED' for item in value['symbols']+value['imports']))
            self.assertTrue(all(item['epistemic_status']=='INFERRED' for item in value['calls']))
            self.assertIn('Helper' if language=='csharp' else 'helper',{item['name'] for item in value['calls']})

    @unittest.skipUnless(AVAILABLE,'actual optional Java/Kotlin/C# grammars not installed')
    def test_kotlin_type_kinds_signatures_and_comment_free_import_paths(self):
        v=self.extract('a.kt','interface Pay {\n fun charge()\n}\nenum class Status { READY, DONE }\nannotation class Marker\n')
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name:s.kind for s in v.symbols},
                         {'a.kt::Pay':'interface','a.kt::Pay.charge':'method-signature','a.kt::Status':'enum','a.kt::Marker':'annotation'})
        for path,source,target in [
            ('a.java','import java /* note */ .util.*; class A {}','java.util.*'),
            ('a.cs','using static global::System.Math; namespace A /* note */ .B { class C {} }','global::System.Math'),
            ('a.kt','import kotlin.collections.*\ninterface Pay {}\n','kotlin.collections.*')]:
            value=self.extract(path,source)
            self.assertTrue(value.parsed)
            self.assertEqual([i.target for i in value.imports],[target])

    @unittest.skipUnless(AVAILABLE,'actual optional Java/Kotlin/C# grammars not installed')
    def test_raw_strings_do_not_create_declarations_but_interpolation_keeps_real_calls(self):
        fixtures=[
            ('a.java','class A { String bait = """\nclass Invented { void fake() {} }\n"""; void actual() {} }'),
            ('a.cs','class A { string bait = """class Invented { void fake() {} }"""; '
                    'string Live = $"{Helper()}"; void actual() {} }'),
            ('a.kt','class A {\n val bait = """\nclass Invented { fun fake() {} }\n"""\n'
                    ' val live = "${helper()}"\n fun actual() {}\n}\n')]
        for path,source in fixtures:
            with self.subTest(path=path):
                value=self.extract(path,source)
                self.assertTrue(value.parsed)
                self.assertEqual({s.qualified_name for s in value.symbols},{path+'::A',path+'::A.actual'})
                if not path.endswith('.java'):
                    self.assertIn('Helper' if path.endswith('.cs') else 'helper',{call.name for call in value.calls})

    def test_missing_grammar_remains_recognized_empty(self):
        for (p,s,language,provider),package in zip(FIXTURES,PACKAGES[1:]):
            with self.subTest(path=p),patch.dict(sys.modules,{package:None}):
                v=self.extract(p,s)
                self.assertEqual((v.language,v.provider),(language,provider))
                self.assertFalse(v.parsed)
                self.assertEqual((v.symbols,v.imports,v.calls),((),(),()))

    @unittest.skipUnless(AVAILABLE,'actual optional Java/Kotlin/C# grammars not installed')
    def test_errors_and_ambiguous_overloads_do_not_supply_partial_facts(self):
        for p,_,_,_ in FIXTURES:
            for source in [b'class Unfinished {',b'\xff']:
                v=self.extract(p,source)
                self.assertFalse(v.parsed)
                self.assertEqual(v.symbols,())
        overloaded=self.extract('A.java','class A { void f(int value) {} void f(String value) {} }')
        self.assertFalse(overloaded.parsed,'no arbitrary overwrite of identical name/kind keys')
        # Pinned Kotlin grammar requires a member separator before a same-line
        # closing brace; preserve explicit unparsed coverage, do not repair text.
        compact=self.extract('A.kt','class A { fun actual() {} }\n')
        self.assertFalse(compact.parsed)
        self.assertEqual(compact.symbols,())

    @unittest.skipUnless(AVAILABLE,'actual optional Java/Kotlin/C# grammars not installed')
    def test_immutable_tree_index_uses_all_three_shared_providers(self):
        from diffwitness.continuity_state import rebuild_state
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)
            def git(*args):return subprocess.check_output(['git','-C',td,*args],stderr=subprocess.PIPE).decode().strip()
            git('init','-q');git('config','user.name','Managed fixture');git('config','user.email','fixture@example.invalid')
            (repo/'src').mkdir()
            for p,s,_,_ in FIXTURES:(repo/p).write_text(s,encoding='utf-8')
            git('add','.');git('commit','-qm','syntax')
            tree=git('rev-parse','HEAD^{tree}')
            (repo/FIXTURES[0][0]).write_text('class Dirty {}',encoding='utf-8')
            state=rebuild_state(repo,include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                self.assertEqual({r[0] for r in conn.execute('select language from structure_components')},{'java','csharp','kotlin'})
                names={r[0] for r in conn.execute('select qualified_name from structure_symbols')}
                self.assertTrue(any('Gateway.charge' in name for name in names))
                self.assertFalse(any('Dirty' in name for name in names))
                self.assertEqual(conn.execute('select distinct tree_sha from structure_symbols').fetchall(),[(tree,)])

if __name__=='__main__':unittest.main()
