// Diagnostic preload only: delegates every call unchanged to Node's real reader.
const cp = require('node:child_process');
const fs = require('node:fs');
const {performance} = require('node:perf_hooks');
const {syncBuiltinESMExports} = require('node:module');
const rows = [];
let depth = 0;
for (const name of ['spawnSync', 'execFileSync']) {
  const original = cp[name];
  cp[name] = function(command, args, ...rest) {
    const outer = depth++ === 0;
    const started = performance.now();
    let status = null;
    try {
      const value = original.call(this, command, args, ...rest);
      status = value?.status ?? 0;
      return value;
    } catch (error) {
      status = error.status ?? 'exception';
      throw error;
    } finally {
      depth--;
      if (outer) rows.push({api:name, command:String(command), args:Array.isArray(args)?args:[], ms:performance.now()-started, status});
    }
  };
}
syncBuiltinESMExports();
process.on('exit', code => {
  fs.writeFileSync(process.env.DW_DIAGNOSTIC_OUT, JSON.stringify({classification:'MACHINE_DIAGNOSTIC', code, rows}, null, 2)+'\n');
});
