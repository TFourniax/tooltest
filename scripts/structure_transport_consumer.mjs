import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const dw = process.argv[2];
assert.ok(dw, 'pass the exact installed dw executable');
const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'dw-structure-consumer-'));
const source = Buffer.from('from decimal import Decimal\n\ndef remboursement(amount):\n    return Decimal(amount)\n');
const input = JSON.stringify({schema_version:'structure-request-1', files:[
  {path:'src/paiement.py', content_base64:source.toString('base64')},
  {path:'opaque.bin', content_base64:Buffer.from([0xff, 0]).toString('base64')}
]});
const env = {...process.env};
delete env.PYTHONPATH;
try {
  const values = ['en','fr'].map(language => {
    const child = spawnSync(dw, ['--language',language,'state','extract','--json'],
      {cwd, env, input, encoding:'utf8', timeout:10000, maxBuffer:1024*1024, windowsHide:true});
    assert.equal(child.status, 0, child.stderr || String(child.error));
    return JSON.parse(child.stdout);
  });
  assert.deepEqual(values[0], values[1]);
  const result = values[0];
  assert.equal(result.schema_version, 'structure-response-1');
  assert.equal(result.files[0].source_sha256, createHash('sha256').update(source).digest('hex'));
  assert.equal(result.files[0].symbols[0].qualified_name, 'src.paiement.remboursement');
  assert.equal(result.files[0].symbols[0].epistemic_status, 'OBSERVED');
  assert.equal(result.files[0].calls[0].epistemic_status, 'INFERRED');
  assert.equal(result.files[1].provider, 'file-only');
  assert.deepEqual(result.coverage, {files:2, parsed:1, unsupported:1, unparsed:0});
  assert.deepEqual(fs.readdirSync(cwd), []);
  console.log('STRUCTURE TRANSPORT CONSUMER PASS: exact installed Core, Node JSON, FR/EN, source hash, authority and explicit fallback');
} finally {
  fs.rmSync(cwd, {recursive:true, force:true});
}
