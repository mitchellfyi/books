import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { lstat, readFile, realpath, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const failure = 'Managed review evidence could not be verified.';
const maximum = 8_000_000;
const contextName = '.dex-review-context';
const contextFiles = ['run-spec.json', 'prompt.md', 'review-result.schema.json'];
// Keep the relay's extension exclusions when considering deleted base files.
const binaryPath = /\.(?:png|jpe?g|webp|gif|ico|pdf|pptx|zip|gz|mp[34]|webm|woff2?|ttf|eot|otf|sqlite3?|db)$|(?:^|\/)areaflags\.map$/i;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const decode = bytes => new TextDecoder('utf-8', { fatal: true }).decode(bytes);

export async function canonicalizeReviewCheckout(workspace, target, environment = process.env) {
  try {
    if (target !== join(workspace, 'review-target') || await realpath(workspace) !== workspace ||
        await realpath(target) !== target || !(await lstat(target)).isDirectory()) throw new Error();
    const specPath = join(workspace, '.dex/review-run-spec.json');
    if (!(await lstat(specPath)).isFile()) throw new Error();
    const specBytes = await readFile(specPath);
    if (specBytes.length > 200_000) throw new Error();
    const spec = JSON.parse(decode(specBytes));
    const head = spec.pull_request?.head_sha;
    if (typeof head !== 'string' || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(head) ||
        typeof spec.repository?.full_name !== 'string' || spec.repository.full_name !== environment.GITHUB_REPOSITORY) throw new Error();
    await canonicalizeCheckout(workspace, target, head, environment, 'review');
  } catch { throw new Error(failure); }
}

export async function canonicalizeCheckout(workspace, target, head, environment = process.env, kind = 'review') {
  try {
    if (!['review', 'implementation'].includes(kind) || typeof head !== 'string' || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(head)) throw new Error();
    const reservedContext = kind === 'review' ? contextName : '.dex-implementation-context';
    const gitDirectory = join(target, '.git');
    if (target !== join(workspace, `${kind}-target`) || await realpath(workspace) !== workspace ||
        await realpath(target) !== target || !(await lstat(target)).isDirectory() ||
        await realpath(gitDirectory) !== gitDirectory || !(await lstat(gitDirectory)).isDirectory()) throw new Error();
    const deadline = Date.now() + 60_000;
    const git = args => {
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new Error();
      const result = spawnSync('git', ['--no-replace-objects', '--literal-pathspecs', '--no-pager',
        '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-c', 'core.attributesFile=/dev/null',
        '-c', 'core.autocrlf=false', '--git-dir', gitDirectory, '--work-tree', target, '-C', target, ...args], {
        timeout: Math.min(15_000, remaining), maxBuffer: 3_000_000,
        env: { PATH: environment.PATH, HOME: '/nonexistent', GIT_CONFIG_NOSYSTEM: '1',
          GIT_CONFIG_GLOBAL: '/dev/null', GIT_NO_LAZY_FETCH: '1', GIT_TERMINAL_PROMPT: '0' },
      });
      if (result.error || result.status !== 0 || result.signal) throw new Error();
      return result.stdout;
    };
    if (decode(git(['rev-parse', '--verify', 'HEAD^{commit}'])).trim() !== head) throw new Error();
    const tree = decode(git(['ls-tree', '-r', '-z', '--full-tree', head])).split('\0').filter(Boolean);
    if (tree.length > 20_000) throw new Error();
    const directories = new Set([target]);
    for (const row of tree) {
      const match = row.match(/^(100644|100755|120000|160000) (blob|commit) [a-f0-9]{40}(?:[a-f0-9]{24})?\t([\s\S]+)$/);
      if (!match || (match[1] === '160000') !== (match[2] === 'commit')) throw new Error();
      const parts = match[3].split('/');
      if (parts.some(part => ['', '.', '..', '.git'].includes(part)) || parts[0] === reservedContext) throw new Error();
      let parent = target;
      for (const part of parts.slice(0, -1)) {
        parent = join(parent, part);
        if (directories.has(parent)) continue;
        if (await realpath(parent) !== parent || !(await lstat(parent)).isDirectory()) throw new Error();
        directories.add(parent);
      }
      const stat = await lstat(join(target, match[3]));
      if (match[1] === '120000' ? !stat.isSymbolicLink() : match[1] === '160000' ? !stat.isDirectory()
        : !stat.isFile() || stat.nlink !== 1) throw new Error();
    }
    const info = join(gitDirectory, 'info');
    if (await realpath(info) !== info || !(await lstat(info)).isDirectory()) throw new Error();
    // info/attributes outranks repository attributes, including nested files.
    // Disable conversion before read-tree, which can also call clean filters.
    await writeFile(join(info, 'attributes'), '* -text -ident -filter -working-tree-encoding\n', { flag: 'wx', mode: 0o600 });
    // Only this fresh-checkout entry point replaces files. Evidence preparation
    // later retains its exact byte checks and rejects any subsequent drift.
    // Discard cached file stats so checkout-index cannot skip converted bytes.
    git(['read-tree', '--empty']);
    git(['read-tree', '--reset', head]);
    if (git(['ls-files', '--others', '-z']).length) throw new Error();
    git(['checkout-index', '--all', '--force']);
    if (decode(git(['rev-parse', '--verify', 'HEAD^{commit}'])).trim() !== head) throw new Error();
  } catch {
    throw new Error(failure);
  }
}

export async function prepareReviewEvidence(workspace, target, environment = process.env) {
  try {
    const gitDirectory = join(target, '.git');
    if (await realpath(target) !== target || !(await lstat(target)).isDirectory() ||
        await realpath(gitDirectory) !== gitDirectory || !(await lstat(gitDirectory)).isDirectory()) throw new Error();
    const protocolPath = join(workspace, '.ops-agent/agent-relay-protocol.mjs');
    if (await realpath(protocolPath) !== protocolPath || !(await lstat(protocolPath)).isFile()) throw new Error();
    const { safePath, snapshot } = await import(pathToFileURL(protocolPath).href);
    const specPath = join(workspace, '.dex/review-run-spec.json');
    if (!(await lstat(specPath)).isFile()) throw new Error();
    const specBytes = await readFile(specPath);
    if (specBytes.length > 200_000) throw new Error();
    const spec = JSON.parse(decode(specBytes));
    const { base_sha: base, head_sha: head } = spec.pull_request || {};
    if (![base, head].every(value => typeof value === 'string' && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(value)) ||
        base.length !== head.length || typeof spec.repository?.full_name !== 'string' ||
        spec.repository.full_name !== environment.GITHUB_REPOSITORY ||
        !/^[1-9][0-9]{0,15}$/.test(environment.GITHUB_REPOSITORY_ID || '') ||
        !Number.isSafeInteger(Number(environment.GITHUB_REPOSITORY_ID)) || typeof spec.run_id !== 'string' ||
        !spec.run_id || spec.run_id.length > 200) throw new Error();
    const deadline = Date.now() + 60_000;
    const git = (args, limit = maximum, input) => {
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new Error();
      const result = spawnSync('git', ['--no-replace-objects', '--literal-pathspecs', '--no-pager',
        '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-c', 'core.attributesFile=/dev/null',
        '-c', 'diff.external=', '-c', 'diff.algorithm=myers', '-C', target, ...args], {
        timeout: Math.min(15_000, remaining), maxBuffer: limit, input,
        env: { PATH: environment.PATH, HOME: '/nonexistent', GIT_CONFIG_NOSYSTEM: '1',
          GIT_CONFIG_GLOBAL: '/dev/null', GIT_NO_LAZY_FETCH: '1', GIT_TERMINAL_PROMPT: '0', GIT_OPTIONAL_LOCKS: '0' },
      });
      if (result.error || result.status !== 0 || result.signal) throw new Error();
      return result.stdout;
    };
    if (decode(git(['rev-parse', '--verify', 'HEAD'], 200)).trim() !== head) throw new Error();
    for (const sha of [base, head]) if (decode(git(['rev-parse', '--verify', `${sha}^{commit}`], 200)).trim() !== sha) throw new Error();
    const tree = sha => {
      const entries = new Map();
      for (const row of decode(git(['ls-tree', '-r', '-z', '--full-tree', sha], 3_000_000)).split('\0').filter(Boolean)) {
        const match = row.match(/^([0-7]{6}) (blob|commit) ([a-f0-9]{40}|[a-f0-9]{64})\t([\s\S]+)$/);
        if (!match || entries.has(match[4]) || entries.size >= 20_000) throw new Error();
        entries.set(match[4], { mode: match[1], type: match[2], oid: match[3] });
      }
      return entries;
    };
    const before = tree(base), after = tree(head);
    const reason = (path, entry) => {
      try { safePath(path); } catch { return 'excluded-by-relay'; }
      if (path === contextName || path.startsWith(`${contextName}/`)) return 'reserved-review-context';
      if (binaryPath.test(path)) return 'binary-path';
      if (entry && (!['100644', '100755'].includes(entry.mode) || entry.type !== 'blob')) return 'unsupported-file-type';
    };
    const entries = await snapshot(target);
    if (entries.some(entry => entry.path.startsWith(`${contextName}/`) &&
        !contextFiles.some(name => entry.path === `${contextName}/${name}`))) throw new Error();
    const source = new Map(entries.filter(entry => !entry.path.startsWith(`${contextName}/`)).map(entry => [entry.path, entry]));
    const files = [];
    for (const [path, entry] of after) {
      if (reason(path, entry)) continue;
      const actual = source.get(path);
      if (!actual) throw new Error();
      const bytes = Buffer.from(actual.content, 'base64');
      const oid = createHash(head.length === 40 ? 'sha1' : 'sha256').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
      if (oid !== entry.oid || actual.mode !== (entry.mode === '100755' ? 0o755 : 0o644)) throw new Error();
      files.push({ path, mode: actual.mode, sha256: hash(bytes) });
      source.delete(path);
    }
    // The model must not receive untracked or modified source attributed to HEAD.
    if (source.size) throw new Error();
    const included = [], excluded = [];
    let inspectedBytes = 0;
    for (const path of [...new Set([...before.keys(), ...after.keys()])].sort()) {
      const old = before.get(path), next = after.get(path);
      if (old?.oid === next?.oid && old?.mode === next?.mode) continue;
      if (included.length + excluded.length >= 1000) throw new Error();
      let omission = reason(path, old) || reason(path, next);
      if (!omission) for (const entry of [old, next].filter(Boolean)) {
        const bytes = git(['cat-file', 'blob', entry.oid]);
        inspectedBytes += bytes.length;
        if (inspectedBytes > 64_000_000) throw new Error();
        try { if (bytes.includes(0)) throw new Error(); decode(bytes); }
        catch { omission = 'binary-content'; break; }
      }
      if (omission) excluded.push({ path, reason: omission });
      else included.push(path);
    }
    if (Buffer.byteLength(included.join('\0')) > 100_000) throw new Error();
    let diff = '';
    if (included.length) {
      const options = ['--no-ext-diff', '--no-textconv', '--no-renames', '--ignore-submodules=all',
        '--text', '--no-color', '--src-prefix=a/', '--dst-prefix=b/', '--unified=3'];
      const selection = [base, head, '--', ...included];
      const records = bytes => {
        const value = decode(bytes);
        if (!value.endsWith('\0')) throw new Error();
        return value.slice(0, -1).split('\0');
      };
      const verifyPaths = paths => {
        paths.sort();
        if (paths.length !== included.length || paths.some((path, index) => path !== included[index])) throw new Error();
      };
      // Literal pathspecs still recurse across file/directory transitions. Check
      // the complete selection before asking Git to emit any file contents.
      verifyPaths(records(git(['diff', ...options, '--name-only', '-z', ...selection], 200_000)));
      diff = decode(git(['diff', ...options, ...selection], 4_000_000));
      // --numstat parses without applying. Check both directions so the old
      // and new patch headers must each name exactly the verified files.
      for (const reverse of [[], ['--reverse']]) {
        verifyPaths(records(git(['apply', '--numstat', '-z', ...reverse], 200_000, diff)).map(row => {
          const match = row.match(/^[0-9]+\t[0-9]+\t([\s\S]+)$/);
          if (!match) throw new Error();
          return match[1];
        }));
      }
    }
    const context = join(target, contextName);
    if (await realpath(context) !== context || !(await lstat(context)).isDirectory()) throw new Error();
    for (const name of contextFiles) {
      const path = join(context, name);
      const trusted = name === 'run-spec.json' ? specBytes : await readFile(join(workspace, '.dex',
        name === 'prompt.md' ? 'prompts/dexcode_review.md' : 'review-result.schema.json'));
      if (await realpath(path) !== path || !(await lstat(path)).isFile() || !(await readFile(path)).equals(trusted) ||
          !entries.some(entry => entry.path === `${contextName}/${name}`)) throw new Error();
    }
    const evidence = { schemaVersion: 1, repository: spec.repository.full_name,
      repositoryId: Number(environment.GITHUB_REPOSITORY_ID), runId: spec.run_id,
      specSha256: hash(specBytes), baseSha: base, headSha: head,
      headTree: decode(git(['rev-parse', `${head}^{tree}`], 200)).trim(),
      files: files.sort((a, b) => a.path.localeCompare(b.path)), changedPaths: included,
      excludedChanges: excluded, diffSha256: hash(diff), diff };
    const raw = JSON.stringify(evidence);
    if (Buffer.byteLength(raw) > maximum) throw new Error();
    await writeFile(join(context, 'review-evidence.json'), raw, { flag: 'wx', mode: 0o600 });
    const expected = new Map(entries.map(entry => [entry.path, entry]));
    expected.set(`${contextName}/review-evidence.json`, { mode: 0o644, content: Buffer.from(raw).toString('base64') });
    const transmitted = await snapshot(target);
    if (transmitted.length !== expected.size || transmitted.some(entry =>
      entry.mode !== expected.get(entry.path)?.mode || entry.content !== expected.get(entry.path)?.content)) throw new Error();
    return evidence;
  } catch {
    throw new Error(failure);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    if (process.argv[2] !== 'canonicalize') throw new Error();
    await canonicalizeReviewCheckout(process.env.GITHUB_WORKSPACE, join(process.env.GITHUB_WORKSPACE, 'review-target'));
  } catch {
    process.stderr.write(`${failure}\n`);
    process.exitCode = 1;
  }
}
