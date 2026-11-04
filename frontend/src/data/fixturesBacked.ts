/**
 * Shared loader for PackSource and FixtureSource: both read the files under
 * public/fixtures (copied from the participant pack + a real offline backend run).
 * Nothing here invents data; the timeline is DERIVED from real schedule_handoff
 * windows and the fixture seed, and labelled "simulated in UI" by the panels.
 */
import type {
  Channel,
  FollowUp,
  GenerateResult,
  Insight,
  Language,
  Report,
  RenderArtifact,
  ResponseRecord,
  ScheduleHandoff,
  Survey,
  NoSurvey,
  PolicyName,
} from './types';
import {
  MAX_PAGE_LIMIT,
  type DataSource,
  type HumanQueueItem,
  type IngestStats,
  type Page,
  type Paged,
  type ScenarioDetail,
  type ScenarioMeta,
  type SourceKind,
  type TimelineFilter,
  type TimelineRow,
  type TimelineState,
} from './DataSource';

const CHANNELS: Channel[] = ['app', 'web', 'whatsapp', 'telegram', 'voice'];
const LANGS: Language[] = ['en-IN', 'hi-IN'];

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`fixture fetch failed: ${url} (${res.status})`);
  return (await res.json()) as T;
}

export abstract class FixturesBackedSource implements DataSource {
  abstract readonly kind: SourceKind;
  protected base: string;

  constructor(base = '/fixtures') {
    this.base = base;
  }

  async health(): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  async listScenarios(signal?: AbortSignal): Promise<ScenarioMeta[]> {
    return fetchJson<ScenarioMeta[]>(`${this.base}/scenarios-index.json`, signal);
  }

  async getScenario(scenario: string, signal?: AbortSignal): Promise<ScenarioDetail> {
    const metas = await this.listScenarios(signal);
    const meta = metas.find((m) => m.scenario === scenario);
    if (!meta) throw new Error(`unknown scenario ${scenario}`);
    const dir = `${this.base}/scenarios/${scenario}`;
    const insight = await fetchJson<Insight>(`${dir}/insight.json`, signal);
    const surveys: Partial<Record<Language, Survey>> = {};
    if (meta.decision === "survey") {
      for (const lang of meta.languages) {
        surveys[lang] = await fetchJson<Survey>(`${dir}/survey.${lang}.json`, signal);
      }
    }
    let handoff: ScheduleHandoff | null = null;
    let noSurvey: NoSurvey | null = null;
    if (meta.decision === 'survey') {
      handoff = await fetchJson<ScheduleHandoff>(`${dir}/schedule_handoff.json`, signal);
    } else {
      noSurvey = await fetchJson<NoSurvey>(`${dir}/no_survey.json`, signal);
    }
    let generate: GenerateResult | null = null;
    try {
      generate = await fetchJson<GenerateResult>(`${this.base}/generate/${scenario}.json`, signal);
    } catch {
      generate = null;
    }
    return { meta, insight, surveys, handoff, noSurvey, generate };
  }

  async generateSurvey(
    insight: Insight,
    _language: Language,
    _policy: PolicyName,
    signal?: AbortSignal,
  ): Promise<GenerateResult> {
    // Offline sources return the captured real pipeline result for this insight.
    const metas = await this.listScenarios(signal);
    const meta = metas.find((m) => m.farmer_id === insight.farmer_id);
    if (meta) {
      return fetchJson<GenerateResult>(`${this.base}/generate/${meta.scenario}.json`, signal);
    }
    throw new Error('offline source: no captured generate result for this insight');
  }

  async getSurvey(surveyId: string, signal?: AbortSignal): Promise<GenerateResult> {
    const metas = await this.listScenarios(signal);
    for (const m of metas) {
      try {
        const g = await fetchJson<GenerateResult>(`${this.base}/generate/${m.scenario}.json`, signal);
        if (g.survey?.survey_id === surveyId) return g;
      } catch {
        /* skip */
      }
    }
    throw new Error(`unknown survey ${surveyId}`);
  }

  async postResponse(): Promise<{ outcome: string; status: number }> {
    // No persistence offline; label handled by the UI ("simulated tap, not persisted").
    return { outcome: 'simulated', status: 200 };
  }

  async getFollowUps(signal?: AbortSignal): Promise<FollowUp[]> {
    // Derive from any scenario response that reported a follow-up.
    const metas = await this.listScenarios(signal);
    const out: FollowUp[] = [];
    for (const m of metas) {
      const responses = await this.getResponses(m.scenario, signal).catch(() => ({}));
      for (const rec of Object.values(responses)) {
        if (rec && rec.needs_follow_up) {
          out.push({
            survey_id: rec.survey_id,
            farmer_id: rec.farmer_id,
            source_insight_ids: rec.source_insight_ids,
            reasons: rec.follow_up_reasons,
          });
        }
      }
    }
    // de-dup by survey_id
    const seen = new Set<string>();
    return out.filter((f) => (seen.has(f.survey_id) ? false : (seen.add(f.survey_id), true)));
  }

  async getRenders(
    scenario: string,
    lang: Language,
    signal?: AbortSignal,
  ): Promise<Partial<Record<Channel, RenderArtifact>>> {
    const out: Partial<Record<Channel, RenderArtifact>> = {};
    for (const ch of CHANNELS) {
      try {
        out[ch] = await fetchJson<RenderArtifact>(
          `${this.base}/scenarios/${scenario}/render/${lang}/${ch}.json`,
          signal,
        );
      } catch {
        /* channel may be absent */
      }
    }
    return out;
  }

  async getResponses(
    scenario: string,
    signal?: AbortSignal,
  ): Promise<Partial<Record<Channel, ResponseRecord>>> {
    const out: Partial<Record<Channel, ResponseRecord>> = {};
    for (const ch of CHANNELS) {
      try {
        out[ch] = await fetchJson<ResponseRecord>(
          `${this.base}/scenarios/${scenario}/responses/${ch}.json`,
          signal,
        );
      } catch {
        /* channel may be absent */
      }
    }
    return out;
  }

  async getIngestStats(signal?: AbortSignal): Promise<IngestStats> {
    return fetchJson<IngestStats>(`${this.base}/ingest-stats.json`, signal);
  }

  async getReports(signal?: AbortSignal): Promise<Report[]> {
    const names = [
      'v0-baseline-rules',
      'v1-calibrated-rules',
      'v2-llm-prompt1-en',
      'v3-llm-prompt2-en',
      'v4-llm-prompt2-hi',
    ];
    const out: Report[] = [];
    for (const n of names) {
      try {
        out.push(await fetchJson<Report>(`${this.base}/reports/${n}.json`, signal));
      } catch {
        /* report may be absent */
      }
    }
    return out;
  }

  async getOutcomes(signal?: AbortSignal): Promise<ResponseRecord[]> {
    // The 183 outcome records live under outcomes/{channel}/{question-type}/*.json.
    // We load a representative set via the manifest the build writes, or fall back
    // to the per-scenario responses if the manifest is absent.
    try {
      const manifest = await fetchJson<string[]>(`${this.base}/outcomes-manifest.json`, signal);
      const out: ResponseRecord[] = [];
      for (const rel of manifest) {
        out.push(await fetchJson<ResponseRecord>(`${this.base}/outcomes/${rel}`, signal));
      }
      return out;
    } catch {
      const metas = await this.listScenarios(signal);
      const out: ResponseRecord[] = [];
      for (const m of metas) {
        const r = await this.getResponses(m.scenario, signal).catch(() => ({}));
        out.push(...(Object.values(r).filter(Boolean) as ResponseRecord[]));
      }
      return out;
    }
  }

  async getHumanQueue(signal?: AbortSignal): Promise<HumanQueueItem[]> {
    const seed = await fetchJson<{ human_queue: HumanQueueItem[] }>(
      `${this.base}/seed/seed.json`,
      signal,
    );
    return seed.human_queue ?? [];
  }

  async listTimeline(
    filter: TimelineFilter,
    page: Page,
    signal?: AbortSignal,
  ): Promise<Paged<TimelineRow>> {
    const rows = await this.buildTimeline(signal);
    const filtered = rows.filter(
      (r) =>
        (!filter.crop || r.crop === filter.crop) &&
        (!filter.topic || r.topic === filter.topic) &&
        (!filter.language || r.language === filter.language) &&
        (!filter.channel || r.channel === filter.channel) &&
        (!filter.severity || r.severity === filter.severity) &&
        (!filter.state || r.state === filter.state),
    );
    const limit = Math.min(page.limit, MAX_PAGE_LIMIT);
    return {
      rows: filtered.slice(page.offset, page.offset + limit),
      total: filtered.length,
      offset: page.offset,
      limit,
    };
  }

  private timelineCache: TimelineRow[] | null = null;

  private async buildTimeline(signal?: AbortSignal): Promise<TimelineRow[]> {
    if (this.timelineCache) return this.timelineCache;
    const metas = await this.listScenarios(signal);
    const rows: TimelineRow[] = [];
    for (const m of metas) {
      const detail = await this.getScenario(m.scenario, signal);
      const insight = detail.insight;
      const firstChannel = detail.handoff?.channel_order?.[0]?.channel ?? insight.preferred_channel;
      if (m.decision === 'no_survey') {
        for (const lang of m.languages) {
          rows.push({
            survey_id: m.survey_id ?? `${m.scenario}-no-survey`,
            scenario: m.scenario,
            farmer_id: m.farmer_id,
            language: lang,
            channel: insight.preferred_channel,
            crop: insight.asset.name,
            topic: insight.concern,
            severity: insight.severity,
            state: 'no_survey',
            not_before: insight.created_at,
            not_after: insight.created_at,
            expires_at: insight.created_at,
          });
        }
        continue;
      }
      const handoff = detail.handoff;
      if (!handoff) continue;
      for (const lang of m.languages) {
        rows.push({
          survey_id: handoff.survey.survey_id,
          scenario: m.scenario,
          farmer_id: m.farmer_id,
          language: lang,
          channel: firstChannel,
          crop: insight.asset.name,
          topic: insight.concern,
          severity: insight.severity,
          state: 'scheduled',
          not_before: handoff.send_window.not_before,
          not_after: handoff.send_window.not_after,
          expires_at: handoff.expires_at,
        });
      }
    }
    // add seed-derived states (deferred/expired/season-truncated)
    try {
      const seed = await fetchJson<Record<string, { handoff?: ScheduleHandoff }>>(
        `${this.base}/seed/seed.json`,
        signal,
      );
      const seedStates: Array<[string, TimelineState]> = [
        ['deferred', 'deferred_by_cap'],
        ['expired', 'expired'],
        ['season_truncated', 'window_truncated_by_season_end'],
      ];
      for (const [key, state] of seedStates) {
        const h = seed[key]?.handoff;
        if (!h) continue;
        rows.push({
          survey_id: `${h.survey.survey_id}-${state}`,
          scenario: `seed-${key}`,
          farmer_id: h.survey.farmer_id,
          language: h.survey.language,
          channel: h.channel_order?.[0]?.channel ?? 'app',
          crop: null,
          topic: 'seed',
          severity: 'low',
          state,
          not_before: h.send_window.not_before,
          not_after: h.send_window.not_after,
          expires_at: h.expires_at,
        });
      }
    } catch {
      /* seed optional */
    }
    this.timelineCache = rows;
    return rows;
  }
}

export const SUPPORTED_LANGS = LANGS;
