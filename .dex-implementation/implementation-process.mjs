import { spawn } from 'node:child_process';
import { appendFile, lstat, mkdtemp, readFile, realpath, rm } from 'node:fs/promises';
import { isAbsolute, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { prepareReviewEvidence } from './review-evidence.mjs';

const failure = 'Managed Codex execution failed.';
const apiCredentials = ['OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY', 'DEXCODE_OPENAI_API_KEY'];
const disabled = ['multi_agent', 'multi_agent_v2', 'plugins', 'apps', 'browser_use',
  'browser_use_external', 'in_app_browser', 'view_image', 'computer_use', 'image_generation',
  'hooks', 'code_mode', 'memories', 'remote_plugin', 'workspace_dependencies', 'tool_suggest'];
const credential = /(?:sk-(?:proj-|svcacct-)?|gh[opusr]_|github_pat_)[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}/;

function contains(root, path) {
  const suffix = relative(root, path);
  return !suffix || (!suffix.startsWith('../') && suffix !== '..' && !isAbsolute(suffix));
}

async function boundedFile(path, maximum) {
  const metadata = await lstat(path);
  if (!metadata.isFile() || metadata.size > maximum) throw new Error(failure);
  const bytes = await readFile(path);
  if (bytes.length > maximum) throw new Error(failure);
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
}

// Return a normalized copy with JSON Schema's Unicode code-point limits.
// This boundary must not load repository packages on the OAuth host.
export function validateManagedPlan(result) {
  const textLimits = { title: 300, summary: 8000, problem: 8000, readinessReason: 2000 };
  const listMinimums = { goals: 1, nonGoals: 0, acceptanceCriteria: 1, implementationPlan: 0,
    verificationPlan: 1, dependencies: 0, risks: 0, questions: 0 };
  const fields = ['schemaVersion', 'ready', ...Object.keys(textLimits), ...Object.keys(listMinimums)];
  if (!result || typeof result !== 'object' || Array.isArray(result) ||
      Object.keys(result).length !== fields.length || fields.some(key => !Object.hasOwn(result, key)) ||
      result.schemaVersion !== 1 || typeof result.ready !== 'boolean') throw new Error(failure);
  if (Buffer.byteLength(JSON.stringify(result)) > 40_000) throw new Error(failure);
  const normalized = { ...result };
  const text = (value, maximum) => {
    if (typeof value !== 'string' || !value.trim() || Array.from(value.trim()).length > maximum ||
        value.includes('\0') || !value.isWellFormed()) throw new Error(failure);
    return value.trim();
  };
  for (const [key, maximum] of Object.entries(textLimits)) {
    normalized[key] = text(result[key], maximum);
  }
  for (const [key, minimum] of Object.entries(listMinimums)) {
    const list = result[key];
    if (!Array.isArray(list) || list.length < minimum || list.length > 100) throw new Error(failure);
    normalized[key] = Array.from(list, value => text(value, 2000));
  }
  if ((result.ready && (result.implementationPlan.length === 0 || result.questions.length > 0)) ||
      (!result.ready && result.questions.length === 0)) throw new Error(failure);
  return normalized;
}

export async function runManagedModel(kind, environment = process.env, execute = runManagedProcess) {
  let directory;
  try {
    if (!['plan', 'review'].includes(kind) || apiCredentials.some(name => environment[name])) throw new Error();
    for (const name of ['GITHUB_WORKSPACE', 'HOME', 'RUNNER_TEMP', 'GITHUB_OUTPUT']) {
      if (typeof environment[name] !== 'string' || !isAbsolute(environment[name])) throw new Error();
    }
    const [workspace, home, temporary] = await Promise.all(
      ['GITHUB_WORKSPACE', 'HOME', 'RUNNER_TEMP'].map(name => realpath(environment[name])),
    );
    if (contains(workspace, home) || contains(workspace, temporary) || contains(temporary, workspace)) throw new Error();
    const target = kind === 'review' ? join(workspace, 'review-target') : workspace;
    if (!(await lstat(target)).isDirectory() || await realpath(target) !== target) throw new Error();
    const output = await realpath(environment.GITHUB_OUTPUT);
    if (!contains(temporary, output) || !(await lstat(environment.GITHUB_OUTPUT)).isFile()) throw new Error();
    const prompt = await boundedFile(join(workspace, '.dex/prompts', `dexcode_${kind}.md`), 200_000);
    const schema = join(workspace, '.dex', `${kind === 'plan' ? 'planner' : 'review'}-result.schema.json`);
    JSON.parse(await boundedFile(schema, 100_000));
    directory = await mkdtemp(join(temporary, 'dexcode-model-'));
    const filesystem = { ':root': 'deny', ':minimal': 'read',
      [join(home, '.local/share/mise/installs/node')]: 'read', [target]: kind === 'review' ? 'write' : 'read' };
    if (kind === 'review') {
      for (const name of ['.git', '.github', '.dex', '.codex', '.dex-review-context']) {
        const path = join(target, name);
        try {
          if ((await lstat(path)).isSymbolicLink() || await realpath(path) !== path) throw new Error();
        } catch (error) {
          if (error.code !== 'ENOENT') throw error;
        }
        filesystem[path] = 'read';
      }
      await prepareReviewEvidence(workspace, target, environment);
    }
    const resultFile = join(directory, 'result.json');
    const args = [
      ...(kind === 'review' ? ['--search'] : []),
      '--ephemeral', '--ignore-user-config', '--ignore-rules', '--skip-git-repo-check',
      '--output-schema', schema, '--output-last-message', resultFile,
      '-c', 'default_permissions="managed"',
      '-c', `permissions.managed.filesystem={${Object.entries(filesystem).map(([path, mode]) => `${JSON.stringify(path)}=${JSON.stringify(mode)}`).join(',')}}`,
      '-c', 'permissions.managed.network.enabled=false',
      '-c', 'approval_policy="never"',
      '-c', 'project_doc_max_bytes=0', '-c', 'include_environment_context=false',
      '-c', 'shell_environment_policy.inherit="none"',
      '--enable', 'skip_host_skill_discovery',
      '--enable', 'code_mode_host',
      ...(kind === 'plan' ? ['-c', 'web_search="disabled"'] : []),
      ...disabled.flatMap(feature => ['--disable', feature]), '-',
    ];
    await execute({ args, cwd: directory, timeoutMs: 150 * 60_000,
      env: { PATH: environment.PATH, HOME: home, RUNNER_TEMP: temporary, LANG: 'C.UTF-8',
        CODEX_MODEL: 'gpt-6-astra', CODEX_REASONING_EFFORT: 'max' },
      input: `The repository root is ${JSON.stringify(target)}. Resolve every repository path in the instructions below against that root, and explicitly use that directory for repository commands. Your process starts outside the repository to exclude project configuration. Never read files outside the permitted workspace. Return at most 40000 UTF-8 bytes of JSON.\n\n${prompt}`,
    });
    const text = await boundedFile(resultFile, 40_000);
    const parsed = JSON.parse(text);
    const result = kind === 'plan' ? validateManagedPlan(parsed) : parsed;
    const serialized = JSON.stringify(result);
    if (!result || typeof result !== 'object' || Array.isArray(result) ||
        Buffer.byteLength(serialized) > 40_000 || credential.test(serialized)) throw new Error();
    // One-line JSON cannot terminate a multiline Actions output or add commands.
    await appendFile(output, `result=${serialized}\n`);
  } catch {
    throw new Error(failure);
  } finally {
    if (directory) await rm(directory, { recursive: true, force: true });
  }
}

// The namespace controller stays alive until the OAuth wrapper has handled TERM.
// When PID 1 exits, Linux also kills children that escaped the wrapper's group.
export function runManagedProcess(invocation) {
  if (process.platform !== 'linux') return Promise.reject(new Error(failure));
  return new Promise((resolve, reject) => {
    const { env, cwd, timeoutMs } = invocation;
    const child = spawn('/usr/bin/bwrap', [
      '--unshare-user', '--unshare-pid', '--as-pid-1', '--die-with-parent', '--new-session',
      '--bind', '/', '/', '--dev', '/dev', '--proc', '/proc', '--',
      process.execPath, fileURLToPath(import.meta.url), '_supervise',
    ], { env, cwd, detached: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let stopped = false;
    let settled = false;
    let bytes = 0;
    let forced;
    const kill = () => {
      try { if (child.pid) process.kill(-child.pid, 'SIGKILL'); } catch { /* Already exited. */ }
    };
    const stop = () => {
      if (settled || stopped) return;
      stopped = true;
      child.stdin.write('{"cancel":true}\n');
      forced = setTimeout(kill, 7000);
    };
    const deadline = setTimeout(stop, timeoutMs + 1000);
    const finish = ok => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      clearTimeout(forced);
      process.removeListener('SIGTERM', stop);
      process.removeListener('SIGINT', stop);
      if (ok && !stopped) resolve();
      else reject(new Error(failure));
    };
    process.once('SIGTERM', stop);
    process.once('SIGINT', stop);
    for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > 10_000_000) stop();
    });
    child.once('error', () => finish(false));
    child.once('close', code => finish(code === 0));
    child.stdin.on('error', () => stop());
    const request = JSON.stringify(invocation);
    if (Buffer.byteLength(request) > 1_000_000) { kill(); finish(false); }
    else child.stdin.write(`${request}\n`);
  });
}

export function superviseManagedProcess({ args, env, cwd, input, timeoutMs }) {
  return new Promise((resolve, reject) => {
    const grouped = process.platform !== 'win32';
    const child = spawn('codex-ci', args, { env, cwd, detached: grouped, stdio: ['pipe', 'pipe', 'pipe'] });
    let stopped = false;
    let settled = false;
    let bytes = 0;
    let forceKill;
    const signal = value => {
      try {
        if (grouped && child.pid) process.kill(-child.pid, value);
        else child.kill(value);
      } catch { /* The process may have exited while its pipes were closing. */ }
    };
    const stop = () => {
      if (stopped || settled) return;
      stopped = true;
      signal('SIGTERM');
      forceKill = setTimeout(() => signal('SIGKILL'), 5000);
    };
    const timer = setTimeout(stop, timeoutMs);
    const finish = ok => {
      if (settled) return;
      signal('SIGKILL');
      settled = true;
      clearTimeout(timer);
      clearTimeout(forceKill);
      process.removeListener('SIGTERM', stop);
      process.removeListener('SIGINT', stop);
      if (ok && !stopped) resolve();
      else reject(new Error(failure));
    };
    process.once('SIGTERM', stop);
    process.once('SIGINT', stop);
    for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => {
      bytes += chunk.length;
      if (bytes > 10_000_000) stop();
    });
    child.once('error', () => finish(false));
    child.once('exit', () => {
      signal('SIGKILL');
      // Detached children can retain these pipes. Diagnostics are private and
      // unused, so close our readers and let PID 1 exit to kill the namespace.
      child.stdout.destroy();
      child.stderr.destroy();
    });
    child.once('close', code => finish(code === 0));
    child.stdin.on('error', error => { if (error.code !== 'EPIPE') stop(); });
    child.stdin.end(input);
  });
}

function superviseNamespace() {
  let buffer = '';
  let started = false;
  const startup = setTimeout(() => process.exit(1), 5000);
  process.stdin.setEncoding('utf8');
  process.stdin.on('end', () => process.exit(1));
  process.stdin.on('error', () => process.exit(1));
  process.stdin.on('data', chunk => {
    buffer += chunk;
    if (Buffer.byteLength(buffer) > 1_000_000) process.exit(1);
    while (buffer.includes('\n')) {
      const end = buffer.indexOf('\n');
      const line = buffer.slice(0, end);
      buffer = buffer.slice(end + 1);
      try {
        const request = JSON.parse(line);
        if (!started) {
          if (!request || !Array.isArray(request.args) || !request.args.every(value => typeof value === 'string') ||
              typeof request.input !== 'string' || !isAbsolute(request.cwd) || !request.env ||
              !Number.isSafeInteger(request.timeoutMs) || request.timeoutMs < 1 || request.timeoutMs > 150 * 60_000) process.exit(1);
          started = true;
          clearTimeout(startup);
          superviseManagedProcess(request).then(() => process.exit(0), () => process.exit(1));
        } else if (request?.cancel === true) process.emit('SIGTERM');
        else process.exit(1);
      } catch { process.exit(1); }
    }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.argv[2] === '_supervise') superviseNamespace();
  else runManagedModel(process.argv[2]).then(() => {
    console.log('Bounded Codex result prepared for the separate reporting job.');
  }).catch(() => {
    console.error(failure);
    process.exitCode = 1;
  });
}
