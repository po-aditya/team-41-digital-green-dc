/**
 * The single data abstraction the UI depends on. Three implementations:
 * LiveApiSource (5 real endpoints), PackSource and FixtureSource (public/fixtures).
 *
 * Only the first five methods map to real mel_agent endpoints. Every read-helper
 * below has NO backend endpoint in this repo and is served from pack/fixtures;
 * UI panels built on them are labelled "simulated in UI, no backend endpoint".
 */
import type {
  FollowUp,
  GenerateResult,
  Insight,
  Language,
  PolicyName,
  Report,
  ResponseRecord,
  Survey,
  ScheduleHandoff,
  Channel,
  RenderArtifact,
  NoSurvey,
} from './types';

export type SourceKind = 'live' | 'pack' | 'fixture';

export interface ScenarioMeta {
  scenario: string;
  survey_id: string | null;
  farmer_id: string;
  languages: Language[];
  decision: 'survey' | 'no_survey';
}

export interface IngestStats {
  total: number;
  valid: number;
  quarantined: number;
  source: string;
}

export interface TimelineRow {
  survey_id: string;
  scenario: string;
  farmer_id: string;
  language: Language;
  channel: Channel;
  crop: string | null;
  topic: string;
  severity: string;
  state: TimelineState;
  not_before: string;
  not_after: string;
  expires_at: string;
}

export type TimelineState =
  | 'scheduled'
  | 'due'
  | 'deferred_by_cap'
  | 'delivered'
  | 'answered'
  | 'expired'
  | 'window_truncated_by_season_end'
  | 'crop_already_harvested'
  | 'no_survey';

export interface TimelineFilter {
  crop?: string;
  topic?: string;
  language?: Language;
  channel?: Channel;
  severity?: string;
  state?: TimelineState;
}

export interface Page {
  offset: number;
  limit: number; // capped at 200
}
export interface Paged<T> {
  rows: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface HumanQueueItem {
  seed_state: string;
  note: string;
  insight: Insight;
  status: 'new' | 'in_review' | 'resolved';
}

export interface ScenarioDetail {
  meta: ScenarioMeta;
  insight: Insight;
  surveys: Partial<Record<Language, Survey>>;
  handoff: ScheduleHandoff | null;
  noSurvey: NoSurvey | null;
  generate: GenerateResult | null;
}

export const MAX_PAGE_LIMIT = 200;

export interface DataSource {
  readonly kind: SourceKind;

  // ---- served by the five verified endpoints (live) / recorded run (pack,fixture)
  health(signal?: AbortSignal): Promise<{ ok: boolean }>;
  generateSurvey(
    insight: Insight,
    language: Language,
    policy: PolicyName,
    signal?: AbortSignal,
  ): Promise<GenerateResult>;
  getSurvey(surveyId: string, signal?: AbortSignal): Promise<GenerateResult>;
  postResponse(
    flowId: string,
    record: ResponseRecord,
    signal?: AbortSignal,
  ): Promise<{ outcome: string; status: number }>;
  getFollowUps(signal?: AbortSignal): Promise<FollowUp[]>;

  // ---- read helpers: pack/fixtures only (no backend endpoint; labelled simulated)
  listScenarios(signal?: AbortSignal): Promise<ScenarioMeta[]>;
  getScenario(scenario: string, signal?: AbortSignal): Promise<ScenarioDetail>;
  getRenders(
    scenario: string,
    lang: Language,
    signal?: AbortSignal,
  ): Promise<Partial<Record<Channel, RenderArtifact>>>;
  getResponses(
    scenario: string,
    signal?: AbortSignal,
  ): Promise<Partial<Record<Channel, ResponseRecord>>>;
  listTimeline(filter: TimelineFilter, page: Page, signal?: AbortSignal): Promise<Paged<TimelineRow>>;
  getIngestStats(signal?: AbortSignal): Promise<IngestStats>;
  getReports(signal?: AbortSignal): Promise<Report[]>;
  getOutcomes(signal?: AbortSignal): Promise<ResponseRecord[]>;
  getHumanQueue(signal?: AbortSignal): Promise<HumanQueueItem[]>;
}
