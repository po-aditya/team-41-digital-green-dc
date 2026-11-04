import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { PackSource } from '../src/data/PackSource';
import { FixtureSource } from '../src/data/FixtureSource';
import { LiveApiSource } from '../src/data/LiveApiSource';
import { MAX_PAGE_LIMIT } from '../src/data/DataSource';
import type { ScenarioMeta } from '../src/data/DataSource';

const SCENARIOS: ScenarioMeta[] = [
  { scenario: '1-x', survey_id: 'S-1', farmer_id: 'F-1', languages: ['en-IN', 'hi-IN'], decision: 'survey' },
  { scenario: '6-no', survey_id: null, farmer_id: 'F-6', languages: [], decision: 'no_survey' },
];

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as Response;
}

/** Route fixture URLs to canned JSON so the fixtures loader works under jsdom. */
function installFetchRouter(routes: Record<string, unknown>) {
  const fn = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const u = typeof url === 'string' ? url : url.toString();
    if (init?.signal?.aborted) throw new DOMException('aborted', 'AbortError');
    const match = Object.keys(routes)
      .filter((k) => u.endsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    if (match) return jsonResponse(routes[match]);
    return jsonResponse({ error: "not found" }, false, 404);
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

beforeEach(() => {
  vi.restoreAllMocks();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PackSource / FixtureSource (fixtures-backed)', () => {
  it('reports its kind', () => {
    expect(new PackSource().kind).toBe('pack');
    expect(new FixtureSource().kind).toBe('fixture');
  });

  it('listScenarios reads scenarios-index.json', async () => {
    installFetchRouter({ 'scenarios-index.json': SCENARIOS });
    const src = new PackSource();
    const got = await src.listScenarios();
    expect(got).toHaveLength(2);
    expect(got[0]?.scenario).toBe('1-x');
  });

  it('health is always ok offline', async () => {
    expect(await new FixtureSource().health()).toEqual({ ok: true });
  });

  it('listTimeline caps the page limit at 200', async () => {
    installFetchRouter({
      'scenarios-index.json': SCENARIOS,
      '/1-x/insight.json': {
        insight_id: 'I-1', farmer_id: 'F-1', created_at: '2026-12-01T09:00:00+05:30',
        asset: { name: 'mustard', category: 'crop', growth_stage: null },
        concern: 'pest_disease', severity: 'medium', preferred_channel: 'app',
      },
      '/1-x/survey.en-IN.json': { survey_id: 'S-1', language: 'en-IN' },
      '/1-x/survey.hi-IN.json': { survey_id: 'S-1', language: 'hi-IN' },
      '/1-x/schedule_handoff.json': {
        survey: { survey_id: 'S-1', farmer_id: 'F-1', language: 'en-IN' },
        send_window: { not_before: '2026-12-02T07:00:00+05:30', not_after: '2026-12-05T19:00:00+05:30' },
        expires_at: '2026-12-06T19:00:00+05:30',
        channel_order: [{ channel: 'app', wait_hours: 24 }],
      },
      '/6-no/insight.json': {
        insight_id: 'I-6', farmer_id: 'F-6', created_at: '2026-12-01T09:00:00+05:30',
        asset: { name: 'wheat', category: 'crop', growth_stage: null },
        concern: 'soil_health', severity: 'low', preferred_channel: 'app',
      },
      '/6-no/no_survey.json': { insight_id: 'I-6', farmer_id: 'F-6', decision: 'no_survey', reason_code: 'generic_information', reason: 'x' },
      '/seed/seed.json': {},
    });
    const src = new FixtureSource();
    const page = await src.listTimeline({}, { offset: 0, limit: 9999 });
    expect(page.limit).toBe(MAX_PAGE_LIMIT);
    expect(page.rows.length).toBeLessThanOrEqual(MAX_PAGE_LIMIT);
    expect(page.total).toBeGreaterThan(0);
  });

  it('getReports tolerates missing report files', async () => {
    installFetchRouter({ 'v0-baseline-rules.json': { name: 'v0', scores: {}, speed: {}, status_counts: {}, cases: [] } });
    const reports = await new PackSource().getReports();
    expect(reports.length).toBeGreaterThanOrEqual(1);
  });
});

describe('LiveApiSource', () => {
  it('calls the five endpoints and sends a Bearer token in memory', async () => {
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      if (init?.signal?.aborted) throw new DOMException('aborted', 'AbortError');
      const u = url.toString();
      if (u.endsWith('/health')) return jsonResponse({ ok: true });
      if (u.includes('/v1/surveys?')) return jsonResponse({ status: 'scheduled', survey: { survey_id: 'S-9' }, decision: {}, no_survey: null });
      if (u.match(/\/v1\/surveys\/[^/]+$/)) return jsonResponse({ status: 'scheduled', survey: { survey_id: 'S-9' } });
      if (u.endsWith('/responses')) return jsonResponse({ outcome: 'accepted' }, true, 201);
      if (u.endsWith('/v1/follow-ups')) return jsonResponse([{ survey_id: 'S-9', farmer_id: 'F-9', source_insight_ids: [], reasons: ['advice_did_not_work'] }]);
      return jsonResponse({}, false, 404);
    });
    vi.stubGlobal('fetch', fetchMock);

    let token: string | null = 'secret-token-123456';
    const src = new LiveApiSource({ baseUrl: 'http://api.test', getToken: () => token });

    expect(await src.health()).toEqual({ ok: true });
    const authHeader = (fetchMock.mock.calls[0]?.[1] as RequestInit).headers as Record<string, string>;
    expect(authHeader['authorization']).toBe('Bearer secret-token-123456');

    // token can be cleared and is re-read each call (never cached)
    token = null;
    const gen = await src.generateSurvey(
      { insight_id: 'I', farmer_id: 'F' } as never,
      'hi-IN',
      'calibrated',
    );
    expect(gen.status).toBe('scheduled');
    const genHeader = (fetchMock.mock.calls[1]?.[1] as RequestInit).headers as Record<string, string>;
    expect(genHeader['authorization']).toBeUndefined();

    const resp = await src.postResponse('flow-1', { survey_id: 'S-9' } as never);
    expect(resp.status).toBe(201);
    expect(resp.outcome).toBe('accepted');

    const fus = await src.getFollowUps();
    expect(fus[0]?.reasons).toContain('advice_did_not_work');

    vi.unstubAllGlobals();
  });

  it('propagates AbortError on cancellation', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_u: string, init?: RequestInit) => {
      if (init?.signal?.aborted) throw new DOMException('aborted', 'AbortError');
      return jsonResponse({ ok: true });
    }));
    const src = new LiveApiSource({ baseUrl: 'http://api.test' });
    const ac = new AbortController();
    ac.abort();
    await expect(src.health(ac.signal)).rejects.toThrow();
    vi.unstubAllGlobals();
  });

  it('throws on non-ok health so the caller can fall back', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, false, 503)));
    const src = new LiveApiSource({ baseUrl: 'http://api.test' });
    await expect(src.health()).rejects.toThrow();
    vi.unstubAllGlobals();
  });
});
