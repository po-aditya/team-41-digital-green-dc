import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { explainDecision } from '../src/state/rulesExplain';
import type { Decision } from '../src/data/types';

const rules = JSON.parse(
  readFileSync(join(__dirname, '..', 'public', 'fixtures', 'rules', 'rules.json'), 'utf-8'),
);

const noSurveyGen = JSON.parse(
  readFileSync(join(__dirname, '..', 'public', 'fixtures', 'generate', '6-zero-tillage-info-no-survey.json'), 'utf-8'),
);

describe('rulesExplain surfaces backend decision verbatim + plain asks', () => {
  it('passes through the backend rule, reason_code and reason unchanged', () => {
    const d = noSurveyGen.decision as Decision;
    const e = explainDecision(d, rules, 'generic_information');
    expect(e.rule).toBe(d.rule);
    expect(e.reasonCode).toBe(d.reason_code);
    expect(e.reason).toBe(d.reason);
    expect(e.survey).toBe(false);
  });

  it('adds the plain-language "asks" for a surveyed resolution type', () => {
    const d: Decision = {
      insight_id: 'I', farmer_id: 'F', survey: true, rule: 'R8',
      reason_code: 'verify_action', reason: 'x', send_window: null, priority: 'normal', channel_order: null,
    };
    const e = explainDecision(d, rules, 'direct_action');
    expect(e.asks).toBe(rules.survey_by_resolution.direct_action.asks);
  });

  it('asks is null when rules are missing', () => {
    const d: Decision = {
      insight_id: 'I', farmer_id: 'F', survey: true, rule: 'R8',
      reason_code: 'x', reason: 'y', send_window: null, priority: 'normal', channel_order: null,
    };
    expect(explainDecision(d, null).asks).toBeNull();
  });
});
