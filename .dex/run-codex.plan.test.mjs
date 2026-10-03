import assert from 'node:assert/strict';
import { test } from 'node:test';
import { validateManagedPlan } from './run-codex.mjs';
import { completePlan } from './run-codex.fixture.mjs';

const fields = { title: 300, summary: 8000, problem: 8000, readinessReason: 2000 };
const lists = ['goals', 'nonGoals', 'acceptanceCriteria', 'implementationPlan', 'verificationPlan', 'dependencies', 'risks', 'questions'];
const fail = /Managed Codex execution failed\./;

test('valid ready and blocked plans return independent normalized copies', () => {
  for (const input of [completePlan, { ...completePlan, ready: false, implementationPlan: [], questions: ['Which target?'] }]) {
    const before = structuredClone(input);
    const result = validateManagedPlan(input);
    assert.deepEqual(result, before);
    assert.notEqual(result, input);
    for (const key of lists) assert.notEqual(result[key], input[key]);
    assert.deepEqual(input, before);
  }
});
for (const [key, maximum] of Object.entries(fields)) {
  test(`${key} uses normalized Unicode code-point limits`, () => {
    for (const character of ['x', '😀']) {
      const input = Object.freeze({ ...completePlan, [key]: ` \t${character.repeat(maximum)}\n ` });
      assert.equal(validateManagedPlan(input)[key], character.repeat(maximum));
      assert.throws(() => validateManagedPlan({ ...completePlan, [key]: character.repeat(maximum + 1) }), fail);
    }
    for (const value of ['', ' \t ', null, 4, 'bad\0text', 'bad\ud800text', 'bad\udffftext']) {
      assert.throws(() => validateManagedPlan({ ...completePlan, [key]: value }), fail);
    }
  });
}
for (const key of lists) {
  test(`${key} validates every list and entry boundary`, () => {
    const base = { ...completePlan, ...(key === 'questions' ? { ready: false } : {}) };
    for (const value of [['x'.repeat(2000)], ['😀'.repeat(2000)], Array(100).fill('x')]) {
      assert.deepEqual(validateManagedPlan({ ...base, [key]: value })[key], value);
    }
    assert.deepEqual(validateManagedPlan({ ...base, [key]: ['  text 😀  '] })[key], ['text 😀']);
    for (const value of [null, {}, 'text', [null], [''], [' \t '], ['x'.repeat(2001)], ['😀'.repeat(2001)],
      ['bad\0text'], ['bad\ud800text'], ['bad\udffftext'], Array(101).fill('x'), Array(1)]) {
      assert.throws(() => validateManagedPlan({ ...base, [key]: value }), fail);
    }
  });
}
for (const key of Object.keys(completePlan)) {
  test(`requires the ${key} key even if an unknown key replaces it`, () => {
    const input = { ...completePlan };
    delete input[key];
    assert.throws(() => validateManagedPlan(input), fail);
    assert.throws(() => validateManagedPlan({ ...input, unknown: true }), fail);
  });
}
test('rejects invalid envelopes and preserves inputs on failure', () => {
  for (const input of [null, [], {}, true, 'plan', { ...completePlan, unknown: true },
    { ...completePlan, schemaVersion: 2 }, { ...completePlan, ready: 'true' }]) {
    const before = structuredClone(input);
    assert.throws(() => validateManagedPlan(input), fail);
    assert.deepEqual(input, before);
  }
});
for (const ready of [true, false]) for (const steps of [[], ['Implement']]) for (const questions of [[], ['Clarify?']]) {
  test(`readiness ready=${ready}, steps=${steps.length}, questions=${questions.length}`, () => {
    const input = { ...completePlan, ready, implementationPlan: steps, questions };
    if (ready ? steps.length > 0 && questions.length === 0 : questions.length > 0) {
      assert.deepEqual(validateManagedPlan(input), input);
    } else assert.throws(() => validateManagedPlan(input), fail);
  });
}
for (const key of ['goals', 'acceptanceCriteria', 'verificationPlan']) {
  test(`blocked plans still require ${key}`, () => {
    assert.throws(() => validateManagedPlan({ ...completePlan, ready: false,
      implementationPlan: [], questions: ['Clarify?'], [key]: [] }), fail);
  });
}
