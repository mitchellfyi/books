import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import { open, lstat, realpath, mkdir, writeFile, rename, unlink, readdir, rmdir } from 'node:fs/promises';
import { resolve, dirname, join, isAbsolute } from 'node:path';
import { spawnSync } from 'node:child_process';

export const fail = () => new Error('Hosted agent request failed; private details withheld.');

export function executionDiagnostic(stage, sourceRunId, execution = {}) {
  const stages = ['preparation', 'context-upload', 'submission', 'polling', 'execution', 'head-verification',
    'result-download', 'result-validation', 'apply-changes', 'output'];
  const statuses = ['queued', 'dispatching', 'running', 'succeeded', 'failed', 'cancelled', 'blocked'];
  const codes = ['model_failed', 'checkpoint_failed', 'cancelled', 'invalid_result', 'dispatch_uncertain'];
  const run = value => /^[1-9][0-9]{0,19}$/.test(String(value)) ? String(value) : 'unknown';
  const id = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(execution.id || '') ? execution.id : 'unknown';
  return `Ops execution failure: stage=${stages.includes(stage) ? stage : 'unknown'}; source_run=${run(sourceRunId)}; ` +
    `execution=${id}; executor_run=${run(execution.executor_run_id)}; state=${statuses.includes(execution.status) ? execution.status : 'unknown'}; ` +
    `code=${codes.includes(execution.error_code) ? execution.error_code : 'unknown'}.`;
}

// The executor never reached a model verdict, so the pull request has not been
// reviewed. Its content did not cause this and a later attempt can still work.
export function executionUnavailable(line) {
  const match = /^Ops execution failure: stage=[a-z-]+; source_run=(?:[0-9]+|unknown); execution=(?:[a-f0-9-]+|unknown); executor_run=(?:[0-9]+|unknown); state=[a-z]+; code=([a-z_]+)\.$/.exec(line || '');
  return ['model_failed', 'checkpoint_failed', 'cancelled', 'dispatch_uncertain'].includes(match?.[1]);
}

export function readExecutionDiagnostic(text) {
  if (typeof text !== 'string' || Buffer.byteLength(text) > 64_000) return null;
  for (const line of text.split('\n')) {
    const match = /^Ops execution failure: stage=([a-z-]+); source_run=([0-9]+|unknown); execution=([a-f0-9-]+|unknown); executor_run=([0-9]+|unknown); state=([a-z]+); code=([a-z_]+)\.$/.exec(line);
    if (match && line === executionDiagnostic(match[1], match[2], { id: match[3], executor_run_id: match[4], status: match[5], error_code: match[6] })) return line;
  }
  return null;
}
export const digest = value => createHash('sha256').update(value).digest('hex');
export const MAX_FILE = 8_000_000;
export const MAX_BUNDLE = 96_000_000;
const MAX_SOURCE = 64_000_000;
const protectedDirectories = new Set(['.git', '.github', '.dex', '.codex', '.claude', '.ops-agent', '.ops-control', '.review', '.dex-review-context', '.dex-implementation', '.dex-implementation-context', 'AGENTS.md', 'CLAUDE.md']);
const ignoredDirectories = new Set(['.git', '.codex', '.ops-agent', '.ops-control', '.ssh', '.aws', '.gnupg', 'node_modules', '.next', '.nuxt', '.output', 'coverage', 'vendor']);
const secretFile = /(?:^|\/)(?:\.npmrc|\.netrc|\.yarnrc(?:\.yml)?|\.env(?:\..*)?|auth\.json|credentials(?:\.[^/]*)?|[^/]*\.(?:pem|key|p12|pfx))$/i;
const binaryFile = /\.(?:png|jpe?g|webp|gif|ico|pdf|pptx|zip|gz|mp[34]|webm|woff2?|ttf|eot|otf|sqlite3?|db)$|(?:^|\/)areaflags\.map$/i;

export function safePath(path, { writable = false } = {}) {
  if (typeof path !== 'string' || path.length < 1 || path.length > 1024 || path.includes('\\') ||
      [...path].some(character => character.codePointAt(0) < 32 || character.codePointAt(0) === 127) ||
      isAbsolute(path) || path.split('/').some(part => ['', '.', '..'].includes(part)) || secretFile.test(path.normalize('NFKC')) ||
      path.split('/').some(part => ignoredDirectories.has(part.normalize('NFKC').toLowerCase())) || (writable && path.split('/').some(part => protectedDirectories.has(part)))) throw fail();
  return path;
}

export function decodeFile(entry, options) {
  safePath(entry?.path, options);
  if (![0o644, 0o755].includes(entry.mode) || typeof entry.content !== 'string' || entry.content.length > MAX_FILE * 1.4) throw fail();
  // The canonical round trip rejects malformed base64 without a repeated-group
  // regexp, which exhausts V8's stack on valid multi-megabyte source files.
  const raw = Buffer.from(entry.content, 'base64');
  if (raw.length > MAX_FILE || raw.toString('base64') !== entry.content) throw fail();
  return raw;
}

export async function readRegular(path, maximum = MAX_FILE) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > maximum) throw fail();
    const content = await file.readFile();
    if (content.length !== stat.size) throw fail();
    return { content, mode: stat.mode & 0o111 ? 0o755 : 0o644 };
  } finally { await file.close(); }
}

export async function snapshot(workspace) {
  if (!isAbsolute(workspace) || await realpath(workspace) !== workspace) throw fail();
  const run = spawnSync('git', ['-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
    '-C', workspace, 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
    encoding: 'utf8', maxBuffer: 2_000_000, timeout: 15_000, env: { PATH: process.env.PATH, HOME: '/nonexistent', GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' } });
  if (run.error || run.status !== 0) throw fail();
  const paths = [...new Set(run.stdout.split('\0').filter(Boolean))];
  for (const path of [...paths]) {
    if (!path.endsWith('/')) continue;
    const nested = path.slice(0, -1);
    try { safePath(nested); } catch { continue; }
    if (await realpath(join(workspace, nested)) !== join(workspace, nested)) throw fail();
    // Git lists an untracked nested checkout as one directory. Expand only
    // that checkout's own tracked and unignored files, without its .git data.
    for (const entry of await snapshot(join(workspace, nested))) paths.push(`${nested}/${entry.path}`);
  }
  paths.sort();
  if (paths.length > 20_000) throw fail();
  const entries = []; let total = 0;
  for (const path of paths) {
    try { safePath(path); } catch { continue; }
    if (binaryFile.test(path)) continue;
    const absolute = join(workspace, path);
    try {
      if (await realpath(absolute) !== absolute || !(await lstat(absolute)).isFile()) continue;
      const { content, mode } = await readRegular(absolute);
      total += content.length;
      if (total > MAX_SOURCE) throw fail();
      entries.push({ path, mode, content: content.toString('base64') });
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  return entries;
}

export async function materialize(entries, workspace) {
  if (!Array.isArray(entries) || entries.length > 20_000) throw fail();
  const seen = new Set(); let bytes = 0;
  const decoded = entries.map(entry => {
    const raw = decodeFile(entry);
    bytes += raw.length;
    if (seen.has(entry.path) || bytes > MAX_SOURCE) throw fail();
    seen.add(entry.path);
    return { entry, raw };
  });
  await mkdir(workspace, { mode: 0o700 });
  for (const { entry, raw } of decoded) {
    const path = join(workspace, entry.path);
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    await writeFile(path, raw, { flag: 'wx', mode: entry.mode });
  }
}

export function changesBetween(before, after) {
  const previous = new Map(before.map(entry => [entry.path, entry]));
  const current = new Map(after.map(entry => [entry.path, entry]));
  const changes = [];
  for (const path of new Set([...previous.keys(), ...current.keys()])) {
    const old = previous.get(path), next = current.get(path);
    if (old?.content === next?.content && old?.mode === next?.mode) continue;
    safePath(path, { writable: true });
    changes.push({ path, before: old ? digest(decodeFile(old)) : null, before_mode: old?.mode ?? null,
      after: next || null });
  }
  return changes;
}

export async function applyChanges(changes, workspace) {
  if (!Array.isArray(changes) || changes.length > 1000 || await realpath(workspace) !== workspace) throw fail();
  const validated = []; const seen = new Set(); let total = 0;
  for (const change of changes) {
    const path = safePath(change?.path, { writable: true });
    if (seen.has(path) || !(change.before === null || /^[a-f0-9]{64}$/.test(change.before)) ||
        !(change.before_mode === null || [0o644, 0o755].includes(change.before_mode))) throw fail();
    seen.add(path);
    const raw = change.after ? decodeFile(change.after, { writable: true }) : null;
    if (change.after && change.after.path !== path) throw fail();
    total += raw?.length || 0;
    if (total > 16_000_000) throw fail();
    const absolute = resolve(workspace, path);
    validated.push({ change, absolute, raw });
  }
  const removals = new Set(validated.filter(item => item.raw === null).map(item => item.absolute));
  const writes = new Set(validated.filter(item => item.raw !== null).map(item => item.absolute));
  const directories = new Set();
  const removableDirectory = async path => {
    if (directories.size >= 20_000) throw fail();
    directories.add(path);
    for (const entry of await readdir(path, { withFileTypes: true })) {
      const child = join(path, entry.name);
      safePath(child.slice(workspace.length + 1), { writable: true });
      if (entry.isDirectory()) await removableDirectory(child);
      else if (!entry.isFile() || !removals.has(child)) throw fail();
    }
  };
  for (const { change, absolute, raw } of validated) {
    let parent = dirname(absolute);
    let removedAncestor = false;
    while (parent !== workspace) {
      if (raw !== null && writes.has(parent)) throw fail();
      try {
        if (await realpath(parent) !== parent) throw fail();
        const stat = await lstat(parent);
        if (!stat.isDirectory()) {
          if (!stat.isFile() || !removals.has(parent)) throw fail();
          removedAncestor = true;
        }
      } catch (error) { if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error; }
      parent = dirname(parent);
    }
    let existing;
    if (!removedAncestor) {
      try {
        const stat = await lstat(absolute);
        if (stat.isDirectory() && raw !== null) await removableDirectory(absolute);
        else existing = await readRegular(absolute);
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    if (raw === null && !existing) throw fail();
    if ((existing ? digest(existing.content) : null) !== change.before || (existing?.mode ?? null) !== change.before_mode) throw fail();
  }
  // Validate every original first, then remove only the files named by the
  // patch and empty directories that must become files.
  for (const absolute of removals) await unlink(absolute);
  for (const directory of [...directories].sort((a, b) => b.length - a.length)) await rmdir(directory);
  for (const { change, absolute, raw } of validated) {
    if (raw === null) continue;
    await mkdir(dirname(absolute), { recursive: true });
    const temporary = `${absolute}.agent-next`;
    await writeFile(temporary, raw, { flag: 'wx', mode: change.after.mode });
    await rename(temporary, absolute);
  }
}

export async function normalizeInvocation(args, input, workspace, temporary, control = workspace) {
  if (!Array.isArray(args) || typeof input !== 'string' || Buffer.byteLength(input) > 4_100_000) throw fail();
  const flags = new Set(['--search', '--json', '--ephemeral', '--ignore-user-config', '--ignore-rules', '--skip-git-repo-check', '-']);
  const features = new Set(['shell_tool', 'multi_agent', 'multi_agent_v2', 'plugins', 'apps', 'browser_use', 'browser_use_external',
    'in_app_browser', 'view_image', 'computer_use', 'image_generation', 'hooks', 'code_mode_host', 'code_mode', 'memories',
    'remote_plugin', 'workspace_dependencies', 'tool_suggest', 'skip_host_skill_discovery']);
  const normalized = [], images = []; let schema, output;
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (typeof arg !== 'string' || arg.length > 20_000) throw fail();
    if (flags.has(arg)) { if (['--search', '--json'].includes(arg)) normalized.push(arg); continue; }
    const value = args[++index];
    if (typeof value !== 'string') throw fail();
    if (arg === '--image' || arg === '-i') {
      const path = resolve(value);
      if (!path.startsWith(`${temporary}/`) || !path.endsWith('.webp') || await realpath(path) !== path || images.length >= 8) throw fail();
      const { content } = await readRegular(path, 500_000);
      if (content.length < 26 || content.toString('latin1', 0, 4) !== 'RIFF' ||
          content.toString('latin1', 8, 12) !== 'WEBP' || content.readUInt32LE(4) !== content.length - 8) throw fail();
      images.push({ content: content.toString('base64'), sha256: digest(content) });
    } else if (arg === '--output-schema') {
      const path = resolve(value);
      if (!(path.startsWith(`${workspace}/`) || path.startsWith(`${temporary}/`) || path.startsWith(`${control}/`)) ||
          !path.endsWith('.schema.json') || await realpath(path) !== path) throw fail();
      schema = (await readRegular(path, 100_000)).content.toString('utf8'); JSON.parse(schema);
    } else if (arg === '--output-last-message') {
      const path = resolve(value);
      if (!path.startsWith(`${temporary}/`) || await realpath(dirname(path)) !== dirname(path)) throw fail();
      output = path;
    } else if (arg === '--disable' || arg === '--enable') {
      if (!features.has(value)) throw fail();
      normalized.push(arg, value);
    } else if (arg === '-c' || arg === '--config') {
      // Caller permissions are replaced by the central workspace policy. Keep
      // only the stricter request to disable built-in search.
      if (value === 'web_search="disabled"') normalized.push('-c', value);
      else if (!/^(?:default_permissions|permissions\.[a-z_]+\.(?:filesystem|network\.enabled)|approval_policy|project_doc_max_bytes|include_environment_context|shell_environment_policy\.inherit|model_reasoning_effort)=/.test(value)) throw fail();
    } else if (arg === '--model' || arg === '-m') {
      if (value !== 'gpt-6-astra') throw fail();
    } else if (arg === '--sandbox' || arg === '-s') {
      if (!['danger-full-access', 'workspace-write', 'read-only'].includes(value)) throw fail();
    } else throw fail();
  }
  return { args: normalized, images, input: input.split(workspace).join('/tmp/agent-workspace'), schema, output };
}
