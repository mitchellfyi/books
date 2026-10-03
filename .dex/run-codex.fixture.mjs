import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export const completePlan = { schemaVersion: 1, title: 'A bounded plan', summary: 'Record verified behavior.',
  problem: 'No verification record.', goals: ['Record the evidence.'], nonGoals: [],
  acceptanceCriteria: ['A real run passes.'], implementationPlan: ['Update the runbook.'],
  verificationPlan: ['Run contracts.'], dependencies: [], risks: [], questions: [],
  ready: true, readinessReason: 'The requirements are known.' };

export function completeReview(reviewedSha) {
  return { schemaVersion: 1, outcome: 'passed', reviewedSha, summary: 'The bounded fixture passes.',
    manualChecks: [{ check: 'Execute the injected review fixture.', outcome: 'passed', evidence: 'One injected execution returned a bound result.' }],
    findings: [], testCoverageGaps: [], optimizations: [], acceptanceCriteria: [], verificationPlan: [],
    researchSources: [
      { title: 'GitHub Actions security', url: 'https://docs.github.com/en/actions/reference/security/secure-use', relevance: 'Defines job permission boundaries.' },
      { title: 'Node test runner', url: 'https://nodejs.org/docs/latest-v24.x/api/test.html', relevance: 'Defines the injected test execution.' },
    ] };
}

// All model executions in this suite are injected local fixtures, never Codex.
export async function modelFixture(t, value) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'dexcode-contract-')));
  t.after(() => rm(root, { recursive: true, force: true }));
  const workspace = join(root, 'workspace');
  const home = join(root, 'home');
  const temporary = join(root, 'temporary');
  for (const path of [join(workspace, '.dex', 'prompts'), join(workspace, 'review-target'), home, temporary]) {
    await mkdir(path, { recursive: true });
  }
  for (const kind of ['plan', 'review']) {
    await writeFile(join(workspace, '.dex/prompts', `dexcode_${kind}.md`), 'A fixture prompt.');
    const name = `${kind === 'plan' ? 'planner' : 'review'}-result.schema.json`;
    await writeFile(join(workspace, '.dex', name), await readFile(new URL('./' + name, import.meta.url)));
  }
  const environment = { GITHUB_WORKSPACE: workspace, HOME: home, RUNNER_TEMP: temporary,
    PATH: process.env.PATH, GITHUB_OUTPUT: join(temporary, 'output'), GH_TOKEN: 'publisher-sentinel',
    ACTIONS_ID_TOKEN_REQUEST_TOKEN: 'reporter-sentinel', CODEX_AUTH_JSON: 'oauth-sentinel',
    CODEX_MODEL: 'unapproved-model', CODEX_REASONING_EFFORT: 'low' };
  await writeFile(environment.GITHUB_OUTPUT, 'existing=value\n');
  const calls = [];
  const execute = async invocation => {
    calls.push(invocation);
    const output = invocation.args[invocation.args.indexOf('--output-last-message') + 1];
    const schema = invocation.args[invocation.args.indexOf('--output-schema') + 1];
    const result = value !== undefined ? value : (schema.endsWith('/review-result.schema.json')
      ? completeReview(JSON.parse(await readFile(join(workspace, '.dex/review-run-spec.json'), 'utf8')).pull_request.head_sha)
      : completePlan);
    await writeFile(output, typeof result === 'string' || Buffer.isBuffer(result) ? result : JSON.stringify(result));
  };
  return { root, environment, execute, calls, output: () => readFile(environment.GITHUB_OUTPUT, 'utf8') };
}

export async function reviewFixture(fixture) {
  const { environment } = fixture;
  const workspace = environment.GITHUB_WORKSPACE;
  const target = join(workspace, 'review-target');
  const git = (...args) => {
    const result = spawnSync('git', ['-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-C', target, ...args], {
      encoding: 'utf8', env: { PATH: process.env.PATH, HOME: '/nonexistent', GIT_CONFIG_NOSYSTEM: '1',
        GIT_CONFIG_GLOBAL: '/dev/null', GIT_AUTHOR_NAME: 'Review fixture', GIT_AUTHOR_EMAIL: 'fixture@example.invalid',
        GIT_COMMITTER_NAME: 'Review fixture', GIT_COMMITTER_EMAIL: 'fixture@example.invalid' },
    });
    if (result.status !== 0) throw new Error('Git fixture failed.');
    return result.stdout.trim();
  };
  git('init', '-q');
  await writeFile(join(target, 'source.txt'), 'before\n');
  git('add', 'source.txt'); git('commit', '-qm', 'base');
  const base = git('rev-parse', 'HEAD');
  await writeFile(join(target, 'source.txt'), 'after\n');
  git('add', 'source.txt'); git('commit', '-qm', 'head');
  let protocol;
  try { protocol = await readFile(new URL('../.ops-agent/agent-relay-protocol.mjs', import.meta.url)); }
  catch { protocol = await readFile(new URL('./ops-agent/agent-relay-protocol.mjs', import.meta.url)); }
  await mkdir(join(workspace, '.ops-agent'));
  await writeFile(join(workspace, '.ops-agent/agent-relay-protocol.mjs'), protocol);
  await mkdir(join(target, '.dex-review-context'));
  environment.GITHUB_REPOSITORY_ID = '123';
  environment.GITHUB_REPOSITORY = 'fixture/repository';
  const updateSpec = async (nextBase = base, nextHead = git('rev-parse', 'HEAD')) => {
    const spec = { schema_version: 1, run_id: 'review-fixture', repository: { full_name: 'fixture/repository' },
      pull_request: { base_sha: nextBase, head_sha: nextHead } };
    const raw = JSON.stringify(spec);
    await writeFile(join(workspace, '.dex/review-run-spec.json'), raw);
    await writeFile(join(target, '.dex-review-context/run-spec.json'), raw);
    return spec;
  };
  await updateSpec();
  await writeFile(join(target, '.dex-review-context/prompt.md'), await readFile(join(workspace, '.dex/prompts/dexcode_review.md')));
  await writeFile(join(target, '.dex-review-context/review-result.schema.json'), await readFile(join(workspace, '.dex/review-result.schema.json')));
  return { target, git, base, updateSpec };
}
