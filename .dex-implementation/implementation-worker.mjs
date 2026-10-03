import { realpathSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runImplementationWorker, readImplementationWorkerContext } from './implementation-runtime.mjs';
import { canonicalizeCheckout } from './review-evidence.mjs';
import { runManagedProcess } from './implementation-process.mjs';

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length !== 3 || !['canonicalize', 'execute'].includes(process.argv[2])) throw new Error();
    if (process.argv[2] === 'canonicalize') {
      const { workspace, spec, environment } = await readImplementationWorkerContext(process.env);
      await canonicalizeCheckout(workspace, join(workspace, 'implementation-target'), spec.baseSha, environment, 'implementation');
      console.log('Approved implementation checkout materialized without conversions.');
    } else {
      await runImplementationWorker(process.env, runManagedProcess);
      console.log('Implementation patch prepared for the separate validator and publisher.');
    }
  } catch {
    console.error('Implementation worker failed.');
    process.exitCode = 1;
  }
}
