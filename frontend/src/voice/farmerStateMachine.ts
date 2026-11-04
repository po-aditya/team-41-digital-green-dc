/**
 * Pure voice-channel state machine, driven strictly by the pack voice render.
 * No audio, no timers, no I/O: the caller feeds events (transcript, keypad,
 * silence, busy, no_answer) and reads back the next prompt + accumulated answers.
 * This is what both the browser voice UI and the tests exercise.
 */
import type { ResponseItem, VoiceItem, VoiceRender } from '../data/types';
import { isKeypadOutOfRange, matchKeypad, matchSpeech, type MatchResult } from './intentMatcher';

export type Phase =
  | 'ringing'
  | 'opening'
  | 'asking' // waiting for input on the current item
  | 'confirming' // read back the matched label, awaiting accept/change
  | 'closing'
  | 'ended';

export type EndReason =
  | 'completed'
  | 'partial_two_silent'
  | 'voice_no_answer'
  | 'voice_busy'
  | 'hung_up';

export interface ItemProgress {
  item_id: string;
  value: string | null;
  input_kind: 'speech' | 'keypad' | null;
  attempts: number; // prompts shown for this item
  result: 'answered' | 'invalid' | 'not_reached';
}

export interface VoiceState {
  phase: Phase;
  itemIndex: number;
  items: ItemProgress[];
  consecutiveSilent: number;
  /** pending match awaiting confirmation */
  pendingMatch: MatchResult | null;
  endReason: EndReason | null;
  failureCode: string | null;
  /** what JAAKBOT should say right now (caption/tts) */
  prompt: string;
}

export function initVoice(render: VoiceRender): VoiceState {
  return {
    phase: 'ringing',
    itemIndex: -1,
    items: render.items.map((it) => ({
      item_id: it.item_id,
      value: null,
      input_kind: null,
      attempts: 0,
      result: 'not_reached',
    })),
    consecutiveSilent: 0,
    pendingMatch: null,
    endReason: null,
    failureCode: null,
    prompt: '',
  };
}

function currentItem(render: VoiceRender, s: VoiceState): VoiceItem | null {
  return render.items[s.itemIndex] ?? null;
}

function anyAnswered(s: VoiceState): boolean {
  return s.items.some((i) => i.result === 'answered');
}

function triggersFollowUp(render: VoiceRender, s: VoiceState): boolean {
  // Follow-up is driven by the SURVEY options' follow_up codes, not the render.
  // The render exposes closing_if_follow_up; the engine (console) computes the
  // actual follow-up from survey options. Here we expose a hook the caller sets.
  void render;
  void s;
  return false;
}

/** Caller answers the ringing/opening to begin; returns the first question. */
export function answerCall(render: VoiceRender, s: VoiceState): VoiceState {
  if (s.phase !== 'ringing') return s;
  return advanceToItem(render, { ...s, phase: 'opening' }, 0);
}

function advanceToItem(render: VoiceRender, s: VoiceState, index: number): VoiceState {
  const item = render.items[index];
  if (!item) {
    // no more items -> closing
    const followUp = triggersFollowUp(render, s);
    return {
      ...s,
      phase: 'closing',
      itemIndex: index,
      endReason: 'completed',
      prompt: followUp ? render.closing_if_follow_up : render.closing,
    };
  }
  const items = s.items.slice();
  const prev = items[index]!;
  items[index] = { ...prev, attempts: prev.attempts + 1 };
  return {
    ...s,
    phase: 'asking',
    itemIndex: index,
    items,
    consecutiveSilent: 0,
    pendingMatch: null,
    prompt: item.say,
  };
}

/** A spoken transcript for the current item. */
export function submitTranscript(render: VoiceRender, s: VoiceState, transcript: string): VoiceState {
  const item = currentItem(render, s);
  if (!item || s.phase !== 'asking') return s;
  const m = matchSpeech(item, transcript);
  if (m) return toConfirm(render, s, item, m);
  return reprompt(render, s, item);
}

/** A keypad digit for the current item. */
export function submitKeypad(render: VoiceRender, s: VoiceState, digit: string): VoiceState {
  const item = currentItem(render, s);
  if (!item || s.phase !== 'asking') return s;
  const m = matchKeypad(item, digit);
  if (m) return toConfirm(render, s, item, m);
  // out-of-range key counts like an unclear prompt
  if (isKeypadOutOfRange(item, digit)) {
    return reprompt(render, s, item, 'keypad_out_of_range');
  }
  return reprompt(render, s, item);
}

function toConfirm(render: VoiceRender, s: VoiceState, item: VoiceItem, m: MatchResult): VoiceState {
  void render;
  // read back the matched option label if present in speech synonyms, else value
  const label = item.speech?.[m.value]?.[0] ?? m.value;
  return { ...s, phase: 'confirming', pendingMatch: m, consecutiveSilent: 0, prompt: label };
}

/** Farmer accepts the read-back; record and move on. */
export function acceptConfirmation(render: VoiceRender, s: VoiceState): VoiceState {
  if (s.phase !== 'confirming' || !s.pendingMatch) return s;
  const items = s.items.slice();
  const cur = items[s.itemIndex]!;
  items[s.itemIndex] = {
    ...cur,
    value: s.pendingMatch.value,
    input_kind: s.pendingMatch.via,
    result: 'answered',
  };
  return advanceToItem(render, { ...s, items, pendingMatch: null }, s.itemIndex + 1);
}

/** Farmer rejects the read-back; ask again (does not add an attempt beyond cap). */
export function rejectConfirmation(render: VoiceRender, s: VoiceState): VoiceState {
  if (s.phase !== 'confirming') return s;
  const item = currentItem(render, s)!;
  return { ...s, phase: 'asking', pendingMatch: null, prompt: item.say };
}

function reprompt(render: VoiceRender, s: VoiceState, item: VoiceItem, failureHint?: string): VoiceState {
  // a no-match or invalid key counts toward the silent/repeat budget
  return handleNoInput(render, s, item, failureHint);
}

/** Silence (no input) on the current item. */
export function submitSilence(render: VoiceRender, s: VoiceState): VoiceState {
  const item = currentItem(render, s);
  if (!item || s.phase !== 'asking') return s;
  return handleNoInput(render, s, item);
}

function handleNoInput(
  render: VoiceRender,
  s: VoiceState,
  item: VoiceItem,
  failureHint?: string,
): VoiceState {
  const consecutiveSilent = s.consecutiveSilent + 1;
  const allowedRepeats = item.repeat_if_no_input ?? 1;
  if (consecutiveSilent > allowedRepeats) {
    // two prompts with no usable input in a row -> end call, save partial
    const items = s.items.slice();
    const cur = items[s.itemIndex]!;
    if (cur.result === 'not_reached') {
      items[s.itemIndex] = { ...cur, result: 'invalid' };
    }
    return {
      ...s,
      items,
      phase: 'ended',
      endReason: anyAnswered({ ...s, items }) ? 'partial_two_silent' : 'voice_no_answer',
      failureCode: failureHint ?? (anyAnswered({ ...s, items }) ? null : 'voice_no_answer'),
      prompt: render.closing,
    };
  }
  // repeat the same item once more
  const items = s.items.slice();
  const cur = items[s.itemIndex]!;
  items[s.itemIndex] = { ...cur, attempts: cur.attempts + 1 };
  return { ...s, items, consecutiveSilent, phase: 'asking', prompt: item.say };
}

/** Caller-reported line failures. */
export function reportBusy(s: VoiceState): VoiceState {
  return { ...s, phase: 'ended', endReason: 'voice_busy', failureCode: 'voice_busy', prompt: '' };
}
export function reportNoAnswer(s: VoiceState): VoiceState {
  return { ...s, phase: 'ended', endReason: 'voice_no_answer', failureCode: 'voice_no_answer', prompt: '' };
}
export function hangUp(render: VoiceRender, s: VoiceState): VoiceState {
  return {
    ...s,
    phase: 'ended',
    endReason: anyAnswered(s) ? 'hung_up' : 'voice_no_answer',
    failureCode: anyAnswered(s) ? 'voice_call_dropped' : 'voice_no_answer',
    prompt: render.closing,
  };
}

/** Take the closing to finish. */
export function finishClosing(s: VoiceState): VoiceState {
  if (s.phase !== 'closing') return s;
  return { ...s, phase: 'ended' };
}

/** Build the response items array for the record builder. */
export function toResponseItems(render: VoiceRender, s: VoiceState): ResponseItem[] {
  return render.items.map((it, i) => {
    const p = s.items[i]!;
    return {
      item_id: it.item_id,
      item_type: 'survey-single-select', // voice renders don't carry type; console maps from survey
      result: p.result === 'answered' ? 'answered' : p.result === 'invalid' ? 'invalid' : 'not_reached',
      value: p.value,
      raw_input: p.value,
      input_kind: p.input_kind,
      attempts: p.attempts,
    };
  });
}

export function answers(s: VoiceState): Record<string, string> {
  const out: Record<string, string> = {};
  for (const i of s.items) if (i.result === 'answered' && i.value) out[i.item_id] = i.value;
  return out;
}
