import type { Report, ReportCase } from '../data/types';

export interface Confusion {
  tp: number; // expected survey & agent survey
  fp: number; // expected no-survey & agent survey
  tn: number; // expected no-survey & agent no-survey
  fn: number; // expected survey & agent no-survey
  precision: number;
  recall: number;
  f1: number;
  total: number;
}

/** Compute the 2x2 only if every case has both expected_survey and agent_survey.
 *  Otherwise return null and the UI shows "not shown here". */
export function confusionFromCases(cases: ReportCase[]): Confusion | null {
  if (cases.length === 0) return null;
  const ok = cases.every(
    (c) => typeof c.expected_survey === 'boolean' && typeof c.agent_survey === 'boolean',
  );
  if (!ok) return null;
  let tp = 0, fp = 0, tn = 0, fn = 0;
  for (const c of cases) {
    const exp = c.expected_survey as boolean;
    const got = c.agent_survey as boolean;
    if (exp && got) tp += 1;
    else if (!exp && got) fp += 1;
    else if (!exp && !got) tn += 1;
    else fn += 1;
  }
  const precision = tp + fp === 0 ? 1 : tp / (tp + fp);
  const recall = tp + fn === 0 ? 1 : tp / (tp + fn);
  const f1 = precision + recall === 0 ? 0 : (2 * precision * recall) / (precision + recall);
  return { tp, fp, tn, fn, precision, recall, f1, total: cases.length };
}

export interface RuleMismatch {
  insight_id?: string;
  golden_id?: string;
  expected_rule?: string;
  agent_rule?: string;
}

export function ruleMismatches(cases: ReportCase[]): RuleMismatch[] {
  return cases
    .filter((c) => c.expected_rule && c.agent_rule && c.expected_rule !== c.agent_rule)
    .map((c) => ({
      insight_id: c.insight_id,
      golden_id: c.golden_id,
      expected_rule: c.expected_rule,
      agent_rule: c.agent_rule,
    }));
}

/** Pick the latest/best Hindi report if present, else the last report. */
export function primaryReport(reports: Report[]): Report | null {
  return reports.find((r) => r.language === 'hi-IN') ?? reports[reports.length - 1] ?? null;
}
