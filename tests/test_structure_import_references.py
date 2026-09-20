from __future__ import annotations

import base64
import contextlib
from dataclasses import replace
import importlib.util
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from diffwitness.structure_contract import validate_extraction
from diffwitness.structure_python import extract_python
from diffwitness.structure_registry import extract_structure
from diffwitness.structure_transport import extract_request
from diffwitness.continuity_state import rebuild_state
import test_continuity_kernel as fixtures


class ImportReferenceTests(unittest.TestCase):
    def request(self, source, version=2):
        return {'schema_version':f'structure-request-{version}', 'files':[
            {'path':'pkg/__init__.py','content_base64':base64.b64encode(source).decode()}]}

    def test_package_initializer_retains_base_members_and_source_positions(self):
        source='from .child import (\n    café as local,\n    other,\n)\nfrom . import sibling\n'.encode()
        result=extract_python('pkg/__init__.py',source)
        self.assertEqual([i.target for i in result.imports],['pkg.child','pkg'])
        first,second=result.imports
        self.assertEqual((first.source_target,first.members,first.line,first.end_line),('.child',('café','other'),1,4))
        self.assertEqual((second.source_target,second.members,second.line,second.end_line),('.',('sibling',),5,5))

    def test_outside_package_relative_imports_never_become_absolute_names(self):
        for path,source,expected in [('root.py',b'from .other import thing\n','.other'),
              ('pkg/worker.py',b'from ..outside import run\n','..outside'),
              ('pkg/sub/worker.py',b'from ..inside import run\n','pkg.inside'),
              ('pkg/sub/__init__.py',b'from ..inside import run\n','pkg.inside')]:
            with self.subTest(path=path):
                self.assertEqual(extract_python(path,source).imports[0].target,expected)

    def test_v1_field_shape_is_preserved_and_v2_is_explicit(self):
        source=b'from .child import run as renamed\n'
        v1=extract_request(self.request(source,1));v2=extract_request(self.request(source,2))
        self.assertEqual(v1['schema_version'],'structure-response-1')
        self.assertEqual(v1['files'][0]['schema_version'],'structure-extraction-1')
        self.assertEqual(set(v1['files'][0]['imports'][0]),{'target','epistemic_status'})
        self.assertEqual(v2['schema_version'],'structure-response-2')
        self.assertEqual(v2['files'][0]['schema_version'],'structure-extraction-2')
        detail=v2['files'][0]['imports'][0]
        self.assertEqual((detail['source_target'],tuple(detail['members']),detail['line']),('.child',('run',),1))
        self.assertEqual(detail['epistemic_status'],'OBSERVED')
        for bad in [{**self.request(source),'extra':1},{**self.request(source),'schema_version':'structure-request-3'}]:
            with self.assertRaises(ValueError):extract_request(bad)

    def test_import_detail_admission_rejects_invalid_positions_and_members(self):
        source=b'import os\n';result=extract_python('a.py',source)
        for fields in [dict(line=0),dict(line=True),dict(end_line=3),dict(line=None,end_line=1),
                       dict(source_target=[]),dict(members=['thing']),dict(members=(42,))]:
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                validate_extraction(replace(result,imports=(replace(result.imports[0],**fields),)),'a.py',source)

    def test_python_aliases_crlf_and_decoys_preserve_only_import_syntax(self):
        source=b'# import invented\r\ntext = "from false import other"\r\nimport os as operating, sys\r\n'
        result=extract_python('pkg/a.py',source)
        self.assertEqual([i.target for i in result.imports],['os','sys'])
        self.assertEqual([(i.line,i.end_line,i.source_target,i.members) for i in result.imports],[(3,3,'os',()),(3,3,'sys',())])

    @unittest.skipUnless(importlib.util.find_spec('tree_sitter_php'),'optional actual syntax grammars not installed')
    def test_actual_syntax_import_positions_reuse_every_adapter(self):
        cases=[('a.ts','// decoy\nimport {x} from "./other";\n'),
               ('a.go','package a\nimport "fmt"\n'),('a.rs','// decoy\nuse std::fmt;\n'),
               ('A.java','// decoy\nimport java.util.List;\nclass A {}\n'),
               ('A.cs','// decoy\nusing System;\nclass A {}\n'),('a.kt','// decoy\nimport kotlin.collections.List\n'),
               ('a.rb','# decoy\nrequire "json"\n'),('a.php','<?php\nrequire("local.php");\n')]
        for path,source in cases:
            with self.subTest(path=path):
                value=extract_structure(path,source.encode());self.assertTrue(value.parsed)
                self.assertTrue(value.imports)
                self.assertTrue(all((i.line,i.end_line)==(2,2) for i in value.imports))
                self.assertTrue(all(i.members is None and i.source_target is None for i in value.imports),
                                'Unavailable member/raw-target detail must be explicit, not an empty fact')
                validate_extraction(value,path,source.encode(),language=value.language,provider=value.provider)

    def test_immutable_index_never_picks_ambiguous_or_outside_relative_modules(self):
        with tempfile.TemporaryDirectory() as td:
            repo=fixtures.ContinuityKernelTests().repo(Path(td))
            sources={'pkg/__init__.py':'from .child import run\n','pkg/child.py':'def run(): pass\n',
                     'outside.py':'def run(): pass\n','pkg/worker.py':'from ..outside import run\n',
                     'ambiguous.py':'import duplicate\n','duplicate.py':'','duplicate/__init__.py':''}
            for name,source in sources.items():
                p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(source)
            subprocess.check_call(['git','add','.'],cwd=repo);subprocess.check_call(['git','commit','-qm','imports'],cwd=repo)
            state=rebuild_state(repo,include_structure=True)
            with contextlib.closing(sqlite3.connect(state)) as conn:
                rows=conn.execute("select c.path,e.target_id,e.target_kind,e.epistemic_status from structure_edges e join structure_components c on c.component_id=e.source_id where predicate='imports'").fetchall()
                targets=dict(conn.execute('select component_id,path from structure_components'))
            self.assertTrue(any(p=='pkg/__init__.py' and targets.get(t)=='pkg/child.py' and a=='INFERRED' for p,t,k,a in rows))
            self.assertFalse(any(p in {'pkg/worker.py','ambiguous.py'} and k=='component' for p,t,k,a in rows))
            self.assertTrue(any(p=='pkg/worker.py' and t=='module:..outside' and k=='module-reference' for p,t,k,a in rows))


if __name__=='__main__':unittest.main()
