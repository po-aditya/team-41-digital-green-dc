/**
 * LiveApiSource: the only source that calls the real mel_agent endpoints.
 * Read-helpers with no endpoint fall through to the fixtures loader so the UI
 * is identical on live and offline (those panels are labelled "simulated in UI").
 * The operator token is passed in per call and kept in memory only.
 */
import type {
  FollowUp,
  GenerateResult,
  Insight,
  Language,
  PolicyName,
  ResponseRecord,
} from './types';
import type { DataSource, SourceKind } from './DataSource';
import { FixturesBackedSource } from './fixturesBacked';

class OfflineHelpers extends FixturesBackedSource {
  readonly kind: SourceKind = 'live';
}

export interface LiveApiOptions {
  baseUrl: string;
  getToken?: () => string | null;
  fixturesBase?: string;
}

export class LiveApiSource implements DataSource {
  readonly kind: SourceKind = 'live';
  private base: string;
  private getToken: () => string | null;
  private helpers: OfflineHelpers;

  constructor(opts: LiveApiOptions) {
    this.base = opts.baseUrl.replace(/\/$/, '');
    this.getToken = opts.getToken ?? (() => null);
    this.helpers = new OfflineHelpers(opts.fixturesBase ?? '/fixtures');
  }

  private headers(): HeadersInit {
    const h: Record<string, string> = { 'content-type': 'application/json' };
    const token = this.getToken();
    if (token) h['authorization'] = `Bearer ${token}`;
    return h;
  }

  async health(signal?: AbortSignal): Promise<{ ok: boolean }> {
    const res = await fetch(`${this.base}/health`, { signal, headers: this.headers() });
    if (!res.ok) throw new Error(`health ${res.status}`);
    return (await res.json()) as { ok: boolean };
  }

  async generateSurvey(
    insight: Insight,
    language: Language,
    policy: PolicyName,
    signal?: AbortSignal,
  ): Promise<GenerateResult> {
    const url = `${this.base}/v1/surveys?language=${encodeURIComponent(language)}&policy=${policy}`;
    const res = await fetch(url, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(insight),
      signal,
    });
    if (!res.ok && res.status !== 200) throw new Error(`generate ${res.status}`);
    return (await res.json()) as GenerateResult;
  }

  async getSurvey(surveyId: string, signal?: AbortSignal): Promise<GenerateResult> {
    const res = await fetch(`${this.base}/v1/surveys/${encodeURIComponent(surveyId)}`, {
      signal,
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`getSurvey ${res.status}`);
    return (await res.json()) as GenerateResult;
  }

  async postResponse(
    flowId: string,
    record: ResponseRecord,
    signal?: AbortSignal,
  ): Promise<{ outcome: string; status: number }> {
    const res = await fetch(`${this.base}/v1/surveys/${encodeURIComponent(flowId)}/responses`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(record),
      signal,
    });
    const body = (await res.json().catch(() => ({}))) as { outcome?: string };
    return { outcome: body.outcome ?? 'unknown', status: res.status };
  }

  async getFollowUps(signal?: AbortSignal): Promise<FollowUp[]> {
    const res = await fetch(`${this.base}/v1/follow-ups`, { signal, headers: this.headers() });
    if (!res.ok) throw new Error(`followUps ${res.status}`);
    return (await res.json()) as FollowUp[];
  }

  // read-helpers with no endpoint -> fixtures loader
  listScenarios: DataSource['listScenarios'] = (s) => this.helpers.listScenarios(s);
  getScenario: DataSource['getScenario'] = (sc, s) => this.helpers.getScenario(sc, s);
  getRenders: DataSource['getRenders'] = (sc, l, s) => this.helpers.getRenders(sc, l, s);
  getResponses: DataSource['getResponses'] = (sc, s) => this.helpers.getResponses(sc, s);
  listTimeline: DataSource['listTimeline'] = (f, p, s) => this.helpers.listTimeline(f, p, s);
  getIngestStats: DataSource['getIngestStats'] = (s) => this.helpers.getIngestStats(s);
  getReports: DataSource['getReports'] = (s) => this.helpers.getReports(s);
  getOutcomes: DataSource['getOutcomes'] = (s) => this.helpers.getOutcomes(s);
  getHumanQueue: DataSource['getHumanQueue'] = (s) => this.helpers.getHumanQueue(s);
}
