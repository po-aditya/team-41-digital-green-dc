/**
 * Deterministic intent matcher for JAAKBOT (no LLM). It matches a transcript or
 * keypad digit ONLY against the current voice item's `speech` synonyms and
 * `keypad` map. No match -> null (the caller re-prompts). It never returns a
 * value from another item and never invents an answer.
 */
import type { VoiceItem } from '../data/types';

export function normalizeTranscript(text: string): string {
  return text
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[।.,!?;:]+$/g, '') // trailing punctuation incl. Devanagari danda
    .replace(/\s+/g, ' ')
    .trim();
}

export interface MatchResult {
  value: string; // the option value, e.g. "yes"
  via: 'speech' | 'keypad';
}

/** Match a spoken transcript against this item's speech synonyms only. */
export function matchSpeech(item: VoiceItem, transcript: string): MatchResult | null {
  const norm = normalizeTranscript(transcript);
  if (!norm) return null;
  for (const [value, synonyms] of Object.entries(item.speech ?? {})) {
    for (const syn of synonyms) {
      if (normalizeTranscript(syn) === norm) return { value, via: 'speech' };
    }
  }
  return null;
}

/** Match a keypad digit against this item's keypad map only. */
export function matchKeypad(item: VoiceItem, digit: string): MatchResult | null {
  const key = digit.trim();
  const value = item.keypad?.[key];
  return value ? { value, via: 'keypad' } : null;
}

/** True when the digit is outside the item's keypad map (keypad_out_of_range). */
export function isKeypadOutOfRange(item: VoiceItem, digit: string): boolean {
  const key = digit.trim();
  return /^\d$/.test(key) && !(key in (item.keypad ?? {}));
}
