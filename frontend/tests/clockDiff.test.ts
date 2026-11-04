import { describe, it, expect } from 'vitest';
import { advance, nextDue, type ClockModel } from '../src/state/clockDiff';

const base: ClockModel = {
  seasonEnd: '2027-03-31T23:59:59+05:30',
  cap: { max_surveys: 1, window_days: 7, exempt_priority: ['high'] },
  surveys: [
    { survey_id: 'A', farmer_id: 'F1', not_before: '2026-12-02T07:00:00+05:30', not_after: '2026-12-05T19:00:00+05:30', expires_at: '2026-12-06T19:00:00+05:30', priority: 'normal' },
    { survey_id: 'B', farmer_id: 'F1', not_before: '2026-12-03T07:00:00+05:30', not_after: '2026-12-06T19:00:00+05:30', expires_at: '2026-12-07T19:00:00+05:30', priority: 'normal' },
    { survey_id: 'C', farmer_id: 'F2', not_before: '2026-12-02T07:00:00+05:30', not_after: '2026-12-05T19:00:00+05:30', expires_at: '2026-12-06T19:00:00+05:30', priority: 'normal' },
  ],
};

describe('clock diff engine', () => {
  it('delivers a survey once its window opened and it is not expired', () => {
    const d = advance(base, '2026-12-02T08:00:00+05:30');
    expect(d.delivered).toContain('A');
    expect(d.delivered).toContain('C');
    expect(d.blockedUnsafe).toBe(0);
  });

  it('defers a second survey to the same farmer inside the cap window', () => {
    const d = advance(base, '2026-12-04T08:00:00+05:30');
    expect(d.delivered).toContain('A');
    expect(d.deferredByCap).toContain('B'); // same farmer F1, within 7 days
    expect(d.delivered).toContain('C'); // different farmer
  });

  it('exempts high-priority surveys from the cap', () => {
    const m: ClockModel = {
      ...base,
      surveys: base.surveys.map((s) => (s.survey_id === 'B' ? { ...s, priority: 'high' } : s)),
    };
    const d = advance(m, '2026-12-04T08:00:00+05:30');
    expect(d.delivered).toContain('B');
    expect(d.deferredByCap).not.toContain('B');
  });

  it('expires a survey past its expires_at', () => {
    const d = advance(base, '2026-12-10T08:00:00+05:30');
    expect(d.expired).toEqual(expect.arrayContaining(['A', 'B', 'C']));
  });

  it('expires a survey whose not_after is after the season end', () => {
    const m: ClockModel = {
      seasonEnd: '2027-03-31T23:59:59+05:30',
      cap: base.cap,
      surveys: [
        { survey_id: 'S', farmer_id: 'F9', not_before: '2027-03-30T07:00:00+05:30', not_after: '2027-04-02T19:00:00+05:30', expires_at: '2027-04-03T19:00:00+05:30', priority: 'normal' },
      ],
    };
    const d = advance(m, '2027-03-30T08:00:00+05:30');
    expect(d.expired).toContain('S');
  });

  it('every due survey lands in exactly one bucket (partition)', () => {
    const d = advance(base, '2026-12-10T08:00:00+05:30');
    const all = [...d.delivered, ...d.deferredByCap, ...d.expired];
    expect(new Set(all).size).toBe(all.length); // no duplicates
  });

  it('nextDue returns the earliest not_before at/after now', () => {
    expect(nextDue(base, '2026-12-01T00:00:00+05:30')).toBe('2026-12-02T07:00:00+05:30');
    expect(nextDue(base, '2026-12-02T12:00:00+05:30')).toBe('2026-12-03T07:00:00+05:30');
  });
});
