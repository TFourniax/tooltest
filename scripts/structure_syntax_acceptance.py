"""Actual installed optional syntax producer; no source checkout imports."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

dw = shutil.which('dw')
assert dw, 'installed dw required'
sources = {'source.ts': b'export interface Input { value: string };\nexport function actual(x: Input) { return x.value; }\n',
           'View.jsx': b'export const View = () => <div>bonjour</div>;\n',
           'api.d.ts': b'declare function load(): void;\nexport declare class Service { run(): void; }\n',
           'invalid.js': b'function broken(', 'opaque.unknown': b'opaque'}
sources['service.go'] = b'package service\nfunc Refund(value int) int { return value }\n'
sources['service.rs'] = b'pub fn refund(value: i32) -> i32 { value }\n'
sources['Gateway.java'] = b'class Gateway { void refund() {} }\n'
sources['Gateway.cs'] = b'namespace Payments; public class Gateway { public void Refund() {} }\n'
sources['Gateway.kt'] = b'class Gateway {\n fun refund() {}\n}\n'
sources['gateway.rb'] = b'class Gateway; def refund(); end; end\n'
sources['gateway.php'] = b"<?php namespace Payments; require('client.php'); class Gateway { function refund() {} }\n"
sources['schema.sql'] = b'CREATE TABLE accounts (id int);\n'
sources['config.json'] = b'{"service":{"secret":"private-value"}}'
sources['config.toml'] = b'[service]\nsecret = "private-value"\n'
sources['config.yaml'] = b'service:\n  secret: private-value\n'
request = {'schema_version': 'structure-request-1', 'files': [
    {'path': name, 'content_base64': base64.b64encode(content).decode()} for name, content in sources.items()]}
env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
with tempfile.TemporaryDirectory(prefix='dw-syntax-installed-') as td:
    values = []
    for options in ([], ['--language', 'en'], ['--language', 'fr']):
        result = subprocess.run([dw, *options, 'state', 'extract', '--json'], cwd=td, env=env,
                                input=json.dumps(request), capture_output=True, text=True,
                                encoding='utf-8', timeout=10)
        assert result.returncode == 0, result.stderr
        values.append(json.loads(result.stdout))
    assert values[0] == values[1] == values[2]
    response = values[0]
    assert response['coverage'] == {'files': 16, 'parsed': 14, 'unparsed': 1, 'unsupported': 1}, response
    for item, (name, content) in zip(response['files'], sources.items()):
        assert item['path'] == name and item['source_sha256'] == hashlib.sha256(content).hexdigest()
        assert all(symbol['epistemic_status'] == 'OBSERVED' for symbol in item['symbols'])
    assert {symbol['qualified_name'] for symbol in response['files'][0]['symbols']} == {'source.ts::Input', 'source.ts::actual'}
    assert response['files'][1]['symbols'][0]['qualified_name'] == 'View.jsx::View'
    assert {symbol['qualified_name'] for symbol in response['files'][2]['symbols']} == {'api.d.ts::load', 'api.d.ts::Service', 'api.d.ts::Service.run'}
    by_path = {item['path']: item for item in response['files']}
    assert by_path['service.go']['symbols'][0]['qualified_name'] == 'service.go::Refund'
    assert by_path['service.rs']['symbols'][0]['qualified_name'] == 'service.rs::refund'
    assert {s['qualified_name'] for s in by_path['Gateway.java']['symbols']} == {'Gateway.java::Gateway', 'Gateway.java::Gateway.refund'}
    assert {s['qualified_name'] for s in by_path['Gateway.cs']['symbols']} == {'Gateway.cs::Payments.Gateway', 'Gateway.cs::Payments.Gateway.Refund'}
    assert {s['qualified_name'] for s in by_path['Gateway.kt']['symbols']} == {'Gateway.kt::Gateway', 'Gateway.kt::Gateway.refund'}
    assert {s['qualified_name'] for s in by_path['gateway.rb']['symbols']} == {'gateway.rb::Gateway', 'gateway.rb::Gateway.refund'}
    assert {s['qualified_name'] for s in by_path['gateway.php']['symbols']} == {'gateway.php::Payments.Gateway', 'gateway.php::Payments.Gateway.refund'}
    assert [i['target'] for i in by_path['gateway.php']['imports']] == ['client.php']
    assert {s['qualified_name'] for s in by_path['schema.sql']['symbols']} == {'schema.sql::accounts'}
    for source, prefix in [('config.json', ''), ('config.toml', ''), ('config.yaml', '/@0')]:
        assert {s['qualified_name'] for s in by_path[source]['symbols']} == {source + '::' + prefix + p for p in ['/service', '/service/secret']}
    assert 'private-value' not in json.dumps(response), 'configuration values must not be retained'
    overflow = {'schema_version': 'structure-request-1', 'files': [{
        'path': 'overflow.json', 'content_base64': base64.b64encode(b'{"nested":[{"timeout":1e999}]}').decode()}]}
    rejected = subprocess.run([dw, 'state', 'extract', '--json'], cwd=td, env=env,
                              input=json.dumps(overflow), capture_output=True, text=True,
                              encoding='utf-8', timeout=10)
    assert rejected.returncode == 0, rejected.stderr
    empty = json.loads(rejected.stdout)['files'][0]
    assert empty['parsed'] is False and not empty['symbols'] and not empty['imports'] and not empty['calls']
    assert not list(Path(td).iterdir()), 'source-byte extraction must not persist files'
print('INSTALLED SYNTAX ACCEPTANCE PASS: actual pinned code/SQL/config providers, source hashes, FR/EN, unparsed and unsupported coverage; MACHINE')
