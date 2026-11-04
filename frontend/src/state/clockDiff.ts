/**
 * Pure simulated-clock diff engine (Properties 1-3). There is no backend clock;
 * advancing time classifies each survey as delivered / deferred-by-cap / expired
 * from its schedule_handoff window, the per-farmer frequency cap, and the season
 * end. blockedUnsafe is always 0.
 */

export const SEASON_END = '2027-03-31T23:59:59+05:30';

export interface ClockSurvey {
  survey_id: string;
  farmer_id: string;
  not_before: string; // ISO
  not_after: string; // ISO
  expires_at: string; // ISO
  priority: 'low' | 'normal' | 'high';
}

export interface ClockModel {
  surveys: ClockSurvey[];
  seasonEnd: string;
  cap: { max_surveys: number; window_days: number; exempt_priority: string[] };
}

export interface Diff {
  delivered: string[];
  deferredByCap: string[];
  expired: string[];
  blockedUnsafe: 0;
  at: string;
}

function t(iso: string): number {
  return Date.parse(iso);
}

/**
 * Classify every survey whose window has opened by `until`. A survey is:
 *  - expired  if `until` is past its expires_at OR its not_after is after season end
 *  - deferred if a non-exempt earlier survey to the same farmer was delivered
 *             within cap.window_days
 *  - delivered otherwise
 * Surveys whose not_before is still in the future are untouched.
 */
export function advance(model: ClockModel, until: string): Diff {
  const untilMs = t(until);
  const seasonMs = t(model.seasonEnd);
  const windowMs = model.cap.window_days * 24 * 60 * 60 * 1000;

  // deterministic order: by not_before then survey_id
  const due = model.surveys
    .filter((s) => t(s.not_before) <= untilMs)
    .sort((a, b) => t(a.not_before) - t(b.not_before) || a.survey_id.localeCompare(b.survey_id));

  const delivered: string[] = [];
  const deferredByCap: string[] = [];
  const expired: string[] = [];
  const deliveredByFarmer = new Map<string, number[]>(); // farmer -> delivered times

  for (const s of due) {
    const exempt = model.cap.exempt_priority.includes(s.priority);
    if (untilMs > t(s.expires_at) || t(s.not_after) > seasonMs) {
      expired.push(s.survey_id);
      continue;
    }
    const openAt = t(s.not_before);
    const prior = deliveredByFarmer.get(s.farmer_id) ?? [];
    const cappedBy = prior.some((d) => Math.abs(openAt - d) < windowMs);
    if (cappedBy && !exempt) {
      deferredByCap.push(s.survey_id);
      continue;
    }
    delivered.push(s.survey_id);
    prior.push(openAt);
    deliveredByFarmer.set(s.farmer_id, prior);
  }

  return { delivered, deferredByCap, expired, blockedUnsafe: 0, at: until };
}

/** Next not_before at or after `now`, for the "jump to next due" control. */
export function nextDue(model: ClockModel, now: string): string | null {
  const nowMs = t(now);
  const future = model.surveys
    .map((s) => s.not_before)
    .filter((nb) => t(nb) >= nowMs)
    .sort((a, b) => t(a) - t(b));
  return future[0] ?? null;
}
