/**
 * Pure helpers that turn a set of farmer answers into a `ResponseRecord`, and
 * decide whether a negative answer creates a Follow_Up_Case. Kept free of React
 * so it is unit- and property-testable.
 *
 * Honesty rule: a voice answer and a tap answer to the same survey must produce
 * identical records EXCEPT for the per-item `input_kind` (speech vs sheet_tap /
 * button_reply). Nothing else about the answer may change by channel.
 */
import type {
  Channel,
  FollowUp,
  InputKind,
  Language,
  ResponseItem,
  ResponseRecord,
  Survey,
} from '../data/types';

export interface BuildArgs {
  survey: Survey;
  channel: Channel;
  language: Language;
  /** item_id -> chosen option value (or scale value as string). */
  answers: Record<string, string>;
  inputKind: InputKind;
  /** stable timestamp so voice/tap records compare equal in tests. */
  now?: string;
}

/** The option values that carry a `follow_up` reason, per survey. */
export function negativeValues(survey: Survey): Map<string, string> {
  const m = new Map<string, string>(); // `${item_id}:${value}` -> reason
  for (const item of survey.items) {
    for (const opt of item.options ?? []) {
      if (opt.follow_up) m.set(`${item.item_id}:${opt.value}`, opt.follow_up);
    }
  }
  return m;
}

/** Reasons triggered by the given answers (deduped, in item order). */
export function followUpReasons(survey: Survey, answers: Record<string, string>): string[] {
  const neg = negativeValues(survey);
  const reasons: string[] = [];
  for (const item of survey.items) {
    const v = answers[item.item_id];
    if (v == null) continue;
    const reason = neg.get(`${item.item_id}:${v}`);
    if (reason && !reasons.includes(reason)) reasons.push(reason);
  }
  return reasons;
}

export function buildResponse(args: BuildArgs): ResponseRecord {
  const { survey, channel, language, answers, inputKind } = args;
  const now = args.now ?? '2026-11-15T09:41:00+05:30';

  const items: ResponseItem[] = survey.items.map((item) => {
    const value = answers[item.item_id] ?? null;
    return {
      item_id: item.item_id,
      item_type: item.type,
      result: value == null ? 'skipped' : 'answered',
      value,
      raw_input: value,
      input_kind: value == null ? null : inputKind,
      attempts: 1,
    };
  });

  const reasons = followUpReasons(survey, answers);
  const complete = items.every((i) => i.result === 'answered');

  return {
    response_key: `${survey.survey_id}:${channel}`,
    survey_id: survey.survey_id,
    farmer_id: survey.farmer_id,
    source_insight_ids: survey.source_insight_ids,
    channel,
    language,
    status: complete ? 'completed' : 'partial',
    failure_code: null,
    sheet_outcome: channel === 'app' || channel === 'web' ? 'finished' : null,
    answers,
    items,
    complete,
    delivery_attempt: 1,
    timestamps: { sent: now, delivered: now, opened: now, answered: now },
    recorded_at: now,
    answered_by: 'farmer',
    raw_event: null,
    retry_decision: 'none',
    retry_after_minutes: null,
    counts_toward_cap: true,
    farmerchat_reply: null,
    needs_follow_up: reasons.length > 0,
    follow_up_reasons: reasons,
  };
}

/** Build the Follow_Up_Case for a record that needs one, or null. */
export function toFollowUp(record: ResponseRecord): FollowUp | null {
  if (!record.needs_follow_up) return null;
  return {
    survey_id: record.survey_id,
    farmer_id: record.farmer_id,
    source_insight_ids: record.source_insight_ids,
    reasons: record.follow_up_reasons,
  };
}

/** The per-channel input kind for a tap-style answer. */
export function tapInputKind(channel: Channel): InputKind {
  switch (channel) {
    case 'app':
    case 'web':
      return 'sheet_tap';
    case 'whatsapp':
      return 'button_reply';
    case 'telegram':
      return 'callback_data';
    case 'voice':
      return 'speech';
    default:
      return 'free_text';
  }
}
