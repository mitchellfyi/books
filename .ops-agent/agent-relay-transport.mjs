import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { fail, MAX_BUNDLE } from './agent-relay-protocol.mjs';

export const OPS = 'https://ops.m12n.org/api/v1/agent-executions';

let quietUploads = 0;
let uploadLogs;

function quietArtifactLogs() {
  if (quietUploads++ === 0) {
    uploadLogs = { stdout: process.stdout.write, stderr: process.stderr.write,
      console: Object.fromEntries(['log', 'info', 'warn', 'debug', 'error'].map(key => [key, console[key]])) };
    // The Actions SDK writes directly to stdout. The relay reserves that stream
    // for model output and must not expose artifact diagnostics on stderr either.
    const discard = (_chunk, encoding, callback) => {
      const done = typeof encoding === 'function' ? encoding : callback;
      if (typeof done === 'function') process.nextTick(done);
      return true;
    };
    process.stdout.write = process.stderr.write = discard;
    for (const key of Object.keys(uploadLogs.console)) console[key] = () => {};
  }
  return () => {
    if (--quietUploads === 0) {
      process.stdout.write = uploadLogs.stdout;
      process.stderr.write = uploadLogs.stderr;
      Object.assign(console, uploadLogs.console);
      uploadLogs = undefined;
    }
  };
}

export async function bytes(response, limit) {
  if (Number(response.headers.get('content-length')) > limit) throw fail();
  const chunks = []; let length = 0;
  for await (const chunk of response.body || []) {
    length += chunk.length; if (length > limit) throw fail(); chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

export async function opsRequest(env, path = '', { method = 'GET', body, fetcher = fetch, signal, wait = delay } = {}) {
  if (!/^(?:\/[a-f0-9-]{36}(?:\/(?:cancel|claim|complete|context|result))?)?$/.test(path)) throw fail();
  // Completion only records an immutable artifact receipt. The endpoint checks
  // identical repeated bodies under a lock; it never republishes model output.
  const completion = method === 'POST' && /^\/[a-f0-9-]{36}\/complete$/.test(path);
  const attempts = method === 'GET' || completion ? 5 : 1;
  const transient = () => Object.assign(fail(), { retryable: true });
  const boundedSignal = milliseconds => signal ? AbortSignal.any([signal, AbortSignal.timeout(milliseconds)]) : AbortSignal.timeout(milliseconds);
  const read = async (url, options, limit, completionReceipt = false) => {
    let response;
    try { response = await fetcher(url, options); } catch { throw transient(); }
    if ([408, 429, 500, 502, 503, 504].includes(response.status) || completionReceipt && response.status === 409) {
      await response.body?.cancel?.().catch(() => {});
      const retry = transient();
      const after = response.headers.get('retry-after');
      if (after) {
        const seconds = /^\d+$/.test(after) ? Number(after) : (Date.parse(after) - Date.now()) / 1000;
        if (!Number.isFinite(seconds) || seconds > 30) throw fail();
        retry.retryAfter = Math.max(0, seconds * 1000);
      }
      throw retry;
    }
    if (!response.ok) throw fail();
    let raw;
    try { raw = await bytes(response, limit); }
    catch (error) {
      if (['TypeError', 'AbortError', 'TimeoutError'].includes(error?.name)) throw transient();
      throw fail();
    }
    try { return JSON.parse(raw.toString('utf8')); } catch { throw fail(); }
  };
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      signal?.throwIfAborted();
      const identityUrl = new URL(env.ACTIONS_ID_TOKEN_REQUEST_URL);
      if (identityUrl.protocol !== 'https:' || !/^[a-z0-9.-]+\.actions\.githubusercontent\.com$/.test(identityUrl.hostname)) throw fail();
      identityUrl.searchParams.set('audience', 'ops:agent-executions');
      const token = await read(identityUrl, { redirect: 'error', signal: boundedSignal(15_000),
        headers: { Authorization: `Bearer ${env.ACTIONS_ID_TOKEN_REQUEST_TOKEN}` } }, 30_000);
      if (typeof token.value !== 'string' || !token.value) throw fail();
      return await read(`${OPS}${path}`, { method, redirect: 'error', signal: boundedSignal(30_000),
        headers: { Authorization: `Bearer ${token.value}`, 'Content-Type': 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) }, 100_000, completion);
    } catch (error) {
      if (signal?.aborted || !error?.retryable || attempt + 1 === attempts) throw fail();
      try { await wait(Math.max(1000 * 2 ** attempt, error.retryAfter || 0), undefined, { signal }); }
      catch { throw fail(); }
    }
  }
}

export async function uploadBundle(name, bundle, env = process.env, client) {
  const raw = JSON.stringify(bundle);
  if (!/^[a-z0-9-]{1,180}$/.test(name) || Buffer.byteLength(raw) > MAX_BUNDLE) throw fail();
  const directory = await mkdtemp(join(env.RUNNER_TEMP, 'agent-artifact-'));
  let restoreLogs;
  try {
    await writeFile(join(directory, 'bundle.json'), raw, { mode: 0o600, flag: 'wx' });
    restoreLogs = quietArtifactLogs();
    const uploader = client || new (await import('@actions/artifact')).DefaultArtifactClient();
    const result = await uploader.uploadArtifact(name, [join(directory, 'bundle.json')], directory, { retentionDays: 7, compressionLevel: 6 });
    if (!Number.isSafeInteger(result.id) || result.id < 1 || !/^[a-f0-9]{64}$/.test(result.digest)) throw fail();
    return { id: result.id, digest: result.digest };
  } catch { throw fail(); }
  finally { restoreLogs?.(); await rm(directory, { recursive: true, force: true }); }
}

export async function downloadBundle(url, digest, fetcher = fetch) {
  try {
    const target = new URL(url);
    if (target.protocol !== 'https:' || target.username || target.password || target.port ||
        !/^[a-z0-9-]+\.blob\.core\.windows\.net$/.test(target.hostname) || !/^[a-f0-9]{64}$/.test(digest)) throw fail();
    const response = await fetcher(target, { redirect: 'error', signal: AbortSignal.timeout(60_000) });
    if (response.status !== 200) throw fail();
    const raw = await bytes(response, 128 * 1024 * 1024);
    const decoded = spawnSync('python3', [fileURLToPath(new URL('./agent_bundle.py', import.meta.url)), digest], {
      input: raw, timeout: 30_000, maxBuffer: MAX_BUNDLE + 1, env: { PATH: process.env.PATH, LANG: 'C.UTF-8' }, encoding: 'utf8' });
    if (decoded.error || decoded.status !== 0) throw fail();
    return JSON.parse(decoded.stdout);
  } catch { throw fail(); }
}
