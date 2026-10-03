import { appendFile, mkdir, symlink, chmod, cp, writeFile, readdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { setup } from './agent-relay-client.mjs';

export async function verifyRelayPackage(source) {
  const manifest = JSON.parse(await readFile(join(source, 'provenance.json'), 'utf8'));
  const files = ['action.yml', 'agent-relay-client.mjs', 'agent-relay-protocol.mjs', 'agent-relay-transport.mjs',
    'agent-relay-setup.mjs', 'agent_bundle.py', 'package.json', 'package-lock.json'].sort();
  if (manifest.version !== 1 || manifest.repository !== 'm12n-org/ops.m12n.org' ||
      JSON.stringify(Object.keys(manifest.checksums || {}).sort()) !== JSON.stringify(files)) throw new Error('Invalid relay provenance.');
  for (const name of files) {
    const actual = createHash('sha256').update(await readFile(join(source, name))).digest('hex');
    if (actual !== manifest.checksums[name]) throw new Error('The managed relay bytes have changed.');
  }
}

export async function installRelayRuntime(source, env) {
  // Later steps may check out a PR over the control checkout. Keep this trusted
  // entry point and its dependencies outside that mutable tree.
  const runtime = join(env.RUNNER_TEMP, 'ops-agent-runtime');
  await mkdir(runtime, { mode: 0o700 });
  for (const name of await readdir(source)) {
    await cp(join(source, name), join(runtime, name), { recursive: true, force: false, errorOnExist: true });
  }
  const directory = join(env.RUNNER_TEMP, 'ops-agent-bin');
  const client = join(runtime, 'agent-relay-client.mjs');
  await mkdir(directory, { mode: 0o700 });
  await chmod(client, 0o755);
  await symlink(client, join(directory, 'codex-ci'));
  await appendFile(env.GITHUB_PATH, `${directory}\n`);
}

export function installSandboxPackages(run) {
  // The hosted image supplies Chrome; sandbox setup only needs Ubuntu packages.
  run(['rm', '-f', '/etc/apt/sources.list.d/google-chrome.list', '/etc/apt/sources.list.d/google-chrome.sources']);
  const apt = ['apt-get', '-o', 'Acquire::Retries=2', '-o', 'Acquire::http::Timeout=30', '-o', 'Acquire::https::Timeout=30'];
  run([...apt, 'update', '-qq']);
  run([...apt, 'install', '-y', 'bubblewrap']);
}

export async function setupRelayAction(env = process.env) {
  const source = fileURLToPath(new URL('.', import.meta.url));
  const opsSource = env.GITHUB_REPOSITORY_ID === '1188582959' &&
    [join(env.GITHUB_WORKSPACE, 'automation') + '/', join(env.GITHUB_WORKSPACE, 'ops/automation') + '/'].includes(source);
  if (!opsSource) await verifyRelayPackage(source);
  await setup(env);
  if (process.platform !== 'linux') throw new Error('A GitHub-hosted Linux runner is required.');
  const run = args => {
    const result = spawnSync('sudo', args, { stdio: 'inherit', timeout: 180_000 });
    if (result.status !== 0) throw new Error('Sandbox setup failed.');
  };
  installSandboxPackages(run);
  const profile = join(env.RUNNER_TEMP, 'ops-agent-bwrap.apparmor');
  await writeFile(profile, 'abi <abi/4.0>,\ninclude <tunables/global>\nprofile ops-agent-bwrap /usr/bin/bwrap flags=(unconfined) {\n  userns,\n}\n', { flag: 'wx', mode: 0o600 });
  run(['install', '-m', '0644', profile, '/etc/apparmor.d/ops-agent-bwrap']);
  run(['apparmor_parser', '-r', '/etc/apparmor.d/ops-agent-bwrap']);
  await installRelayRuntime(source, env);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { await setupRelayAction(); }
  catch { process.stderr.write('Hosted agent setup failed; private details withheld.\n'); process.exitCode = 1; }
}
