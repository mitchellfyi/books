import assert from 'node:assert/strict';
import { chmod, link, mkdir, readFile, readdir, rename, rm, stat, symlink, utimes, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { runManagedModel } from './run-codex.mjs';
import { completePlan, completeReview, modelFixture, reviewFixture } from './run-codex.fixture.mjs';
import { canonicalizeReviewCheckout, prepareReviewEvidence } from './review-evidence.mjs';

const failure = /Managed Codex execution failed\./;
async function clean(fixture) {
  assert.deepEqual(await readdir(fixture.environment.RUNNER_TEMP), ['output']);
}

for (const kind of ['plan', 'review']) {
  test(`${kind} publishes once with the fixed OAuth model and restricted invocation`, async t => {
    const fixture = await modelFixture(t);
    const review = kind === 'review' ? await reviewFixture(fixture) : null;
    await runManagedModel(kind, fixture.environment, fixture.execute);
    assert.equal(fixture.calls.length, 1);
    const invocation = fixture.calls[0];
    assert.deepEqual(invocation.env, { HOME: fixture.environment.HOME, RUNNER_TEMP: fixture.environment.RUNNER_TEMP,
      PATH: fixture.environment.PATH, LANG: 'C.UTF-8', CODEX_MODEL: 'gpt-6-astra', CODEX_REASONING_EFFORT: 'max' });
    assert.equal(JSON.stringify(invocation).includes('sentinel'), false);
    for (const arg of ['--ignore-user-config', '--ignore-rules', '--ephemeral',
      'permissions.managed.network.enabled=false', 'shell_environment_policy.inherit="none"']) {
      assert.ok(invocation.args.includes(arg));
    }
    assert.ok(invocation.args.some((arg, index) => arg === '--enable' && invocation.args[index + 1] === 'code_mode_host'));
    for (const feature of ['code_mode', 'multi_agent', 'plugins', 'apps', 'browser_use', 'image_generation']) {
      assert.ok(invocation.args.some((arg, index) => arg === '--disable' && invocation.args[index + 1] === feature));
    }
    assert.equal(invocation.args.includes('--search'), kind === 'review');
    assert.equal(invocation.timeoutMs, 150 * 60_000);
    const permissions = invocation.args.find(arg => arg.startsWith('permissions.managed.filesystem='));
    const target = fixture.environment.GITHUB_WORKSPACE + (kind === 'review' ? '/review-target' : '');
    assert.ok(permissions.includes(`${JSON.stringify(target)}="${kind === 'review' ? 'write' : 'read'}"`));
    assert.ok(permissions.includes('":root"="deny"'));
    assert.equal(permissions.includes(`${JSON.stringify(fixture.environment.HOME)}=`), false);
    assert.equal(await fixture.output(), `existing=value\nresult=${JSON.stringify(review ? completeReview(review.git('rev-parse', 'HEAD')) : completePlan)}\n`);
    await clean(fixture);
  });
  for (const name of ['OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY', 'DEXCODE_OPENAI_API_KEY']) {
    test(`${kind} refuses ${name} before execution`, async t => {
      const fixture = await modelFixture(t);
      if (kind === 'review') await reviewFixture(fixture);
      await assert.rejects(runManagedModel(kind, { ...fixture.environment, [name]: 'refusal-fixture' }, fixture.execute), failure);
      assert.equal(fixture.calls.length, 0);
      assert.equal(await fixture.output(), 'existing=value\n');
      await clean(fixture);
    });
  }
  test(`${kind} does not retry or publish an executor failure`, async t => {
    const fixture = await modelFixture(t);
    if (kind === 'review') await reviewFixture(fixture);
    let calls = 0;
    await assert.rejects(runManagedModel(kind, fixture.environment, async () => {
      calls++; throw new Error('private-provider-diagnostic');
    }), error => error.message === 'Managed Codex execution failed.');
    assert.equal(calls, 1);
    assert.equal(await fixture.output(), 'existing=value\n');
    await clean(fixture);
  });
}

test('review evidence binds the complete safe diff and transmitted head bytes to the exact specification', async t => {
  const fixture = await modelFixture(t);
  const review = await reviewFixture(fixture);
  const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  assert.equal(evidence.baseSha, review.base);
  assert.equal(evidence.headSha, review.git('rev-parse', 'HEAD'));
  assert.equal(evidence.headTree, review.git('rev-parse', 'HEAD^{tree}'));
  assert.deepEqual(evidence.changedPaths, ['source.txt']);
  assert.deepEqual(evidence.excludedChanges, []);
  assert.match(evidence.diff, /-before\n\+after\n/);
  assert.equal(evidence.files[0].sha256, createHash('sha256').update('after\n').digest('hex'));
  assert.equal(evidence.specSha256, createHash('sha256').update(await readFile(join(review.target, '.dex-review-context/run-spec.json'))).digest('hex'));
  const protocol = await import(new URL('./ops-agent/agent-relay-protocol.mjs', import.meta.url).href).catch(() =>
    import(new URL('../.ops-agent/agent-relay-protocol.mjs', import.meta.url).href));
  const entries = await protocol.snapshot(review.target);
  assert.ok(entries.some(entry => entry.path === '.dex-review-context/review-evidence.json'));
  assert.equal(entries.some(entry => entry.path.startsWith('.git/')), false);
  const prepared = join(fixture.root, 'prepared');
  await protocol.materialize(entries, prepared);
  assert.deepEqual(JSON.parse(await readFile(join(prepared, '.dex-review-context/review-evidence.json'))), evidence);
});

async function convertedReviewFixture(t, conversion) {
  const fixture = await modelFixture(t);
  const review = await reviewFixture(fixture);
  const attributes = { attributes: '*.bat text eol=crlf\n',
    encoding: '*.bat text working-tree-encoding=UTF-16LE eol=crlf\n', ident: '*.bat ident\n' }[conversion];
  if (attributes) await writeFile(join(review.target, '.gitattributes'), attributes);
  if (conversion === 'autocrlf') review.git('config', 'core.autocrlf', 'true');
  const original = conversion === 'crlf-blob' ? '@echo off\r\necho unchanged\r\n'
    : conversion === 'ident' ? 'rem $Id$\necho unchanged\n' : '@echo off\necho unchanged\n';
  await writeFile(join(review.target, 'unchanged.bat'), conversion === 'encoding' ? Buffer.from(original, 'utf16le') : original);
  review.git('add', 'unchanged.bat', ...(attributes ? ['.gitattributes'] : []));
  review.git('commit', '-qm', 'converted base');
  const base = review.git('rev-parse', 'HEAD');
  await writeFile(join(review.target, 'source.txt'), 'reviewed change\n');
  review.git('add', 'source.txt'); review.git('commit', '-qm', 'reviewed head');
  await rm(join(review.target, 'unchanged.bat'));
  review.git('checkout', '--', 'unchanged.bat');
  await review.updateSpec(base);
  const context = join(review.target, '.dex-review-context');
  await rm(context, { recursive: true });
  const placeContext = async () => {
    await mkdir(context);
    for (const [name, path] of [['run-spec.json', 'review-run-spec.json'], ['prompt.md', 'prompts/dexcode_review.md'],
      ['review-result.schema.json', 'review-result.schema.json']]) {
      await writeFile(join(context, name), await readFile(join(fixture.environment.GITHUB_WORKSPACE, '.dex', path)));
    }
  };
  const updateSpec = async (...args) => {
    await mkdir(context);
    await review.updateSpec(...args);
    await rm(context, { recursive: true });
  };
  return { fixture, review, placeContext, updateSpec };
}

for (const conversion of ['attributes', 'autocrlf', 'lf', 'crlf-blob']) {
  test(`fresh review checkout canonicalizes clean ${conversion} conversion before exact blob verification`, async t => {
    const { fixture, review, placeContext } = await convertedReviewFixture(t, conversion);
    assert.equal(review.git('diff', '--exit-code', 'HEAD'), '');
    assert.equal((await readFile(join(review.target, 'unchanged.bat'), 'utf8')).includes('\r\n'), conversion !== 'lf');
    await canonicalizeReviewCheckout(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
    await placeContext();
    const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
    assert.deepEqual(evidence.changedPaths, ['source.txt']);
    const expected = conversion === 'crlf-blob' ? '@echo off\r\necho unchanged\r\n' : '@echo off\necho unchanged\n';
    assert.equal(await readFile(join(review.target, 'unchanged.bat'), 'utf8'), expected);
    assert.equal(evidence.files.find(file => file.path === 'unchanged.bat').sha256,
      createHash('sha256').update(expected).digest('hex'));
  });
}

async function cacheConvertedStat(review, path = 'unchanged.bat') {
  const absolute = join(review.target, path);
  const old = new Date('2025-01-01T00:00:00Z');
  await utimes(absolute, old, old);
  review.git('update-index', '--refresh');
  assert.equal(review.git('diff', '--exit-code', 'HEAD', '--', path), '');
  const file = await stat(absolute), index = await stat(join(review.target, '.git/index'));
  assert.equal(file.mtimeMs, old.getTime());
  assert.ok(index.mtimeMs > file.mtimeMs);
  const cached = review.git('ls-files', '--debug', '--', path);
  assert.match(cached, new RegExp(`mtime: ${old.getTime() / 1000}:0`));
  assert.match(cached, new RegExp(`size: ${file.size}\\s`));
}

for (const conversion of ['attributes', 'autocrlf', 'encoding', 'ident', 'lf', 'crlf-blob']) {
  test(`fresh canonicalization rebuilds stat-clean ${conversion} entries regardless of checkout timestamps`, async t => {
    const { fixture, review, placeContext } = await convertedReviewFixture(t, conversion);
    await cacheConvertedStat(review);
    const path = join(review.target, 'unchanged.bat');
    const before = await readFile(path);
    const expected = conversion === 'crlf-blob' ? '@echo off\r\necho unchanged\r\n'
      : conversion === 'ident' ? 'rem $Id$\necho unchanged\n' : '@echo off\necho unchanged\n';
    assert.equal(before.equals(Buffer.from(expected)), ['lf', 'crlf-blob'].includes(conversion));
    await canonicalizeReviewCheckout(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
    assert.equal(await readFile(path, 'utf8'), expected);
    await placeContext();
    const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
    assert.deepEqual(evidence.changedPaths, ['source.txt']);
    assert.equal(evidence.files.find(file => file.path === 'unchanged.bat').sha256,
      createHash('sha256').update(expected).digest('hex'));
  });
}

test('the fresh checkout CLI stays silent on success and withholds failure diagnostics', async t => {
  for (const valid of [true, false]) {
    const { fixture, review, placeContext, updateSpec } = await convertedReviewFixture(t, 'attributes');
    if (!valid) await updateSpec(review.base, review.base);
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('./review-evidence.mjs', import.meta.url)), 'canonicalize'], {
      env: fixture.environment, encoding: 'utf8', timeout: 15_000, maxBuffer: 200_000,
    });
    assert.equal(result.status, valid ? 0 : 1);
    assert.equal(result.stdout, '');
    assert.equal(result.stderr, valid ? '' : 'Managed review evidence could not be verified.\n');
    if (valid) {
      await placeContext();
      assert.deepEqual((await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment)).changedPaths, ['source.txt']);
    }
  }
});

test('fresh canonicalization disables nested conversion attributes and every repository filter', async t => {
  const { fixture, review, placeContext, updateSpec } = await convertedReviewFixture(t, 'attributes');
  const hostile = join(fixture.root, 'hostile-filter');
  const marker = `${hostile}.invoked`;
  await writeFile(hostile, '#!/bin/sh\necho invoked > "$0.invoked"\ncat\n', { mode: 0o755 });
  await mkdir(join(review.target, 'nested'));
  await writeFile(join(review.target, 'nested/.gitattributes'), '*.bat text eol=crlf ident filter=hostile\n*.ps1 text working-tree-encoding=UTF-16LE eol=crlf\n');
  await writeFile(join(review.target, 'nested/command.bat'), 'rem $Id$\necho safe\n');
  await writeFile(join(review.target, 'nested/command.ps1'), Buffer.from('Write-Output safe\n', 'utf16le'));
  await writeFile(join(review.target, '.env.production'), 'excluded-checkout-credential-canary\n');
  await writeFile(join(review.target, 'IMAGE.PNG'), 'excluded-checkout-binary-canary\n');
  const outside = join(fixture.root, 'outside-file');
  await writeFile(outside, 'outside-checkout-canary');
  await symlink(outside, join(review.target, 'outside-link'));
  review.git('add', '-f', 'nested', '.env.production', 'IMAGE.PNG', 'outside-link');
  review.git('commit', '-qm', 'conversion and exclusion controls');
  await updateSpec();
  review.git('config', 'filter.hostile.smudge', hostile);
  review.git('config', 'filter.hostile.clean', hostile);
  review.git('config', 'filter.hostile.required', 'true');
  await rm(join(review.target, 'nested/command.bat'));
  review.git('checkout', '--', 'nested/command.bat');
  assert.equal(await readFile(marker, 'utf8'), 'invoked\n');
  assert.match(await readFile(join(review.target, 'nested/command.bat'), 'utf8'), /\$Id: [a-f0-9]+ \$/);
  await cacheConvertedStat(review, 'nested/command.bat');
  await cacheConvertedStat(review, 'nested/command.ps1');
  await rm(marker);
  // A process filter supersedes clean/smudge when enabled. It must also stay off.
  review.git('config', 'filter.hostile.process', hostile);
  await canonicalizeReviewCheckout(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  await placeContext();
  const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  assert.equal(await readFile(join(review.target, 'nested/command.bat'), 'utf8'), 'rem $Id$\necho safe\n');
  assert.equal(await readFile(join(review.target, 'nested/command.ps1'), 'utf8'), 'Write-Output safe\n');
  assert.equal(await readFile(outside, 'utf8'), 'outside-checkout-canary');
  assert.equal((await readdir(fixture.root)).includes('hostile-filter.invoked'), false);
  assert.equal(JSON.stringify(evidence).includes('excluded-checkout-credential-canary'), false);
  assert.equal(JSON.stringify(evidence).includes('excluded-checkout-binary-canary'), false);
  assert.equal(JSON.stringify(evidence).includes('outside-checkout-canary'), false);
  assert.match(evidence.diff, /Write-Output safe/);
});

test('fresh canonicalization derives the index from the verified head instead of staged content', async t => {
  const { fixture, review, placeContext } = await convertedReviewFixture(t, 'attributes');
  const head = review.git('rev-parse', 'HEAD');
  await writeFile(join(review.target, 'source.txt'), 'staged-index-canary\n');
  review.git('add', 'source.txt');
  assert.notEqual(review.git('rev-parse', ':source.txt'), review.git('rev-parse', 'HEAD:source.txt'));
  await canonicalizeReviewCheckout(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  assert.equal(review.git('rev-parse', 'HEAD'), head);
  assert.equal(review.git('rev-parse', ':source.txt'), review.git('rev-parse', 'HEAD:source.txt'));
  await placeContext();
  const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  assert.match(evidence.diff, /reviewed change/);
  assert.equal(JSON.stringify(evidence).includes('staged-index-canary'), false);
});

test('fresh canonicalization cannot follow a configured worktree outside the review target', async t => {
  const { fixture, review, placeContext } = await convertedReviewFixture(t, 'attributes');
  const outside = join(fixture.root, 'other-worktree');
  await mkdir(outside);
  for (const path of ['.gitattributes', 'source.txt', 'unchanged.bat']) await writeFile(join(outside, path), 'outside-worktree-canary');
  review.git('config', 'core.worktree', outside);
  await canonicalizeReviewCheckout(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  for (const path of ['.gitattributes', 'source.txt', 'unchanged.bat']) {
    assert.equal(await readFile(join(outside, path), 'utf8'), 'outside-worktree-canary');
  }
  assert.equal(await readFile(join(review.target, 'unchanged.bat'), 'utf8'), '@echo off\necho unchanged\n');
  review.git('config', '--unset', 'core.worktree');
  await placeContext();
  assert.deepEqual((await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment)).changedPaths, ['source.txt']);
});

for (const mutation of ['head', 'untracked', 'ignored', 'context', 'tracked-context', 'attributes', 'attributes-link',
  'info-link', 'git-link', 'target-link', 'source-link', 'source-hardlink', 'parent-link']) {
  test(`fresh canonicalization refuses ${mutation} before replacing checkout files`, async t => {
    const { fixture, review, updateSpec } = await convertedReviewFixture(t, 'attributes');
    const outside = join(fixture.root, 'outside');
    await mkdir(outside);
    const canary = join(outside, 'canary');
    await writeFile(canary, 'untouched-canary');
    if (mutation === 'head') await updateSpec(review.base, review.base);
    if (mutation === 'untracked') await writeFile(join(review.target, 'untracked.txt'), 'untracked');
    if (mutation === 'ignored') {
      await writeFile(join(review.target, '.git/info/exclude'), 'ignored.txt\n');
      await writeFile(join(review.target, 'ignored.txt'), 'ignored');
    }
    if (['context', 'tracked-context'].includes(mutation)) {
      await mkdir(join(review.target, '.dex-review-context'));
      await writeFile(join(review.target, '.dex-review-context/run-spec.json'), 'untrusted');
      if (mutation === 'tracked-context') {
        review.git('add', '.dex-review-context'); review.git('commit', '-qm', 'reserved context');
        await review.updateSpec();
      }
    }
    if (mutation === 'attributes') await writeFile(join(review.target, '.git/info/attributes'), '* filter=untrusted\n');
    if (mutation === 'attributes-link') await symlink(canary, join(review.target, '.git/info/attributes'));
    for (const [kind, path] of [['info-link', '.git/info'], ['git-link', '.git'], ['target-link', '']]) {
      if (mutation !== kind) continue;
      const original = join(review.target, path);
      const moved = join(outside, 'moved');
      await rename(original, moved);
      await symlink(moved, original);
    }
    if (['source-link', 'source-hardlink'].includes(mutation)) {
      await rm(join(review.target, 'source.txt'));
      if (mutation === 'source-link') await symlink(canary, join(review.target, 'source.txt'));
      else await link(canary, join(review.target, 'source.txt'));
    }
    if (mutation === 'parent-link') {
      await mkdir(join(review.target, 'nested'));
      await writeFile(join(review.target, 'nested/canary'), 'tracked source');
      review.git('add', 'nested'); review.git('commit', '-qm', 'nested source');
      await updateSpec();
      await rm(join(review.target, 'nested'), { recursive: true });
      await symlink(outside, join(review.target, 'nested'));
    }
    await assert.rejects(canonicalizeReviewCheckout(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment),
      error => error.message === 'Managed review evidence could not be verified.');
    assert.equal(await readFile(canary, 'utf8'), 'untouched-canary');
    assert.match(await readFile(join(review.target, 'unchanged.bat'), 'utf8'), /\r\n/);
    assert.equal(fixture.calls.length, 0);
  });
}

for (const drift of ['source-bytes', 'source-mode', 'extra-source', 'spec-copy', 'extra-context']) {
  test(`canonicalized review still refuses ${drift} drift before model execution`, async t => {
    const { fixture, review, placeContext } = await convertedReviewFixture(t, 'attributes');
    await cacheConvertedStat(review);
    await canonicalizeReviewCheckout(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
    await placeContext();
    if (drift === 'source-bytes') await writeFile(join(review.target, 'source.txt'), 'changed after materialization');
    if (drift === 'source-mode') await chmod(join(review.target, 'source.txt'), 0o755);
    if (drift === 'extra-source') await writeFile(join(review.target, 'extra.txt'), 'extra source');
    if (drift === 'spec-copy') await writeFile(join(review.target, '.dex-review-context/run-spec.json'), '{}');
    if (drift === 'extra-context') await writeFile(join(review.target, '.dex-review-context/extra.txt'), 'extra context');
    await assert.rejects(runManagedModel('review', fixture.environment, fixture.execute), failure);
    assert.equal(fixture.calls.length, 0);
    assert.equal(await fixture.output(), 'existing=value\n');
    await clean(fixture);
  });
}

test('review evidence includes additions deletions and mode changes without running repository diff helpers', async t => {
  const fixture = await modelFixture(t);
  const review = await reviewFixture(fixture);
  await writeFile(join(review.target, '.gitattributes'), '*.txt diff=hostile\n');
  await writeFile(join(review.target, 'helper'), 'deleted source\n');
  const hostile = join(fixture.root, 'hostile-helper');
  await writeFile(hostile, '#!/bin/sh\necho invoked > "$0.invoked"\ncat "$1"\n', { mode: 0o755 });
  review.git('config', 'diff.hostile.command', hostile);
  review.git('config', 'diff.hostile.textconv', hostile);
  review.git('add', '.gitattributes', 'helper'); review.git('commit', '-qm', 'attributes');
  const base = review.git('rev-parse', 'HEAD');
  await rm(join(review.target, 'helper'));
  await writeFile(join(review.target, 'new.txt'), 'new content\n');
  await writeFile(join(review.target, 'source.txt'), 'changed content\n');
  await chmod(join(review.target, 'source.txt'), 0o755);
  review.git('add', '-A', '--', 'helper', 'new.txt', 'source.txt'); review.git('commit', '-qm', 'changes');
  review.git('diff', base, 'HEAD', '--', 'source.txt');
  assert.equal(await readFile(`${hostile}.invoked`, 'utf8'), 'invoked\n');
  await rm(`${hostile}.invoked`);
  await review.updateSpec(base);
  const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  assert.deepEqual(evidence.changedPaths, ['helper', 'new.txt', 'source.txt']);
  assert.match(evidence.diff, /deleted file mode/);
  assert.match(evidence.diff, /new file mode/);
  assert.match(evidence.diff, /old mode 100644\nnew mode 100755/);
  assert.match(evidence.diff, /\+changed content/);
  assert.equal((await readdir(fixture.root)).includes('hostile-helper.invoked'), false);
});

test('excluded base secrets and binary bytes cannot escape inside the review diff', async t => {
  const fixture = await modelFixture(t);
  const review = await reviewFixture(fixture);
  const secrets = ['.env.production', '.npmrc', '.yarnrc.yml', '.ops-agent/private.js'];
  for (const path of secrets) {
    await mkdir(join(review.target, path, '..'), { recursive: true });
    await writeFile(join(review.target, path), 'private-history-canary');
  }
  await writeFile(join(review.target, 'image.png'), 'private-binary-canary');
  await writeFile(join(review.target, 'binary.txt'), Buffer.from('private-binary-canary\0'));
  await symlink('/unreadable-private-file', join(review.target, 'outside'));
  review.git('add', '-f', ...secrets, 'image.png', 'binary.txt', 'outside'); review.git('commit', '-qm', 'excluded base');
  const base = review.git('rev-parse', 'HEAD');
  for (const path of [...secrets, 'image.png', 'binary.txt', 'outside']) await rm(join(review.target, path));
  await writeFile(join(review.target, 'source.txt'), 'safe positive control\n');
  review.git('add', '-A', '--', ...secrets, 'image.png', 'binary.txt', 'outside', 'source.txt'); review.git('commit', '-qm', 'remove excluded files');
  await review.updateSpec(base);
  const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  assert.match(evidence.diff, /safe positive control/);
  assert.equal(JSON.stringify(evidence).includes('private-history-canary'), false);
  assert.equal(JSON.stringify(evidence).includes('private-binary-canary'), false);
  assert.deepEqual(evidence.excludedChanges.map(entry => entry.path), [...secrets, 'image.png', 'binary.txt', 'outside'].sort());
});

async function reviewPathTransition(t, direction, children) {
  const fixture = await modelFixture(t);
  const review = await reviewFixture(fixture);
  const configuration = async directory => {
    if (!directory) return writeFile(join(review.target, 'config'), 'safe configuration source\n');
    for (const [path, content] of children) {
      await mkdir(join(review.target, 'config', path, '..'), { recursive: true });
      await writeFile(join(review.target, 'config', path), content);
    }
  };
  await configuration(direction === 'directory-to-file');
  review.git('--literal-pathspecs', 'add', '-f', '--', 'config'); review.git('commit', '-qm', 'transition base');
  const base = review.git('rev-parse', 'HEAD');
  await rm(join(review.target, 'config'), { recursive: true });
  await configuration(direction === 'file-to-directory');
  await writeFile(join(review.target, 'source.txt'), 'safe transition control\n');
  review.git('--literal-pathspecs', 'add', '-A', '--', 'config', 'source.txt'); review.git('commit', '-qm', 'transition head');
  await review.updateSpec(base);
  return { fixture, review, base };
}

async function reviewGitProbe(fixture, patchMutation) {
  const directory = join(fixture.root, 'git-probe');
  const log = join(directory, 'calls.jsonl');
  await mkdir(directory);
  await writeFile(join(directory, 'git'), `#!${process.execPath}
    const { spawnSync } = require('node:child_process');
    const { appendFileSync, readFileSync } = require('node:fs');
    const args = process.argv.slice(2);
    appendFileSync(${JSON.stringify(log)}, JSON.stringify(args) + '\\n');
    const patch = args.includes('diff') && !args.includes('--name-only');
    const mutation = ${JSON.stringify(patchMutation ?? null)};
    if (patch && mutation === 'additional-path') args.splice(args.lastIndexOf('--') + 1);
    const result = spawnSync('git', args, { input: readFileSync(0),
      env: { ...process.env, PATH: ${JSON.stringify(process.env.PATH)} } });
    const output = patch && mutation === 'duplicate-patch' ? Buffer.concat([result.stdout, result.stdout])
      : patch && mutation === 'old-path' ? result.stdout.toString().replaceAll('a/source.txt', 'a/.env.production')
      : result.stdout;
    process.stdout.write(output);
    process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  `, { mode: 0o755 });
  fixture.environment.PATH = `${directory}:${fixture.environment.PATH}`;
  return async () => (await readFile(log, 'utf8')).trim().split('\n').map(row => JSON.parse(row));
}

for (const direction of ['file-to-directory', 'directory-to-file']) {
  for (const path of ['.env.production', 'credentials.json', 'image.png', 'binary.txt']) {
    test(`review refuses recursive ${direction} pathspec selection of excluded ${path}`, async t => {
      const canary = 'excluded-transition-canary';
      const content = `${canary}${path === 'binary.txt' ? '\0' : ''}\n`;
      const { fixture, review, base } = await reviewPathTransition(t, direction, [[path, content]]);
      // A literal pathspec still selects descendants when either revision has a directory here.
      const unguarded = review.git('--literal-pathspecs', 'diff', '--no-ext-diff', '--no-textconv',
        '--no-renames', '--text', base, 'HEAD', '--', 'config', 'source.txt');
      assert.equal(unguarded.includes(canary), true);
      const calls = path === '.env.production' ? await reviewGitProbe(fixture) : null;
      await assert.rejects(runManagedModel('review', fixture.environment, fixture.execute), failure);
      if (calls) {
        const diffs = (await calls()).filter(args => args.includes('diff'));
        assert.equal(diffs.length, 1);
        assert.equal(diffs[0].includes('--name-only'), true);
        assert.equal(diffs[0].includes('-z'), true);
      }
      assert.equal(fixture.calls.length, 0);
      assert.equal(await fixture.output(), 'existing=value\n');
      await assert.rejects(readFile(join(review.target, '.dex-review-context/review-evidence.json')), { code: 'ENOENT' });
      await clean(fixture);
    });
  }

  test(`review preserves complete ${direction} diffs when every selected nested file is safe`, async t => {
    const { fixture, review } = await reviewPathTransition(t, direction,
      [['readme.txt', 'safe child\n'], ['nested/source.txt', 'safe nested child\n']]);
    const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
    assert.deepEqual(evidence.changedPaths, ['config', 'config/nested/source.txt', 'config/readme.txt', 'source.txt']);
    assert.deepEqual(evidence.excludedChanges, []);
    for (const content of ['safe configuration source', 'safe child', 'safe nested child', 'safe transition control']) {
      assert.equal(evidence.diff.includes(content), true);
    }
  });
}

for (const mutation of ['additional-path', 'duplicate-patch', 'old-path']) {
  test(`review refuses ${mutation} in final patch headers before evidence or model execution`, async t => {
    const fixture = await modelFixture(t);
    const review = await reviewFixture(fixture);
    await writeFile(join(review.target, '.env.production'), 'excluded-final-patch-canary\n');
    review.git('add', '-f', '--', '.env.production'); review.git('commit', '-qm', 'excluded head');
    await review.updateSpec();
    const unguarded = review.git('diff', review.base, 'HEAD');
    assert.equal(unguarded.includes('excluded-final-patch-canary'), true);
    const calls = await reviewGitProbe(fixture, mutation);
    await assert.rejects(runManagedModel('review', fixture.environment, fixture.execute), failure);
    const invocations = await calls();
    assert.equal(invocations.filter(args => args.includes('diff') && args.includes('--name-only')).length, 1);
    assert.equal(invocations.filter(args => args.includes('diff') && !args.includes('--name-only')).length, 1);
    assert.equal(invocations.filter(args => args.includes('apply') && args.includes('--numstat')).length,
      mutation === 'old-path' ? 2 : 1);
    assert.equal(fixture.calls.length, 0);
    assert.equal(await fixture.output(), 'existing=value\n');
    await assert.rejects(readFile(join(review.target, '.dex-review-context/review-evidence.json')), { code: 'ENOENT' });
    await clean(fixture);
  });
}

test('review treats glob and pathspec metacharacters as literal filenames', async t => {
  const fixture = await modelFixture(t);
  const review = await reviewFixture(fixture);
  const paths = ['star*.txt', 'question?.txt', '[brackets].txt', ':(glob)*.txt', 'nested/space name.txt', 'quote"name.txt', 'café.txt'];
  for (const path of paths) {
    await mkdir(join(review.target, path, '..'), { recursive: true });
    await writeFile(join(review.target, path), `old ${path}\n`);
  }
  review.git('--literal-pathspecs', 'add', '--', ...paths); review.git('commit', '-qm', 'literal base');
  const base = review.git('rev-parse', 'HEAD');
  for (const path of paths) await writeFile(join(review.target, path), `new ${path}\n`);
  review.git('--literal-pathspecs', 'add', '--', ...paths); review.git('commit', '-qm', 'literal head');
  await review.updateSpec(base);
  const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
  assert.deepEqual(evidence.changedPaths, paths.sort());
  assert.deepEqual(evidence.excludedChanges, []);
  for (const path of paths) assert.equal(evidence.diff.includes(`+new ${path}\n`), true);
});

for (const state of ['unchanged', 'deleted']) {
  test(`review evidence preserves relay exclusions for ${state} uppercase binary paths`, async t => {
    const fixture = await modelFixture(t);
    const review = await reviewFixture(fixture);
    const paths = ['IMAGE.PNG', 'AREAFLAGS.MAP'];
    for (const path of paths) await writeFile(join(review.target, path), 'uppercase-binary-canary\n');
    review.git('add', ...paths); review.git('commit', '-qm', 'uppercase binary base');
    const base = review.git('rev-parse', 'HEAD');
    if (state === 'deleted') for (const path of paths) await rm(join(review.target, path));
    await writeFile(join(review.target, 'source.txt'), 'safe uppercase-exclusion control\n');
    review.git('add', '-u'); review.git('commit', '-qm', 'safe source change');
    await review.updateSpec(base);
    const evidence = await prepareReviewEvidence(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
    assert.deepEqual(evidence.changedPaths, ['source.txt']);
    assert.match(evidence.diff, /safe uppercase-exclusion control/);
    assert.equal(JSON.stringify(evidence).includes('uppercase-binary-canary'), false);
    assert.equal(evidence.files.some(entry => paths.includes(entry.path)), false);
    assert.deepEqual(evidence.excludedChanges, state === 'deleted'
      ? paths.sort().map(path => ({ path, reason: 'binary-path' })) : []);
  });
}

for (const mutation of ['head', 'base', 'repository', 'spec-copy', 'source-bytes', 'source-mode', 'untracked', 'ignored-context', 'existing-evidence', 'extra-context']) {
  test(`review refuses ${mutation} drift before the model or callback`, async t => {
    const fixture = await modelFixture(t);
    const review = await reviewFixture(fixture);
    if (mutation === 'head') await review.updateSpec(review.base, review.base);
    if (mutation === 'base') await review.updateSpec('f'.repeat(40));
    if (mutation === 'repository') fixture.environment.GITHUB_REPOSITORY = 'other/repository';
    if (mutation === 'spec-copy') await writeFile(join(review.target, '.dex-review-context/run-spec.json'), '{}');
    if (mutation === 'source-bytes') await writeFile(join(review.target, 'source.txt'), 'uncommitted');
    if (mutation === 'source-mode') await chmod(join(review.target, 'source.txt'), 0o755);
    if (mutation === 'untracked') await writeFile(join(review.target, 'extra.txt'), 'untracked');
    if (mutation === 'ignored-context') {
      await writeFile(join(review.target, '.git/info/exclude'), '.dex-review-context/\n');
    }
    if (mutation === 'existing-evidence') await writeFile(join(review.target, '.dex-review-context/review-evidence.json'), 'forged');
    if (mutation === 'extra-context') await writeFile(join(review.target, '.dex-review-context/untrusted.txt'), 'untracked context');
    await assert.rejects(runManagedModel('review', fixture.environment, fixture.execute), failure);
    assert.equal(fixture.calls.length, 0);
    assert.equal(await fixture.output(), 'existing=value\n');
    await clean(fixture);
  });
}

for (const drift of ['source-bytes', 'source-mode', 'new-file', 'deleted-file']) {
  test(`review refuses ${drift} drift in the final transmitted snapshot before execution`, async t => {
    const { fixture, review, placeContext } = await convertedReviewFixture(t, 'attributes');
    await cacheConvertedStat(review);
    await canonicalizeReviewCheckout(fixture.environment.GITHUB_WORKSPACE, review.target, fixture.environment);
    await placeContext();
    const protocol = join(fixture.environment.GITHUB_WORKSPACE, '.ops-agent/agent-relay-protocol.mjs');
    await writeFile(join(protocol, '../snapshot-base.mjs'), await readFile(protocol));
    await writeFile(protocol, `
      import { snapshot as originalSnapshot, safePath } from './snapshot-base.mjs';
      import { chmod, rm, writeFile } from 'node:fs/promises';
      import { join } from 'node:path';
      export { safePath };
      let calls = 0;
      export async function snapshot(target) {
        if (++calls === 2) {
          const drift = ${JSON.stringify(drift)};
          if (drift === 'source-bytes') await writeFile(join(target, 'source.txt'), 'changed after verification');
          if (drift === 'source-mode') await chmod(join(target, 'source.txt'), 0o755);
          if (drift === 'new-file') await writeFile(join(target, 'new.txt'), 'added after verification');
          if (drift === 'deleted-file') await rm(join(target, 'source.txt'));
        }
        return originalSnapshot(target);
      }
    `);
    await assert.rejects(runManagedModel('review', fixture.environment, fixture.execute), failure);
    assert.equal(fixture.calls.length, 0);
    assert.equal(await fixture.output(), 'existing=value\n');
    await clean(fixture);
  });
}

test('review refuses an oversized safe diff instead of silently truncating the review', async t => {
  const fixture = await modelFixture(t);
  const review = await reviewFixture(fixture);
  await writeFile(join(review.target, 'source.txt'), `${'x'.repeat(4_000_000)}\n`);
  review.git('add', 'source.txt'); review.git('commit', '-qm', 'oversized diff');
  await review.updateSpec();
  await assert.rejects(runManagedModel('review', fixture.environment, fixture.execute), failure);
  assert.equal(fixture.calls.length, 0);
  assert.equal(await fixture.output(), 'existing=value\n');
  await clean(fixture);
});
for (const title of [' '+ 'x'.repeat(300), '😀'.repeat(300)]) {
  test('publishes normalized valid boundary text, not the raw input', async t => {
    const value = { ...completePlan, title, goals: ['  Record the evidence.  '] };
    const fixture = await modelFixture(t, value);
    await runManagedModel('plan', fixture.environment, fixture.execute);
    assert.equal(await fixture.output(), `existing=value\nresult=${JSON.stringify({ ...value, title: title.trim(), goals: completePlan.goals })}\n`);
    await clean(fixture);
  });
}
for (const value of [{ ...completePlan, implementationPlan: [] }, { ...completePlan, title: '😀'.repeat(301) },
  { ...completePlan, goals: [] }, 'null', '[]', 'not JSON', Buffer.from([0xc3, 0x28]),
  { ...completePlan, title: 'bad\0title' }, { ...completePlan, title: 'bad\ud800title' },
  { ...completePlan, title: 'ghp_' + 'a'.repeat(40) }]) {
  test('rejected results cannot append or retain temporary files', async t => {
    const fixture = await modelFixture(t, value);
    await assert.rejects(runManagedModel('plan', fixture.environment, fixture.execute), failure);
    assert.equal(fixture.calls.length, 1);
    assert.equal(await fixture.output(), 'existing=value\n');
    await clean(fixture);
  });
}
for (const character of ['x', 'é', '😀']) for (const size of [39999, 40000, 40001]) {
  test(`enforces the exact ${size}-byte ${character} JSON transport boundary`, async t => {
    const value = { ...completePlan, goals: Array(20 / Buffer.byteLength(character)).fill(character.repeat(1900)) };
    value.goals.push('x'.repeat(size - Buffer.byteLength(JSON.stringify(value)) - 3));
    assert.equal(Buffer.byteLength(JSON.stringify(value)), size);
    const fixture = await modelFixture(t, value);
    if (size <= 40000) {
      await runManagedModel('plan', fixture.environment, fixture.execute);
      assert.equal(await fixture.output(), `existing=value\nresult=${JSON.stringify(value)}\n`);
    } else {
      await assert.rejects(runManagedModel('plan', fixture.environment, fixture.execute), failure);
      assert.equal(await fixture.output(), 'existing=value\n');
    }
    await clean(fixture);
  });
}

for (const size of [39999, 40000, 40001]) {
  test(`counts raw UTF-8 whitespace toward the ${size}-byte result-file limit`, async t => {
    const value = { ...completePlan, summary: '😀'.repeat(2000) };
    const serialized = JSON.stringify(value);
    const raw = serialized + ' '.repeat(size - Buffer.byteLength(serialized));
    assert.equal(Buffer.byteLength(raw), size);
    assert.ok(Buffer.byteLength(serialized) < 40000);
    const fixture = await modelFixture(t, raw);
    if (size <= 40000) {
      await runManagedModel('plan', fixture.environment, fixture.execute);
      assert.equal(await fixture.output(), `existing=value\nresult=${serialized}\n`);
    } else {
      await assert.rejects(runManagedModel('plan', fixture.environment, fixture.execute), failure);
      assert.equal(await fixture.output(), 'existing=value\n');
    }
    assert.equal(fixture.calls.length, 1);
    await clean(fixture);
  });
}
