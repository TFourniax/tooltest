from __future__ import annotations

import base64
import contextlib
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGES=('tree_sitter','tree_sitter_sql','tree_sitter_json','tree_sitter_toml','tree_sitter_yaml')
AVAILABLE=all(importlib.util.find_spec(p) is not None for p in PACKAGES)
if os.environ.get('DIFFWITNESS_REQUIRE_SYNTAX')=='1' and not AVAILABLE:
    raise RuntimeError('SQL/config qualification requires actual optional grammars')
SQL='''CREATE TABLE public.accounts (id integer, label text);
CREATE VIEW public.labels AS SELECT label FROM public.accounts;
CREATE INDEX account_label ON public.accounts(label);
CREATE FUNCTION public.total(x integer) RETURNS integer AS $$ SELECT x $$ LANGUAGE SQL;
-- CREATE TABLE forged (id int);
SELECT 'CREATE TABLE invented (id int)';
'''
JSON='{"service":{"port":8080,"a/b":"private-value"},"workers":[{"name":"x"},{"name":"y"}],"a~b":0}'
TOML='''title = "private-value"
[service]
port = 8080
"a.b" = {"nested/key" = "private-value"}
[[workers]]
name = "x"
[workers.tls]
enabled = true
[[workers]]
name = "y"
[workers.tls]
enabled = false
'''
YAML='''service:
  port: 8080
  'a/b': "private-value"
workers:
 - name: x
 - name: y
---
base: &base {port: 80}
copy: {<<: *base}
'''
FIXTURES=[('schema.sql',SQL,'sql','tree-sitter-sql'),('config.json',JSON,'json','tree-sitter-json'),
          ('config.toml',TOML,'toml','tree-sitter-toml'),('config.yaml',YAML,'yaml','tree-sitter-yaml')]

class DataSyntaxTests(unittest.TestCase):
    def extract(self,path,source):
        from diffwitness.structure_registry import extract_structure
        return extract_structure(path,source.encode() if isinstance(source,str) else source)

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_sql_only_top_level_ddl_names_not_query_or_literal_decoys(self):
        v=self.extract('schema.sql',SQL)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name:s.kind for s in v.symbols},{'schema.sql::'+n:k for n,k in
            [('public.accounts','table'),('public.labels','view'),('account_label','index'),('public.total','function')]})
        self.assertEqual((v.imports,v.calls),((),()))
        quoted=self.extract('a.sql','CREATE TABLE "A.B"."odd name" (id int); CREATE SCHEMA demo; CREATE TYPE status AS ENUM (\'ready\');')
        self.assertTrue(quoted.parsed)
        self.assertEqual({s.qualified_name for s in quoted.symbols},{'a.sql::"A.B"."odd name"','a.sql::demo','a.sql::status'})

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_json_keys_are_unambiguous_and_array_items_distinct(self):
        v=self.extract('config.json',JSON)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name for s in v.symbols},{'config.json::'+p for p in
            ['/service','/service/port','/service/a~1b','/workers','/workers/0/name','/workers/1/name','/a~0b']})
        self.assertTrue(all(s.kind=='config-key' for s in v.symbols))
        self.assertNotIn('private-value',json.dumps(asdict(v)))

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_toml_tables_and_nested_array_table_scopes(self):
        v=self.extract('config.toml',TOML)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name for s in v.symbols},{'config.toml::'+p for p in
            ['/title','/service','/service/port','/service/a.b','/service/a.b/nested~1key',
             '/workers/0','/workers/0/name','/workers/0/tls','/workers/0/tls/enabled',
             '/workers/1','/workers/1/name','/workers/1/tls','/workers/1/tls/enabled']})
        self.assertNotIn('private-value',json.dumps(asdict(v)))

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_yaml_document_scopes_without_alias_or_tag_execution(self):
        v=self.extract('config.yaml',YAML)
        self.assertTrue(v.parsed)
        self.assertEqual({s.qualified_name for s in v.symbols},{'config.yaml::'+p for p in
            ['/@0/service','/@0/service/port','/@0/service/a~1b','/@0/workers','/@0/workers/0/name',
             '/@0/workers/1/name','/@1/base','/@1/base/port','/@1/copy','/@1/copy/<<']})
        self.assertNotIn('private-value',json.dumps(asdict(v)))
        tagged=self.extract('a.yml','root: !custom {key: secret-value}\n? [a, b]\n: {unknown: secret-value}\n')
        self.assertTrue(tagged.parsed)
        self.assertEqual({s.qualified_name for s in tagged.symbols},{'a.yml::/@0/root','a.yml::/@0/root/key'})

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_duplicates_invalid_encodings_and_unsupported_sql_form_fail_closed(self):
        for p,s in [('a.json','{"x":1,"x":2}'),('a.json','{"x":NaN}'),('a.json','{"x":'),
                    ('a.toml','x=1\nx=2\n'),('a.toml','[a]\n[a]\n'),('a.yaml','x: 1\nx: 2\n'),
                    ('a.sql','CREATE TABLE broken ('),('a.sql','CREATE PROCEDURE demo() LANGUAGE SQL AS $$ SELECT 1 $$;')]:
            with self.subTest(path=p,source=s):
                v=self.extract(p,s);self.assertFalse(v.parsed);self.assertEqual((v.symbols,v.imports,v.calls),((),(),()))
        for p,_,_,_ in FIXTURES:self.assertFalse(self.extract(p,b'\xff').parsed)

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_decoded_keys_positions_and_invalid_surrogates(self):
        json_value=self.extract('a.json',r'{"a\u002fb": {"~": 1}, "": 0}')
        self.assertTrue(json_value.parsed)
        self.assertEqual({s.qualified_name for s in json_value.symbols},{'a.json::/a~1b','a.json::/a~1b/~0','a.json::/'})
        self.assertFalse(self.extract('a.json',r'{"\ud800": 1}').parsed)
        yaml=self.extract('a.yaml','"key": value\nother: 1\n')
        self.assertEqual({s.qualified_name:s.line for s in yaml.symbols},{'a.yaml::/@0/key':1,'a.yaml::/@0/other':2})
        duplicate=self.extract('a.yaml','key: 1\n"key": 2\n')
        self.assertFalse(duplicate.parsed)
        sql=self.extract('a.sql','CREATE TABLE public /* ignored */ . accounts (id int);')
        self.assertTrue(sql.parsed)
        self.assertEqual([s.qualified_name for s in sql.symbols],['a.sql::public.accounts'])

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_overflowing_json_values_fail_closed_at_every_nesting_level(self):
        for source in ('{"timeout":1e999}', '{"nested":[{"value":-1e999}]}', '[1e999]',
                       '{"outer":{"inside":{"value":1e999}}}'):
            with self.subTest(source=source):
                value=self.extract('config.json',source)
                self.assertFalse(value.parsed)
                self.assertEqual((value.symbols,value.imports,value.calls),((),(),()))
        for source in ('{"timeout":1e308}', '{"timeout":1e-999}', '{"large":'+'9'*300+'}'):
            with self.subTest(source=source):
                self.assertTrue(self.extract('config.json',source).parsed)

    def test_missing_grammars_remain_recognized_empty(self):
        for (p,s,language,provider),package in zip(FIXTURES,PACKAGES[1:]):
            with self.subTest(path=p),patch.dict(sys.modules,{package:None}):
                v=self.extract(p,s)
                self.assertEqual((v.language,v.provider),(language,provider));self.assertFalse(v.parsed)
                self.assertEqual((v.symbols,v.imports,v.calls),((),(),()))

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_actual_transport_hash_authority_positions_and_no_values(self):
        from diffwitness.structure_transport import extract_request
        r=extract_request({'schema_version':'structure-request-1','files':[
            {'path':p,'content_base64':base64.b64encode(s.encode()).decode()}for p,s,_,_ in FIXTURES]})
        self.assertEqual(r['coverage'],{'files':4,'parsed':4,'unparsed':0,'unsupported':0})
        self.assertNotIn('private-value',json.dumps(r))
        for value,(p,s,language,provider) in zip(r['files'],FIXTURES):
            self.assertEqual((value['path'],value['language'],value['provider'],value['module']),(p,language,provider,p))
            self.assertEqual(value['source_sha256'],hashlib.sha256(s.encode()).hexdigest())
            self.assertTrue(all(v['epistemic_status']=='OBSERVED' and 1<=v['line']<=v['end_line']<=len(s.splitlines())+1 for v in value['symbols']))

    @unittest.skipUnless(AVAILABLE,'actual optional SQL/config grammars not installed')
    def test_immutable_tree_index_keeps_keys_and_ddl_without_dirty_values(self):
        from diffwitness.continuity_state import rebuild_state
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)
            def git(*args):return subprocess.check_output(['git','-C',td,*args],stderr=subprocess.PIPE).decode().strip()
            git('init','-q');git('config','user.name','Data fixture');git('config','user.email','fixture@example.invalid')
            for p,s,_,_ in FIXTURES:(repo/p).write_text(s,encoding='utf-8')
            git('add','.');git('commit','-qm','data');tree=git('rev-parse','HEAD^{tree}')
            (repo/'config.json').write_text('{"dirty":"secret"}',encoding='utf-8')
            state=rebuild_state(repo,include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                self.assertEqual({r[0]for r in conn.execute('select language from structure_components')},{'sql','json','toml','yaml'})
                names=[r[0]for r in conn.execute('select qualified_name from structure_symbols')]
                self.assertFalse(any('dirty' in n or 'private-value' in n for n in names))
                self.assertIn('schema.sql::public.accounts',names)
                self.assertEqual(conn.execute('select distinct tree_sha from structure_symbols').fetchall(),[(tree,)])

if __name__=='__main__':unittest.main()
