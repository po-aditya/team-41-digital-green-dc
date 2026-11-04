/**
 * Pure bottom-sheet step logic (Property 6). One question per step; advance only
 * after an answer or skip; reach thank-you only after the last step; close/skip
 * handled explicitly. No rendering, no backend calls.
 */
import type { BottomSheetRender } from '../data/types';

export interface SheetState {
  stepIndex: number; // 0-based index into steps
  answers: Record<string, string>; // item_id -> answer value
  phase: 'question' | 'thank_you' | 'closed';
  closedReason?: 'completed' | 'skip_all' | 'closed';
}

export function initSheet(): SheetState {
  return { stepIndex: 0, answers: {}, phase: 'question' };
}

export function totalSteps(render: BottomSheetRender): number {
  return render.sheet.steps.length;
}

export function currentStep(render: BottomSheetRender, state: SheetState) {
  return render.sheet.steps[state.stepIndex] ?? null;
}

function lastIndex(render: BottomSheetRender): number {
  return render.sheet.steps.length - 1;
}

/** Record an answer for the current step and move forward. */
export function answer(render: BottomSheetRender, state: SheetState, value: string): SheetState {
  if (state.phase !== 'question') return state;
  const step = currentStep(render, state);
  if (!step) return state;
  const answers = { ...state.answers, [step.item_id]: value };
  if (state.stepIndex >= lastIndex(render)) {
    return { ...state, answers, phase: 'thank_you', closedReason: 'completed' };
  }
  return { ...state, answers, stepIndex: state.stepIndex + 1 };
}

/** Skip the current step without recording an answer; same advance rule. */
export function skip(render: BottomSheetRender, state: SheetState): SheetState {
  if (state.phase !== 'question') return state;
  if (state.stepIndex >= lastIndex(render)) {
    const anyAnswered = Object.keys(state.answers).length > 0;
    return {
      ...state,
      phase: anyAnswered ? 'thank_you' : 'closed',
      closedReason: anyAnswered ? 'completed' : 'skip_all',
    };
  }
  return { ...state, stepIndex: state.stepIndex + 1 };
}

/** Go back one step (allowed after step 1). */
export function back(state: SheetState): SheetState {
  if (state.phase !== 'question' || state.stepIndex === 0) return state;
  return { ...state, stepIndex: state.stepIndex - 1 };
}

/** Explicit close / swipe-down. */
export function close(state: SheetState): SheetState {
  return { ...state, phase: 'closed', closedReason: 'closed' };
}

/** 1-based step number for the segmented progress / step label. */
export function stepNumber(state: SheetState): number {
  return state.stepIndex + 1;
}
