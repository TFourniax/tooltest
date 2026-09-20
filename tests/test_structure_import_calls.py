from __future__ import annotations
import base64
import importlib.util
import unittest
from diffwitness.structure_registry import extract_structure
from diffwitness.structure_transport import extract_request

AVAILABLE=all(importlib.util.find_spec(x) for x in ('tree_sitter','tree_sitter_javascript','tree_sitter_typescript'))

@unittest.skipUnless(AVAILABLE,'actual JS/TS optional grammars not installed')
class ImportCallTests(unittest.TestCase):
    def extract(self,source,path='a.js'):
        value=extract_structure(path,source.encode());self.assertTrue(value.parsed);return value

    def test_static_commonjs_and_import_keyword_reuse_each_js_ts_grammar(self):
        source="const a = require('./worker.cjs');\nconst b = import('./later.mjs');\n"
        for path in ('a.js','a.jsx','a.cjs','a.mjs','a.ts','a.cts','a.mts','a.tsx'):
            with self.subTest(path=path):
                value=self.extract(source,path)
                self.assertEqual([i.target for i in value.imports],['./worker.cjs','./later.mjs'])
                self.assertEqual([(i.line,i.end_line,i.epistemic_status) for i in value.imports],[(1,1,'OBSERVED'),(2,2,'OBSERVED')])
                self.assertTrue(all(i.members is None and i.source_target is None for i in value.imports))

    def test_comments_parentheses_templates_and_import_options_have_exact_spans(self):
        source="const a=require(/* comment */ ('./café.cjs'));\r\nconst b=import(\r\n `./later.mjs`,\r\n {with:{type:'json'}}\r\n);\r\n"
        value=self.extract(source)
        self.assertEqual([i.target for i in value.imports],['./café.cjs','./later.mjs'])
        self.assertEqual([(i.line,i.end_line) for i in value.imports],[(1,1),(2,5)])

    def test_decoys_dynamic_and_loader_members_do_not_become_targets(self):
        source=r'''// require('./comment.cjs');
const text="import('./string.mjs')";
const regex=/require\(['"]fake/;
require(name); require('./' + name); require(...names); require('');
import(`./${name}.mjs`); import('./' + name); import(name);
require('./escaped\x2ecjs'); import('./escaped\u002emjs');
loader.require('./member.cjs'); require.resolve('./resolve.cjs');
'''
        self.assertEqual(self.extract(source).imports,())

    def test_shadowing_and_writes_suppress_commonjs_candidates_but_keep_keyword_import(self):
        fixtures=[
            'function require(value) {return value;}',
            'function load(require) {return require("./shadow.cjs");}',
            'const require = custom;',
            'const {require} = custom;',
            'const {load: require} = custom;',
            'const load = require => require("./shadow.cjs");',
            'try {} catch(require) {}',
            'require = custom;',
            'require ||= custom;',
            'require++;',
            'for(require of loaders) {}',
            r'const requ\u0069re = custom;',
            'eval(code);',
            'with(loader) {require("./shadow.cjs");}',
            'import {load as require} from "./loader.mjs";'
        ]
        for prefix in fixtures:
            with self.subTest(prefix=prefix):
                value=self.extract(prefix+'\nrequire("./global.cjs");\nimport("./keyword.mjs");')
                targets=[i.target for i in value.imports]
                self.assertIn('./keyword.mjs',targets)
                self.assertNotIn('./global.cjs',targets)
                self.assertNotIn('./shadow.cjs',targets)

    def test_nested_literal_keyword_reference_and_transport_authority_are_preserved(self):
        source=b'async function load() { return import("./worker.mjs"); }\n'
        for version in (1,2):
            value=extract_request({'schema_version':f'structure-request-{version}','files':[
                {'path':'a.js','content_base64':base64.b64encode(source).decode()}]})
            imports=value['files'][0]['imports'];self.assertEqual(len(imports),1)
            self.assertEqual(imports[0]['target'],'./worker.mjs');self.assertEqual(imports[0]['epistemic_status'],'OBSERVED')
            self.assertEqual(set(imports[0]),{'target','epistemic_status'} if version==1 else
                             {'target','epistemic_status','source_target','members','line','end_line'})

    def test_typescript_function_signatures_are_require_binding_barriers(self):
        for declaration in ('declare function require(path: string): unknown;',
                            'function require(path: string): unknown;'):
            with self.subTest(declaration=declaration):
                value=self.extract(declaration+'\nrequire("./custom.cjs");\nimport("./keyword.mjs");','a.ts')
                self.assertEqual([i.target for i in value.imports],['./keyword.mjs'])

    def test_escaped_direct_eval_is_an_ambiguity_barrier(self):
        for spelling in (r'\u0065val',r'e\u0076al',r'\u{65}val'):
            with self.subTest(spelling=spelling):
                source=spelling+'("var require = custom"); require("./custom.cjs"); import("./keyword.mjs");'
                value=self.extract(source)
                self.assertEqual([i.target for i in value.imports],['./keyword.mjs'])

    def test_invalid_source_stays_completely_unparsed(self):
        value=extract_structure('a.js',b'import("./worker.mjs";')
        self.assertFalse(value.parsed);self.assertEqual((value.symbols,value.imports,value.calls),((),(),()))

if __name__=='__main__':unittest.main()
