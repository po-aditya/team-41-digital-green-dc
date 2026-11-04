/**
 * TypeScript types derived verbatim from the participant-pack JSON and the
 * mel_agent API shapes. Field names match the pack exactly. Treat all backend
 * data as untrusted even though it is synthetic (render as text nodes only).
 */

export type Language = 'en-IN' | 'hi-IN';
export type Channel = 'app' | 'web' | 'whatsapp' | 'telegram' | 'voice';
export type PolicyName = 'baseline' | 'calibrated';

export type SurveyItemType = 'survey-confirm' | 'survey-single-select' | 'survey-scale';

export type ResolutionType =
  | 'direct_action'
  | 'wait_and_monitor'
  | 'do_not_act'
  | 'plan_created'
  | 'escalate_to_expert'
  | 'generic_information'
  | 'needs_more_context';

export type FollowUpReason =
  | 'advice_did_not_work'
  | 'crop_or_animal_damaged'
  | 'could_not_reach_expert'
  | 'could_not_get_input';

export type InputKind =
  | 'sheet_tap'
  | 'button_reply'
  | 'callback_data'
  | 'keypad'
  | 'speech'
  | 'free_text';

export type RetryDecision =
  | 'none'
  | 'give_up'
  | 'retry_same_channel'
  | 'fall_back_to_next_channel';

export type SheetOutcome =
  | 'finished'
  | 'closed_partway'
  | 'interrupted'
  | 'dismissed'
  | 'never_opened';

export type Severity = 'low' | 'medium' | 'high' | 'critical';

// ---- insight.schema.json ----
export interface Insight {
  insight_id: string;
  farmer_id: string;
  conversation_id: string;
  created_at: string;
  conversation_language: Language;
  location: { country: string; state: string; district: string };
  asset: { name: string | null; category: string | null; growth_stage: string | null };
  concern: string;
  behavioral_intent: string;
  decision_episode_type: string;
  severity: Severity;
  query_summary: string;
  advice_summary: string;
  resolution_type: ResolutionType;
  action_window_days: number | null;
  verification: { needed: boolean; timing: string; method: string };
  preferred_channel: Channel;
}

// ---- survey.schema.json ----
export interface SurveyOption {
  value: string;
  label: string;
  follow_up?: FollowUpReason;
}
export interface SurveyItem {
  item_id: string;
  type: SurveyItemType;
  prompt: string;
  options?: SurveyOption[];
  scale_min?: number;
  scale_max?: number;
}
export interface SendWindow {
  not_before: string;
  not_after: string;
}
export interface SelfEval {
  schema_valid: boolean;
  relevance_score?: number;
  gives_new_advice?: boolean;
  asks_personal_info?: boolean;
}
export interface Survey {
  survey_id: string;
  farmer_id: string;
  source_insight_ids: string[];
  language: Language;
  send_window: SendWindow;
  items: SurveyItem[];
  rationale: string;
  self_eval?: SelfEval;
}

// ---- no_survey.schema.json ----
export interface NoSurvey {
  insight_id: string;
  farmer_id: string;
  decision: 'no_survey';
  reason_code: string;
  reason: string;
}

// ---- schedule_handoff.schema.json ----
export interface ChannelStep {
  channel: Channel;
  wait_hours: number | null;
}
export interface FrequencyCap {
  key: string;
  max_surveys: number;
  window_days: number;
  exempt: boolean;
}
export interface FarmerChatFlow {
  org_id: string;
  flow_key: string;
  version: number;
  campaign_id: string;
  flow_id: string;
}
export interface ScheduleHandoff {
  handoff_id: string;
  created_at: string;
  survey: Survey;
  send_window: SendWindow;
  send_hours: { from: string; to: string };
  channel_order: ChannelStep[];
  frequency_cap: FrequencyCap;
  priority: 'low' | 'normal' | 'high';
  expires_at: string;
  farmerchat_flow: FarmerChatFlow;
}

// ---- response.schema.json ----
export interface ResponseItem {
  item_id: string;
  item_type: SurveyItemType;
  result: 'answered' | 'skipped' | 'invalid' | 'not_reached';
  value: string | null;
  raw_input: string | null;
  input_kind: InputKind | null;
  attempts: number;
}
export interface ResponseRecord {
  response_key: string;
  survey_id: string;
  farmer_id: string;
  source_insight_ids: string[];
  channel: Channel;
  language: Language;
  question_type?: SurveyItemType;
  status: string;
  failure_code: string | null;
  sheet_outcome: SheetOutcome | null;
  answers: Record<string, string>;
  items: ResponseItem[];
  complete: boolean;
  delivery_attempt: number;
  timestamps: {
    sent?: string | null;
    delivered?: string | null;
    opened?: string | null;
    answered?: string | null;
  };
  recorded_at: string;
  answered_by: string | null;
  raw_event: string | null;
  retry_decision: RetryDecision;
  retry_after_minutes: number | null;
  counts_toward_cap: boolean;
  farmerchat_reply: { http_status: number; outcome: string } | null;
  needs_follow_up: boolean;
  follow_up_reasons: string[];
}

// ---- render artifacts ----
export interface BottomSheetStepOption {
  label: string;
  answer: string;
}
export interface BottomSheetStep {
  step: number;
  step_label: string;
  item_id: string;
  question_type: SurveyItemType;
  question: string;
  options: BottomSheetStepOption[];
}
export interface BottomSheetRender {
  channel: 'app' | 'web';
  how_it_arrives: string;
  presentation: {
    type: 'bottom_sheet';
    opens_when: string[];
    waits_for: string[];
    one_question_per_step: boolean;
    steps_total: number;
    can_skip: boolean;
    can_close: boolean;
    swipe_down_closes: boolean;
  };
  sheet: {
    title: string;
    skip_label: string;
    close_label: string;
    thank_you: string;
    steps: BottomSheetStep[];
  };
}
export interface VoiceItem {
  item_id: string;
  say: string;
  keypad: Record<string, string>;
  speech: Record<string, string[]>;
  timeout_seconds: number;
  repeat_if_no_input: number;
}
export interface VoiceRender {
  channel: 'voice';
  how_it_arrives: string;
  opening: string;
  items: VoiceItem[];
  closing: string;
  closing_if_follow_up: string;
}
export interface ChatMessageRender {
  channel: 'whatsapp' | 'telegram';
  how_it_arrives: string;
  opening_template?: unknown;
  template_text_for_approval?: string;
  messages: unknown[];
}
export type RenderArtifact = BottomSheetRender | VoiceRender | ChatMessageRender;

// ---- mel_agent POST /v1/surveys result ----
export interface Decision {
  insight_id: string;
  farmer_id: string;
  survey: boolean;
  rule: string;
  reason_code: string;
  reason: string;
  send_window: SendWindow | null;
  priority: string | null;
  channel_order: ChannelStep[] | null;
}
export interface GenerateResult {
  insight_id: string;
  farmer_id: string;
  decision: Decision;
  survey: Survey | null;
  handoff: ScheduleHandoff | null;
  no_survey: NoSurvey | null;
  check: unknown;
  status: 'scheduled' | 'no_survey' | 'rejected' | 'writer_skipped' | 'error';
  attempts: number;
  seconds?: number;
  usage?: Usage;
}

// ---- GET /v1/follow-ups ----
export interface FollowUp {
  survey_id: string;
  farmer_id: string;
  source_insight_ids: string[];
  reasons: string[];
}

// ---- reports/v0..v4 ----
export interface Usage {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  seconds: number;
  cost_usd: number | null;
  by_model: Record<string, unknown>;
}
export interface ReportSpeed {
  batch_wall_seconds: number;
  seconds_per_survey_avg: number;
  seconds_per_survey_p95: number;
  agent_usage: Usage;
  eval_judge_usage?: Usage;
}
export interface ReportCase {
  golden_id?: string;
  insight_id?: string;
  expected_survey?: boolean;
  agent_survey?: boolean;
  expected_rule?: string;
  agent_rule?: string;
  status?: string;
  [k: string]: unknown;
}
export interface Report {
  name: string;
  policy: string;
  language: Language;
  golden_cases: number;
  writer_model: string;
  checker_model?: string;
  prompt_version?: string;
  min_relevance?: number;
  at: string;
  scores: Record<string, number | boolean>;
  speed: ReportSpeed | null;
  status_counts: {
    scheduled: number;
    rejected: number;
    writer_skipped: number;
    no_survey: number;
    error: number;
  } | null;
  rule_mismatches: unknown[];
  cases: ReportCase[];
}

// ---- outcome_codes.json entries ----
export interface OutcomeCode {
  status?: string;
  channels?: Channel[];
  retry_decision?: RetryDecision;
  retry_after_minutes?: number | null;
  counts_toward_cap?: boolean;
  meaning?: string;
}
