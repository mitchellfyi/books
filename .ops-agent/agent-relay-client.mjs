#!/usr/bin/env node
import { randomUUID } from 'node:crypto';
import { open, writeFile, unlink, realpath } from 'node:fs/promises';
import { constants } from 'node:fs';
import { join, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { snapshot, normalizeInvocation, applyChanges, safePath, fail, executionDiagnostic, readExecutionDiagnostic } from './agent-relay-protocol.mjs';
import { opsRequest, uploadBundle, downloadBundle } from './agent-relay-transport.mjs';

const runtimeKeys = ['ACTIONS_ID_TOKEN_REQUEST_URL', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
  'ACTIONS_RESULTS_URL', 'ACTIONS_RUNTIME_URL', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_REPOSITORY',
  'GITHUB_REPOSITORY_ID', 'GITHUB_WORKFLOW_SHA', 'GITHUB_WORKFLOW_REF', 'GITHUB_REF', 'GITHUB_EVENT_NAME',
  'RUNNER_ENVIRONMENT', 'GITHUB_WORKSPACE', 'RUNNER_TEMP'];
const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled']);
const pollingStops = new Set([...terminalStatuses, 'blocked']);
const executionStatuses = new Set(['queued', 'dispatching', 'running', ...pollingStops]);

export async function setup(env = process.env) {
  if (env.RUNNER_ENVIRONMENT !== 'github-hosted' || env.GITHUB_REF !== 'refs/heads/main' ||
      !/^[a-f0-9]{40}$/.test(env.GITHUB_WORKFLOW_SHA) || !isAbsolute(env.HOME) ||
      !env.ACTIONS_ID_TOKEN_REQUEST_TOKEN || !env.ACTIONS_RUNTIME_TOKEN) throw fail();
  const runtime = Object.fromEntries(runtimeKeys.map(name => [name, env[name]]));
  runtime.GITHUB_WORKSPACE = await realpath(env.GITHUB_WORKSPACE);
  runtime.CONTROL_WORKSPACE = runtime.GITHUB_WORKSPACE;
  if (env.INPUT_WORKSPACE) {
    if (!['implementation-target', 'ops'].includes(env.INPUT_WORKSPACE)) throw fail();
    runtime.GITHUB_WORKSPACE = await realpath(join(runtime.GITHUB_WORKSPACE, env.INPUT_WORKSPACE));
  }
  runtime.RUNNER_TEMP = await realpath(env.RUNNER_TEMP);
  await writeFile(join(env.HOME, '.ops-agent-runtime.json'), JSON.stringify(runtime), { mode: 0o600, flag: 'wx' });
}

async function runtimeFor(home) {
  const file = await open(join(home, '.ops-agent-runtime.json'), constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.uid !== process.getuid() || stat.mode & 0o077 || stat.nlink !== 1 || stat.size > 100_000) throw fail();
    return JSON.parse(await file.readFile('utf8'));
  } finally { await file.close(); }
}

function head(workspace) {
  const result = spawnSync('git', ['-c', 'core.fsmonitor=false', '-C', workspace, 'rev-parse', 'HEAD'], {
    env: { PATH: process.env.PATH, HOME: '/nonexistent', GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' },
    encoding: 'utf8', timeout: 10_000 });
  if (result.status !== 0 || !/^[a-f0-9]{40}\n$/.test(result.stdout)) throw fail();
  return result.stdout.trim();
}

export async function stageReturnedChanges(env = process.env) {
  if (env.RUNNER_ENVIRONMENT !== 'github-hosted' || env.GITHUB_REF !== 'refs/heads/main' ||
      !/^[1-9][0-9]*$/.test(env.GITHUB_RUN_ID) || !/^[1-9][0-9]*$/.test(env.GITHUB_RUN_ATTEMPT)) throw fail();
  const workspace = await realpath(env.GITHUB_WORKSPACE), current = head(workspace);
  let file;
  try { file = await open(join(env.RUNNER_TEMP, 'ops-agent-changes.ndjson'), constants.O_RDONLY | constants.O_NOFOLLOW); }
  catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  const paths = new Set();
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.uid !== process.getuid() || stat.nlink !== 1 || stat.mode & 0o077 || stat.size > 2_000_000) throw fail();
    const rows = (await file.readFile('utf8')).trim().split('\n').filter(Boolean).map(row => JSON.parse(row));
    for (const row of rows) {
      if (row?.version !== 1 || row.run_id !== env.GITHUB_RUN_ID || row.attempt !== env.GITHUB_RUN_ATTEMPT ||
          row.target_sha !== current || !Array.isArray(row.paths)) throw fail();
      for (const path of row.paths) { safePath(path, { writable: true }); paths.add(path); }
    }
    if (paths.size > 1000) throw fail();
  } finally { await file.close(); }
  const git = args => {
    const result = spawnSync('git', ['-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-C', workspace, ...args],
      { encoding: 'utf8', timeout: 30_000, env: { PATH: env.PATH || process.env.PATH, HOME: '/nonexistent',
        GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', GIT_LITERAL_PATHSPECS: '1' } });
    if (result.status !== 0) throw fail();
    return result.stdout;
  };
  if (git(['diff', '--cached', '--name-only']).trim()) throw fail();
  const selected = [...paths].sort();
  if (selected.length) git(['add', '--', ...selected]);
  return selected;
}

export async function relay(args, input, env = process.env, services = {}) {
  if (['OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY', 'DEXCODE_OPENAI_API_KEY'].some(name => env[name])) throw fail();
  const runtime = await runtimeFor(env.HOME);
  const operation = services.operation || 'codex-cli';
  if (!['codex-cli', 'capability-smoke'].includes(operation) || operation === 'capability-smoke' &&
      (runtime.GITHUB_REPOSITORY_ID !== '1188582959' || runtime.GITHUB_WORKFLOW_REF !==
        'm12n-org/ops.m12n.org/.github/workflows/codex-oauth-smoke.yml@refs/heads/main')) throw fail();
  const lockPath = join(env.HOME, '.ops-agent-invocation.lock');
  const lock = await open(lockPath, 'wx', 0o600);
  const request = services.request || ((path, options) => opsRequest(runtime, path, options));
  let execution, executionId, cancellation; let cancelled = false;
  let stage = 'preparation';
  const cancelAccepted = () => {
    if (cancellation) return cancellation;
    if (!executionId || terminalStatuses.has(execution?.status)) return;
    cancellation ||= (async () => {
      const controller = new AbortController();
      let timer;
      const deadline = new Promise(resolve => {
        timer = setTimeout(() => { controller.abort(); resolve(); }, 5000);
      });
      try {
        await Promise.race([request(`/${executionId}/cancel`, { method: 'POST', signal: controller.signal }), deadline]);
      } catch { /* Cancellation failure must not prevent local cleanup. */ }
      finally { clearTimeout(timer); }
    })();
    return cancellation;
  };
  const cancel = () => { cancelled = true; void cancelAccepted(); };
  process.once('SIGTERM', cancel); process.once('SIGINT', cancel);
  try {
    const workspace = runtime.GITHUB_WORKSPACE;
    const invocation = await normalizeInvocation(args, input, workspace, runtime.RUNNER_TEMP, runtime.CONTROL_WORKSPACE);
    const workflow = runtime.GITHUB_WORKFLOW_REF?.match(/\/([^/]+\.yml)@refs\/heads\/main$/)?.[1];
    const target = workflow === 'dexcode_review.yml' ? 'review-target'
      : workflow === 'dexcode_implement.yml' ? 'implementation-target' : null;
    const checkout = target ? join(workspace, target) : workspace;
    const noFiles = ['codex-pr-review.yml', 'codex-review-sweep.yml', 'weekly-book-discovery.yml', 'weekly-portfolio-stewardship.yml', 'generate-news.yml', 'generate-article.yml'].includes(workflow);
    const entries = noFiles ? [] : (await snapshot(checkout)).map(entry => ({ ...entry, path: target ? `${target}/${entry.path}` : entry.path }));
    const target_sha = head(checkout);
    const client_request_id = randomUUID();
    const bundle = { version: 1, client_request_id, repository_id: Number(runtime.GITHUB_REPOSITORY_ID),
      source_run_id: Number(runtime.GITHUB_RUN_ID), source_attempt: Number(runtime.GITHUB_RUN_ATTEMPT),
      target_sha, entries, images: invocation.images, args: invocation.args, input: invocation.input, schema: invocation.schema || null };
    Object.assign(process.env, Object.fromEntries(runtimeKeys.map(name => [name, runtime[name]]).filter(([, value]) => value !== undefined)));
    stage = 'context-upload';
    const artifact = await (services.upload || uploadBundle)(`agent-context-${runtime.GITHUB_RUN_ID}-${runtime.GITHUB_RUN_ATTEMPT}-${client_request_id}`, bundle, runtime);
    stage = 'submission';
    const body = { client_request_id, target_sha, context_artifact_id: artifact.id, context_digest: artifact.digest, operation };
    for (let attempt = 0; attempt < 3; attempt++) {
      try { execution = await request('', { method: 'POST', body }); break; }
      catch { if (attempt === 2) throw fail(); await delay(2000); }
    }
    if (!/^[a-f0-9-]{36}$/.test(execution?.id)) throw fail();
    executionId = execution.id;
    if (!executionStatuses.has(execution.status)) throw fail();
    stage = 'polling';
    const deadline = Date.now() + 100 * 60_000;
    while (!pollingStops.has(execution.status)) {
      if (cancelled || Date.now() > deadline) throw fail();
      await (services.delay || delay)(5000);
      const next = await request(`/${executionId}`);
      if (next?.id !== executionId || !executionStatuses.has(next.status)) throw fail();
      execution = next;
    }
    stage = 'execution';
    if (execution.status !== 'succeeded' || cancelled) throw fail();
    stage = 'head-verification';
    if (head(checkout) !== target_sha) throw fail();
    stage = 'result-download';
    const download = await request(`/${execution.id}/result`);
    const result = await (services.download || downloadBundle)(download.url, download.digest);
    stage = 'result-validation';
    if (result?.version !== 1 || result.execution_id !== execution.id || result.client_request_id !== client_request_id ||
        result.target_sha !== target_sha || typeof result.stdout !== 'string' || Buffer.byteLength(result.stdout) > 8_000_000 ||
        typeof result.last_message !== 'string' || Buffer.byteLength(result.last_message) > 1_000_000) throw fail();
    if (cancelled) throw fail();
    if (target && (!Array.isArray(result.changes) || result.changes.some(change =>
      typeof change?.path !== 'string' || !change.path.startsWith(`${target}/`)))) throw fail();
    stage = 'apply-changes';
    await applyChanges(result.changes, workspace);
    if (cancelled) throw fail();
    if (result.changes.length) {
      const receipt = await open(join(runtime.RUNNER_TEMP, 'ops-agent-changes.ndjson'),
        constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | constants.O_NOFOLLOW, 0o600);
      try {
        const stat = await receipt.stat();
        if (!stat.isFile() || stat.uid !== process.getuid() || stat.mode & 0o077 || stat.nlink !== 1 || stat.size > 2_000_000) throw fail();
        await receipt.writeFile(`${JSON.stringify({ version: 1, run_id: runtime.GITHUB_RUN_ID,
          attempt: runtime.GITHUB_RUN_ATTEMPT, target_sha, paths: result.changes.map(change => change.path) })}\n`);
      } finally { await receipt.close(); }
    }
    if (cancelled) throw fail();
    stage = 'output';
    if (invocation.output) await writeFile(invocation.output, result.last_message, { mode: 0o600, flag: 'wx' });
    if (cancelled) throw fail();
    return result.stdout;
  } catch (error) {
    throw Object.assign(error instanceof Error ? error : fail(), {
      executionDiagnostic: executionDiagnostic(stage, runtime.GITHUB_RUN_ID,
        { ...execution, id: executionId }),
    });
  } finally {
    try { await cancelAccepted(); }
    finally {
      process.removeListener('SIGTERM', cancel); process.removeListener('SIGINT', cancel);
      try { await lock.close(); } finally { await unlink(lockPath); }
    }
  }
}

export async function readRelayInput(stream = process.stdin) {
  const buffer = Buffer.allocUnsafe(4_100_000);
  let length = 0;
  for await (const chunk of stream) {
    if (!Buffer.isBuffer(chunk) || length + chunk.length > buffer.length) throw fail();
    chunk.copy(buffer, length); length += chunk.length;
  }
  return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(buffer.subarray(0, length));
}

if (process.argv[1] && import.meta.url === pathToFileURL(await realpath(process.argv[1])).href) {
  try {
    if (process.argv[2] === 'setup') await setup();
    else {
      const input = await readRelayInput();
      process.stdout.write(await relay(process.argv.slice(2), input));
    }
  } catch (error) {
    const diagnostic = readExecutionDiagnostic(error?.executionDiagnostic);
    if (diagnostic) process.stderr.write(`${diagnostic}\n`);
    process.stderr.write(`${fail().message}\n`); process.exitCode = 1;
  }
}
