import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { fail, MAX_BUNDLE } from './agent-relay-protocol.mjs';

export const CONTROL = 'https://control.m12n.org/api/v1/agent-executions';

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

// Only fixed categories and an HTTP status cross this boundary. Never retain response bodies, tokens, URLs or a cause.
const requestFailure = (source, reason, status = null, retryAfter) => {
  const retryable = ['network', 'timeout', 'rate_limited', 'server_error', 'receipt_pending'].includes(reason);
  return Object.assign(fail(), { retryable, relay: { kind: retryable ? 'outage' : 'refusal', source, reason, status },
    ...(retryAfter === undefined ? {} : { retryAfter }) });
};

export async function controlRequest(env, path = '', { method = 'GET', body, fetcher = fetch, signal, wait = delay, attempts } = {}) {
  if (!/^(?:\/[a-f0-9-]{36}(?:\/(?:cancel|claim|complete|context|result))?)?$/.test(path)) throw fail();
  // Completion records an immutable receipt and accepts identical repeats. Its 409 means the artifact is not visible
  // yet. A 409 on any other endpoint is permanent, as are all other 4xx except request timeout (408) and throttling (429).
  const completion = method === 'POST' && /^\/[a-f0-9-]{36}\/complete$/.test(path);
  const maxAttempts = method === 'GET' || completion ? 5 : 1;
  // The polling client supplies one attempt: its own clock budget and jittered backoff replace nested transport retries.
  if (attempts === undefined) attempts = maxAttempts;
  if (!Number.isSafeInteger(attempts) || attempts < 1 || attempts > maxAttempts) throw fail();
  const boundedSignal = milliseconds => signal ? AbortSignal.any([signal, AbortSignal.timeout(milliseconds)]) : AbortSignal.timeout(milliseconds);
  const timedOut = error => ['AbortError', 'TimeoutError'].includes(error?.name);
  // Redirects are never followed (so the credential cannot travel to another host) and arrive as a 3xx answer, which is a
  // refusal below. `redirect: 'error'` would reject the fetch instead, and that rejection reads as a network outage.
  const read = async (url, options, limit, source, completionReceipt = false) => {
    let response;
    try { response = await fetcher(url, options); }
    catch (error) { throw requestFailure(source, timedOut(error) ? 'timeout' : 'network'); }
    const status = response.status;
    if (!response.ok) {
      await response.body?.cancel?.().catch(() => {});
      const reason = status === 408 ? 'timeout' : status === 429 ? 'rate_limited' : status >= 500 ? 'server_error'
        : completionReceipt && status === 409 ? 'receipt_pending' : 'refused';
      const after = response.headers.get('retry-after');
      const seconds = after && (/^\d+$/.test(after) ? Number(after) : (Date.parse(after) - Date.now()) / 1000);
      // Ignore malformed Retry-After, but retain valid long delays for the client's bounded wait. Never make 429 permanent.
      const retryAfter = after && Number.isFinite(seconds) ? Math.min(Math.max(0, seconds), 3600) * 1000 : undefined;
      throw requestFailure(source, reason, status, retryAfter);
    }
    let raw;
    try { raw = await bytes(response, limit); }
    catch (error) {
      if (error?.name === 'TypeError' || timedOut(error)) throw requestFailure(source, timedOut(error) ? 'timeout' : 'network');
      throw requestFailure(source, 'invalid_response', status);
    }
    try { return JSON.parse(raw.toString('utf8')); } catch { throw requestFailure(source, 'invalid_response', status); }
  };
  // Requests are sequential: only a failed, repeatable attempt may start another one.
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      signal?.throwIfAborted();
      const identityUrl = new URL(env.ACTIONS_ID_TOKEN_REQUEST_URL);
      if (identityUrl.protocol !== 'https:' || !/^[a-z0-9.-]+\.actions\.githubusercontent\.com$/.test(identityUrl.hostname)) throw fail();
      identityUrl.searchParams.set('audience', 'control:agent-executions');
      const token = await read(identityUrl, { redirect: 'manual', signal: boundedSignal(15_000),
        headers: { Authorization: `Bearer ${env.ACTIONS_ID_TOKEN_REQUEST_TOKEN}` } }, 30_000, 'identity');
      if (typeof token?.value !== 'string' || !token.value) throw requestFailure('identity', 'invalid_response', 200);
      return await read(`${CONTROL}${path}`, { method, redirect: 'manual', signal: boundedSignal(30_000),
        headers: { Authorization: `Bearer ${token.value}`, 'Content-Type': 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) }, 100_000, 'control', completion);
    } catch (error) {
      if (signal?.aborted) throw signal.reason?.name === 'TimeoutError' ? requestFailure('control', 'timeout') : fail();
      // Preserve the classification after attempts are spent, without preserving a provider exception.
      const final = () => error?.relay ? requestFailure(error.relay.source, error.relay.reason, error.relay.status, error.retryAfter) : fail();
      if (!error?.retryable || attempt + 1 === attempts || error.retryAfter > 30_000) throw final();
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
