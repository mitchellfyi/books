#!/usr/bin/env node
import { randomUUID } from 'node:crypto';
import { open, writeFile, unlink, realpath } from 'node:fs/promises';
import { constants } from 'node:fs';
import { join, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { snapshot, normalizeInvocation, applyChanges, safePath, fail, executionDiagnostic, readExecutionDiagnostic } from './agent-relay-protocol.mjs';
import { controlRequest, uploadBundle, downloadBundle } from './agent-relay-transport.mjs';

const runtimeKeys = ['ACTIONS_ID_TOKEN_REQUEST_URL', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
  'ACTIONS_RESULTS_URL', 'ACTIONS_RUNTIME_URL', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_REPOSITORY',
  'GITHUB_REPOSITORY_ID', 'GITHUB_WORKFLOW_SHA', 'GITHUB_WORKFLOW_REF', 'GITHUB_REF', 'GITHUB_EVENT_NAME',
  'RUNNER_ENVIRONMENT', 'GITHUB_WORKSPACE', 'RUNNER_TEMP'];
const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled']);
const pollingStops = new Set([...terminalStatuses, 'blocked']);
const executionStatuses = new Set(['queued', 'dispatching', 'running', ...pollingStops]);

// How long Control may go without answering before a run gives up, measured by the clock. Control restarts on every
// deploy: the step that replaces it took 143 to 169 seconds in 35 deploys on 12 and 13 October 2026, and a whole deploy
// run took up to 13.3 minutes. An outage (agent-relay-transport.mjs says which failures are one) is waited out for this
// long; a refusal ends the run at once. docs/decisions/2026-10-13-relay-outage-tolerance.md has the evidence.
export const OUTAGE_TOLERANCE_MS = 15 * 60_000;
export const POLL_INTERVAL_MS = 5000;
// Waits during an outage double from the poll interval to this cap, each drawn from its upper half (equal jitter), so
// clients that lost Control together do not return together.
export const RETRY_CAP_MS = 30_000;
const reasons = new Set(['network', 'timeout', 'rate_limited', 'server_error', 'receipt_pending', 'invalid_response', 'refused']);

// What a failed request means for the run, from the transport's fixed classification only. An error without one (an
// injected service, an unexpected exception) counts as an outage: it is waited out, never retried forever.
export function classifyFailure(error) {
  const relay = error?.relay;
  const known = relay && ['outage', 'refusal'].includes(relay.kind);
  return {
    kind: known ? relay.kind : 'outage',
    reason: known && reasons.has(relay.reason) ? relay.reason : 'unclassified',
    source: known && relay.source === 'identity' ? 'identity' : 'control',
    status: known && Number.isInteger(relay.status) && relay.status >= 100 && relay.status <= 599 ? relay.status : null,
    retryAfter: Number.isFinite(error?.retryAfter) && error.retryAfter > 0 ? error.retryAfter : 0,
  };
}

// The jittered wait before the next attempt, after `failures` consecutive failures.
export function outageWait(failures, random = Math.random, retryAfter = 0) {
  const ceiling = Math.min(RETRY_CAP_MS, POLL_INTERVAL_MS * 2 ** Math.min(Math.max(failures, 1) - 1, 10));
  const jittered = Math.round(ceiling / 2 + Math.min(Math.max(random(), 0), 1) * ceiling / 2);
  return Math.max(jittered, retryAfter);
}

const seconds = milliseconds => Math.round(milliseconds / 1000);
const facts = why => [`reason=${why.reason}`, `source=${why.source}`, ...(why.status ? [`http=${why.status}`] : [])].join('; ');

export async function setup(env = process.env) {
  if (env.RUNNER_ENVIRONMENT !== 'github-hosted' || env.GITHUB_REF !== 'refs/heads/main' ||
      !/^[a-f0-9]{40}$/.test(env.GITHUB_WORKFLOW_SHA) || !isAbsolute(env.HOME) ||
      !env.ACTIONS_ID_TOKEN_REQUEST_TOKEN || !env.ACTIONS_RUNTIME_TOKEN) throw fail();
  const runtime = Object.fromEntries(runtimeKeys.map(name => [name, env[name]]));
  runtime.GITHUB_WORKSPACE = await realpath(env.GITHUB_WORKSPACE);
  runtime.CONTROL_WORKSPACE = runtime.GITHUB_WORKSPACE;
  if (env.INPUT_WORKSPACE) {
    if (!['implementation-target', 'control', 'ops'].includes(env.INPUT_WORKSPACE)) throw fail();
    runtime.GITHUB_WORKSPACE = await realpath(join(runtime.GITHUB_WORKSPACE, env.INPUT_WORKSPACE));
  }
  runtime.RUNNER_TEMP = await realpath(env.RUNNER_TEMP);
  await writeFile(join(env.HOME, '.control-agent-runtime.json'), JSON.stringify(runtime), { mode: 0o600, flag: 'wx' });
}

async function runtimeFor(home) {
  const file = await open(join(home, '.control-agent-runtime.json'), constants.O_RDONLY | constants.O_NOFOLLOW);
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
  try { file = await open(join(env.RUNNER_TEMP, 'control-agent-changes.ndjson'), constants.O_RDONLY | constants.O_NOFOLLOW); }
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
      (runtime.GITHUB_REPOSITORY_ID !== '1188582959' || !['m12n-org/ops.m12n.org', 'm12n-org/control.m12n.org']
        .some(name => runtime.GITHUB_WORKFLOW_REF === `${name}/.github/workflows/codex-oauth-smoke.yml@refs/heads/main`))) throw fail();
  const lockPath = join(env.HOME, '.control-agent-invocation.lock');
  const lock = await open(lockPath, 'wx', 0o600);
  const request = services.request || ((path, options) => controlRequest(runtime, path, options));
  // Elapsed wall time on a monotonic clock: NTP adjustments cannot lengthen an outage budget.
  const now = services.now || (() => performance.now()), random = services.random || Math.random;
  const log = services.log || (line => process.stderr.write(`${line}\n`));
  // A cancelled run stops waiting at once instead of finishing a backoff first.
  const waiting = new AbortController();
  const pause = milliseconds => (services.delay || delay)(milliseconds, undefined, { signal: waiting.signal }).catch(() => {});
  let execution, executionId, cancellation, deadline = Infinity; let cancelled = false;
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
  const cancel = () => { cancelled = true; waiting.abort(); void cancelAccepted(); };
  const stop = code => Object.assign(fail(), { relayCode: code });
  // Sends one Control request until Control answers it. An outage is waited out for OUTAGE_TOLERANCE_MS of clock time
  // (or until the run's deadline) with jittered backoff and one line on stderr saying why; a refusal stops at once.
  const patiently = async send => {
    let since, failures = 0, logged = -Infinity, last;
    const remaining = () => Math.min(OUTAGE_TOLERANCE_MS - (since === undefined ? 0 : now() - since), deadline - now());
    const expired = () => {
      log(`Control relay: giving up at stage=${stage}: no answer for ${seconds(now() - (since ?? now()))}s, outage limit=${seconds(OUTAGE_TOLERANCE_MS)}s, run deadline remaining=${Math.max(0, seconds(deadline - now()))}s (last ${facts(last || { reason: 'run_deadline', source: 'control' })}).`);
      // Only a failed request makes Control unreachable. A run deadline that arrives before any failure (commonly while a poll
      // sleep crosses it) is the run's own limit and stays terminal, not a restartable outage.
      return last ? stop('control_unreachable') : fail();
    };
    // Sequential by design: the same execution is polled, never resubmitted or replayed as a new model call.
    for (;;) {
      if (cancelled) throw fail();
      if (remaining() <= 0) throw expired();
      const started = now();
      try {
        // Bound the in-flight fetch as well as the sleeps; a request may not consume another transport retry window.
        const signal = AbortSignal.any([waiting.signal, AbortSignal.timeout(Math.max(1, Math.ceil(remaining())))]);
        const answer = await send(signal);
        if (failures) log(`Control relay: Control answered again at stage=${stage} after ${seconds(now() - since)}s (${failures} failed attempts).`);
        return answer;
      } catch (error) {
        if (cancelled) throw fail();
        const why = classifyFailure(error);
        since ??= started; failures++; last = why;
        if (why.kind === 'refusal') {
          log(`Control relay: stopping at stage=${stage}: request refused (${facts(why)}); waiting cannot change a refusal.`);
          throw stop('control_refused');
        }
        if (remaining() <= 0) throw expired();
        const next = Math.min(outageWait(failures, random, why.retryAfter), remaining());
        if (now() - logged >= 60_000) {
          logged = now();
          log(`Control relay: waiting out an outage at stage=${stage} (${facts(why)}; waited ${seconds(now() - since)}s of ${seconds(OUTAGE_TOLERANCE_MS)}s; next attempt in ${seconds(next)}s). Control restarts on every deploy.`);
        }
        await pause(next);
      }
    }
  };
  process.once('SIGTERM', cancel); process.once('SIGINT', cancel);
  try {
    const workspace = runtime.GITHUB_WORKSPACE;
    const invocation = await normalizeInvocation(args, input, workspace, runtime.RUNNER_TEMP, runtime.CONTROL_WORKSPACE);
    const workflow = runtime.GITHUB_WORKFLOW_REF?.match(/\/([^/]+\.yml)@refs\/heads\/main$/)?.[1];
    const target = workflow === 'dexcode_review.yml' ? 'review-target'
      : workflow === 'dexcode_implement.yml' ? 'implementation-target' : null;
    const checkout = target ? join(workspace, target) : workspace;
    const noFiles = ['codex-pr-review.yml', 'codex-review-sweep.yml', 'weekly-book-discovery.yml', 'quality-review.yml', 'estate-review.yml', 'generate-news.yml', 'generate-article.yml'].includes(workflow);
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
    deadline = now() + 100 * 60_000;
    const body = { client_request_id, target_sha, context_artifact_id: artifact.id, context_digest: artifact.digest, operation };
    // Repeating the submission is safe: Control returns the execution it already accepted for this client_request_id.
    execution = await patiently(signal => request('', { method: 'POST', body, signal }));
    if (!/^[a-f0-9-]{36}$/.test(execution?.id)) {
      log('Control relay: stopping at stage=submission: invalid execution identity.'); throw stop('control_refused');
    }
    executionId = execution.id;
    if (!executionStatuses.has(execution.status)) {
      log('Control relay: stopping at stage=submission: unsupported execution state.'); throw stop('control_refused');
    }
    stage = 'polling';
    // A read Control answers with another identity or an unknown status still fails at once. While Control is away the
    // execution keeps running, and a terminal status recorded meanwhile is read when Control answers again.
    while (!pollingStops.has(execution.status)) {
      if (cancelled || now() > deadline) throw fail();
      await pause(POLL_INTERVAL_MS);
      const next = await patiently(signal => request(`/${executionId}`, { attempts: 1, signal }));
      if (next?.id !== executionId || !executionStatuses.has(next.status)) {
        log(`Control relay: stopping at stage=polling: ${next?.id !== executionId ? 'execution identity changed' : 'unsupported execution state'}.`);
        throw stop('control_refused');
      }
      execution = next;
    }
    stage = 'execution';
    if (execution.status !== 'succeeded' || cancelled) throw fail();
    stage = 'head-verification';
    if (head(checkout) !== target_sha) throw fail();
    stage = 'result-download';
    const download = await patiently(signal => request(`/${execution.id}/result`, { attempts: 1, signal }));
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
      const receipt = await open(join(runtime.RUNNER_TEMP, 'control-agent-changes.ndjson'),
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
        { ...execution, id: executionId, ...(error?.relayCode ? { error_code: error.relayCode } : {}) }),
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
