import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { matchKeypad, matchSpeech, isKeypadOutOfRange, normalizeTranscript } from '../src/voice/intentMatcher';
import type { VoiceRender } from '../src/data/types';

const FIX = join(__dirname, '..', 'public', 'fixtures', 'scenarios');

function allVoiceRenders(): { scenario: string; lang: string; render: VoiceRender }[] {
  const out: { scenario: string; lang: string; render: VoiceRender }[] = [];
  for (const scenario of readdirSync(FIX)) {
    for (const lang of ['en-IN', 'hi-IN']) {
      const p = join(FIX, scenario, 'render', lang, 'voice.json');
      if (existsSync(p)) out.push({ scenario, lang, render: JSON.parse(readFileSync(p, 'utf-8')) });
    }
  }
  return out;
}

const renders = allVoiceRenders();

describe('intent matcher over every speech synonym (all scenarios, both languages)', () => {
  it('has voice renders to test', () => {
    expect(renders.length).toBeGreaterThanOrEqual(10);
  });

  it('every speech synonym matches its own item and returns its value', () => {
    let checked = 0;
    for (const { render } of renders) {
      for (const item of render.items) {
        for (const [value, synonyms] of Object.entries(item.speech ?? {})) {
          for (const syn of synonyms) {
            const m = matchSpeech(item, syn);
            expect(m, `synonym "${syn}" should match`).not.toBeNull();
            expect(m!.value).toBe(value);
            expect(m!.via).toBe('speech');
            checked += 1;
          }
        }
      }
    }
    expect(checked).toBeGreaterThanOrEqual(120);
  });

  it('every keypad digit maps to its value and out-of-range is detected', () => {
    for (const { render } of renders) {
      for (const item of render.items) {
        for (const [digit, value] of Object.entries(item.keypad ?? {})) {
          expect(matchKeypad(item, digit)).toEqual({ value, via: 'keypad' });
        }
        // a digit not in the map is out of range
        const used = new Set(Object.keys(item.keypad ?? {}));
        const unused = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'].find((d) => !used.has(d))!;
        expect(isKeypadOutOfRange(item, unused)).toBe(true);
        expect(matchKeypad(item, unused)).toBeNull();
      }
    }
  });

  it('a synonym from one item does NOT match a different item (no cross-item leakage)', () => {
    for (const { render } of renders) {
      for (let i = 0; i < render.items.length; i++) {
        for (let j = 0; j < render.items.length; j++) {
          if (i === j) continue;
          const itemA = render.items[i]!;
          const itemB = render.items[j]!;
          const aSyns = new Set(
            Object.values(itemA.speech ?? {}).flat().map(normalizeTranscript),
          );
          const bSyns = new Set(
            Object.values(itemB.speech ?? {}).flat().map(normalizeTranscript),
          );
          for (const [value, synonyms] of Object.entries(itemA.speech ?? {})) {
            for (const syn of synonyms) {
              const n = normalizeTranscript(syn);
              // only assert "no match on item B" when B has no synonym with the same text
              if (!bSyns.has(n)) {
                expect(matchSpeech(itemB, syn), `"${syn}" leaked into another item`).toBeNull();
              }
              expect(matchSpeech(itemA, syn)!.value).toBe(value);
              void aSyns;
            }
          }
        }
      }
    }
  });

  it('gibberish and empty never match', () => {
    const item = renders[0]!.render.items[0]!;
    expect(matchSpeech(item, 'zzzqqq nonsense')).toBeNull();
    expect(matchSpeech(item, '')).toBeNull();
    expect(matchSpeech(item, '   ')).toBeNull();
  });

  it('normalisation ignores case and trailing punctuation incl. danda', () => {
    const item = renders.find((r) => r.lang === 'hi-IN')!.render.items[0]!;
    const firstValue = Object.keys(item.speech)[0]!;
    const syn = item.speech[firstValue]![0]!;
    expect(matchSpeech(item, `${syn}।`)!.value).toBe(firstValue);
    expect(matchSpeech(item, `${syn.toUpperCase()}`)!.value).toBe(firstValue);
  });
});
