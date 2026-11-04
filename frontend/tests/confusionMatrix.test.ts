import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { confusionFromCases, ruleMismatches, primaryReport } from '../src/evidence/confusionMatrix';
import type { Report } from '../src/data/types';

function loadReport(name: string): Report {
  return JSON.parse(readFileSync(join(__dirname, '..', 'public', 'fixtures', 'reports', `${name}.json`), 'utf-8'));
}

describe('confusion matrix from real report cases', () => {
  it('computes a 2x2 that sums to the case count for the Hindi run', () => {
    const r = loadReport('v4-llm-prompt2-hi');
    const m = confusionFromCases(r.cases);
    expect(m).not.toBeNull();
    expect(m!.tp + m!.fp + m!.tn + m!.fn).toBe(r.cases.length);
    // scheduled count in status_counts should match TP+FP (agent decided to survey)
    expect(r.status_counts).not.toBeNull();
    expect(m!.tp + m!.fp).toBe(r.status_counts!.scheduled);
    expect(m!.precision).toBeGreaterThan(0);
    expect(m!.recall).toBeGreaterThan(0);
    expect(m!.f1).toBeGreaterThan(0);
  });

  it('returns null when cases lack the decision booleans', () => {
    expect(confusionFromCases([{ golden_id: 'x' }])).toBeNull();
    expect(confusionFromCases([])).toBeNull();
  });

  it('rule mismatches are empty when agent_rule equals expected_rule everywhere', () => {
    const r = loadReport('v4-llm-prompt2-hi');
    const mismatches = ruleMismatches(r.cases);
    // v4 report has rule_mismatches [] per the data; our computed list should agree
    expect(mismatches.length).toBe((r.rule_mismatches as unknown[]).length);
  });

  it('primaryReport prefers the hi-IN run', () => {
    const reps = [loadReport('v2-llm-prompt1-en'), loadReport('v4-llm-prompt2-hi')];
    expect(primaryReport(reps)!.language).toBe('hi-IN');
  });
});
