import { prepareImplementationClient, reportImplementationClient } from './implementation-runtime.mjs';

try {
  if (process.argv.length !== 3) throw new Error();
  if (process.argv[2] === 'prepare') await prepareImplementationClient(process.env);
  else if (process.argv[2] === 'report') await reportImplementationClient(process.env);
  else throw new Error();
} catch {
  console.error('Implementation client failed.');
  process.exitCode = 1;
}
