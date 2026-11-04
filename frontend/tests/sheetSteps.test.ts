import { describe, it, expect } from 'vitest';
import {
  answer,
  back,
  close,
  currentStep,
  initSheet,
  skip,
  stepNumber,
  totalSteps,
} from '../src/state/sheetSteps';
import type { BottomSheetRender } from '../src/data/types';

function makeRender(steps: number): BottomSheetRender {
  return {
    channel: 'app',
    how_it_arrives: 'x',
    presentation: {
      type: 'bottom_sheet',
      opens_when: ['push_tapped'],
      waits_for: [],
      one_question_per_step: true,
      steps_total: steps,
      can_skip: true,
      can_close: true,
      swipe_down_closes: true,
    },
    sheet: {
      title: 'T',
      skip_label: 'Skip',
      close_label: 'Close',
      thank_you: 'Thanks',
      steps: Array.from({ length: steps }, (_, i) => ({
        step: i + 1,
        step_label: `${steps} / ${i + 1}`,
        item_id: `q${i + 1}`,
        question_type: 'survey-single-select' as const,
        question: `Q${i + 1}`,
        options: [
          { label: 'A', answer: 'a' },
          { label: 'B', answer: 'b' },
        ],
      })),
    },
  };
}

describe('sheet step logic (Property 6: monotonic and bounded)', () => {
  it('visits each step once in order and reaches thank_you only after the last', () => {
    const r = makeRender(3);
    let s = initSheet();
    const visited: string[] = [];
    while (s.phase === 'question') {
      const step = currentStep(r, s)!;
      visited.push(step.item_id);
      s = answer(r, s, 'a');
    }
    expect(visited).toEqual(['q1', 'q2', 'q3']);
    expect(s.phase).toBe('thank_you');
    expect(Object.keys(s.answers)).toEqual(['q1', 'q2', 'q3']);
  });

  it('records the chosen answer per step', () => {
    const r = makeRender(2);
    let s = initSheet();
    s = answer(r, s, 'b');
    expect(s.answers.q1).toBe('b');
    s = answer(r, s, 'a');
    expect(s.answers.q2).toBe('a');
    expect(s.phase).toBe('thank_you');
  });

  it('never advances past the last step', () => {
    const r = makeRender(1);
    let s = initSheet();
    s = answer(r, s, 'a');
    expect(s.phase).toBe('thank_you');
    // further answers are no-ops once not in question phase
    const s2 = answer(r, s, 'b');
    expect(s2).toEqual(s);
  });

  it('stepNumber is 1-based and within bounds', () => {
    const r = makeRender(3);
    let s = initSheet();
    expect(stepNumber(s)).toBe(1);
    s = answer(r, s, 'a');
    expect(stepNumber(s)).toBe(2);
    expect(stepNumber(s)).toBeLessThanOrEqual(totalSteps(r));
  });

  it('skip advances without recording; skipping all closes with no answers', () => {
    const r = makeRender(2);
    let s = initSheet();
    s = skip(r, s);
    expect(s.answers).toEqual({});
    expect(s.stepIndex).toBe(1);
    s = skip(r, s);
    expect(s.phase).toBe('closed');
    expect(s.closedReason).toBe('skip_all');
  });

  it('partial: skip last after answering first still reaches thank_you', () => {
    const r = makeRender(2);
    let s = initSheet();
    s = answer(r, s, 'a');
    s = skip(r, s);
    expect(s.phase).toBe('thank_you');
    expect(s.answers.q1).toBe('a');
  });

  it('back is bounded and clears forward progress by index only', () => {
    const r = makeRender(3);
    let s = initSheet();
    s = answer(r, s, 'a');
    expect(s.stepIndex).toBe(1);
    s = back(s);
    expect(s.stepIndex).toBe(0);
    // back at step 0 is a no-op
    const s2 = back(s);
    expect(s2.stepIndex).toBe(0);
  });

  it('close ends the sheet immediately', () => {
    const r = makeRender(3);
    let s = initSheet();
    s = answer(r, s, 'a');
    s = close(s);
    expect(s.phase).toBe('closed');
    expect(s.closedReason).toBe('closed');
  });
});
