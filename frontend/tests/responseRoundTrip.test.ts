import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  buildResponse,
  followUpReasons,
  tapInputKind,
  toFollowUp,
} from '../src/phone/responseBuilder';
import type { Survey } from '../src/data/types';

function loadSurvey(): Survey {
  return JSON.parse(
    readFileSync(
      join(__dirname, '..', 'public', 'fixtures', 'scenarios', '1-mustard-aphid-spray', 'survey.en-IN.json'),
      'utf-8',
    ),
  );
}

const survey = loadSurvey();

describe('response round-trip (voice vs tap differ only by input_kind)', () => {
  const answers = { q1: 'yes', q2: 'easy', q3: 'fewer' };

  it('voice and sheet records are identical except per-item input_kind', () => {
    const tap = buildResponse({ survey, channel: 'app', language: 'en-IN', answers, inputKind: 'sheet_tap' });
    const voice = buildResponse({ survey, channel: 'app', language: 'en-IN', answers, inputKind: 'speech' });

    // normalise input_kind to compare everything else
    const strip = (r: typeof tap) => ({ ...r, items: r.items.map((i) => ({ ...i, input_kind: null })) });
    expect(strip(voice)).toEqual(strip(tap));

    // and the only real difference is the per-item kind
    for (const i of tap.items) expect(i.input_kind).toBe('sheet_tap');
    for (const i of voice.items) expect(i.input_kind).toBe('speech');
  });

  it('a positive answer set creates no follow-up case', () => {
    const r = buildResponse({ survey, channel: 'app', language: 'en-IN', answers, inputKind: 'sheet_tap' });
    expect(r.needs_follow_up).toBe(false);
    expect(toFollowUp(r)).toBeNull();
  });

  it('a negative answer creates a follow-up case with the mapped reason', () => {
    const neg = { q1: 'yes', q2: 'easy', q3: 'same' }; // q3 same -> advice_did_not_work
    const r = buildResponse({ survey, channel: 'voice', language: 'en-IN', answers: neg, inputKind: 'speech' });
    expect(r.needs_follow_up).toBe(true);
    expect(r.follow_up_reasons).toContain('advice_did_not_work');
    const fu = toFollowUp(r);
    expect(fu).not.toBeNull();
    expect(fu!.survey_id).toBe(survey.survey_id);
    expect(fu!.reasons).toContain('advice_did_not_work');
  });

  it('follow-up reasons are deduped and follow item order', () => {
    const both = { q1: 'yes', q2: 'not_found', q3: 'more' };
    const reasons = followUpReasons(survey, both);
    expect(reasons).toEqual(['could_not_get_input', 'advice_did_not_work']);
  });

  it('tapInputKind maps each channel to its input kind', () => {
    expect(tapInputKind('app')).toBe('sheet_tap');
    expect(tapInputKind('web')).toBe('sheet_tap');
    expect(tapInputKind('whatsapp')).toBe('button_reply');
    expect(tapInputKind('telegram')).toBe('callback_data');
    expect(tapInputKind('voice')).toBe('speech');
  });

  it('partial answers mark the record partial and skipped items null', () => {
    const r = buildResponse({ survey, channel: 'app', language: 'en-IN', answers: { q1: 'yes' }, inputKind: 'sheet_tap' });
    expect(r.complete).toBe(false);
    expect(r.status).toBe('partial');
    const q2 = r.items.find((i) => i.item_id === 'q2')!;
    expect(q2.result).toBe('skipped');
    expect(q2.value).toBeNull();
    expect(q2.input_kind).toBeNull();
  });
});
