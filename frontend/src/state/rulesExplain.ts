/**
 * Decision explainability. The backend decision already carries { rule (e.g. "R3"),
 * reason_code, reason }. This module surfaces that verbatim and adds the plain
 * "asks" question from rules.json for the resolution type. No rule logic is
 * invented here; we only present what the backend and rules.json say.
 */
import type { Decision, ResolutionType } from '../data/types';

export interface RulesDoc {
  survey_by_resolution: Record<string, { survey: boolean; asks?: string }>;
}

export interface Explanation {
  rule: string; // e.g. "R3"
  survey: boolean;
  reasonCode: string;
  reason: string; // verbatim backend reason
  asks: string | null; // plain-language "what the survey checks", from rules.json
}

export function explainDecision(
  decision: Decision,
  rules: RulesDoc | null,
  resolutionType?: ResolutionType,
): Explanation {
  const asks =
    resolutionType && rules?.survey_by_resolution?.[resolutionType]?.asks
      ? rules.survey_by_resolution[resolutionType]!.asks!
      : null;
  return {
    rule: decision.rule,
    survey: decision.survey,
    reasonCode: decision.reason_code,
    reason: decision.reason,
    asks,
  };
}
