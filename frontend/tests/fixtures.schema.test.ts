import { describe, it, expect, beforeAll } from 'vitest';
import Ajv2020, { type ValidateFunction } from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const FIX = join(__dirname, '..', 'public', 'fixtures');
const SCHEMA_DIR = join(FIX, 'schemas');

function readJson<T = unknown>(p: string): T {
  return JSON.parse(readFileSync(p, 'utf-8')) as T;
}
function walk(dir: string): string[] {
  const out: string[] = [];
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.name.endsWith('.json')) out.push(full);
  }
  return out;
}

let ajv: Ajv2020;
const validators: Record<string, ValidateFunction> = {};

beforeAll(() => {
  // fixtures must exist; fail loudly if `npm run fixtures` was not run.
  expect(existsSync(SCHEMA_DIR), 'run `npm run fixtures` first').toBe(true);
  ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  // register every schema under BOTH its $id and its bare filename so relative
  // "survey.schema.json#/..." refs resolve.
  for (const file of readdirSync(SCHEMA_DIR)) {
    if (!file.endsWith('.json')) continue;
    const schema = readJson<Record<string, unknown>>(join(SCHEMA_DIR, file));
    ajv.addSchema(schema, file);
  }
  for (const [name, file] of Object.entries({
    survey: 'survey.schema.json',
    response: 'response.schema.json',
    schedule_handoff: 'schedule_handoff.schema.json',
    no_survey: 'no_survey.schema.json',
    insight: 'insight.schema.json',
    bottom_sheet: 'bottom_sheet.schema.json',
  })) {
    const v = ajv.getSchema(file);
    if (!v) throw new Error(`schema ${file} failed to compile`);
    validators[name] = v as ValidateFunction;
  }
});

function validate(name: keyof typeof validators | string, data: unknown, label: string) {
  const v = validators[name as string];
  if (!v) throw new Error(`no validator for ${name}`);
  const ok = v(data);
  if (!ok) {
    throw new Error(`${label} failed ${name} schema: ${JSON.stringify(v.errors?.slice(0, 3))}`);
  }
  expect(ok).toBe(true);
}

describe('fixtures validate against the six pack schemas', () => {
  it('all six schemas compile', () => {
    expect(Object.keys(validators)).toHaveLength(6);
  });

  it('every scenario survey (both languages) is schema-valid', () => {
    const scenDir = join(FIX, 'scenarios');
    let count = 0;
    for (const scen of readdirSync(scenDir)) {
      for (const lang of ['en-IN', 'hi-IN']) {
        const p = join(scenDir, scen, `survey.${lang}.json`);
        if (!existsSync(p)) continue;
        validate('survey', readJson(p), `${scen}/survey.${lang}`);
        count += 1;
      }
    }
    expect(count).toBeGreaterThanOrEqual(10);
  });

  it('every scenario schedule_handoff is schema-valid', () => {
    const scenDir = join(FIX, 'scenarios');
    let count = 0;
    for (const scen of readdirSync(scenDir)) {
      const p = join(scenDir, scen, 'schedule_handoff.json');
      if (!existsSync(p)) continue;
      validate('schedule_handoff', readJson(p), `${scen}/schedule_handoff`);
      count += 1;
    }
    expect(count).toBeGreaterThanOrEqual(5);
  });

  it('every scenario insight is schema-valid', () => {
    const scenDir = join(FIX, 'scenarios');
    for (const scen of readdirSync(scenDir)) {
      const p = join(scenDir, scen, 'insight.json');
      if (existsSync(p)) validate('insight', readJson(p), `${scen}/insight`);
    }
  });

  it('every scenario no_survey is schema-valid', () => {
    const p = join(FIX, 'scenarios', '6-zero-tillage-info-no-survey', 'no_survey.json');
    validate('no_survey', readJson(p), 'scenario6/no_survey');
  });

  it('every scenario per-channel response is schema-valid', () => {
    const scenDir = join(FIX, 'scenarios');
    let count = 0;
    for (const scen of readdirSync(scenDir)) {
      const respDir = join(scenDir, scen, 'responses');
      if (!existsSync(respDir)) continue;
      for (const f of readdirSync(respDir)) {
        validate('response', readJson(join(respDir, f)), `${scen}/responses/${f}`);
        count += 1;
      }
    }
    expect(count).toBeGreaterThan(0);
  });

  it('every outcome record (183) is schema-valid against response', () => {
    const files = walk(join(FIX, 'outcomes'));
    expect(files.length).toBeGreaterThan(100);
    for (const f of files) {
      validate('response', readJson(f), f.replace(FIX, ''));
    }
  });

  it('captured generate results: survey is valid when scheduled, else no_survey decision', () => {
    const genDir = join(FIX, 'generate');
    let scheduled = 0;
    let noSurvey = 0;
    for (const f of readdirSync(genDir)) {
      if (f === 'manifest.json' || !f.endsWith('.json')) continue;
      const r = readJson<{ status: string; survey: unknown; no_survey: unknown }>(join(genDir, f));
      if (r.status === 'scheduled') {
        validate('survey', r.survey, `${f}/survey`);
        scheduled += 1;
      } else if (r.status === 'no_survey') {
        expect(r.no_survey).toBeTruthy();
        noSurvey += 1;
      }
    }
    expect(scheduled).toBeGreaterThanOrEqual(5);
    expect(noSurvey).toBeGreaterThanOrEqual(1);
  });
});
