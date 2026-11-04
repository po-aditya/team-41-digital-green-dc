/**
 * The money-moment director. A deterministic, ordered sequence of named steps
 * that drive the existing stores (clock, ui language, demo narration) and the
 * console tab. It does NOT invent farmer answers — the negative tap/voice
 * answer is performed in the phone UI by the presenter; the director only sets
 * the stage and then reveals the follow-up case. Pure w.r.t. React so the step
 * ORDER and transitions are unit-testable.
 */
import { useClockStore } from '../state/clockStore';
import { useUiStore } from '../state/uiStore';
import { useDemoStore } from '../state/demoStore';
import { useResponsesStore } from '../state/responsesStore';

export type MoneyStepId =
  | 'reset'
  | 'pick_survey_scenario'
  | 'show_hindi'
  | 'step_clock_to_due'
  | 'open_phone_hint'
  | 'reveal_follow_up';

export interface MoneyStep {
  id: MoneyStepId;
  caption: string;
  run: () => void;
}

/** Build the ordered steps. `surveyScenario` is the scenario that gets a survey
 *  (the mustard case); passing it keeps the director data-driven, not hardcoded. */
export function moneyMomentSteps(surveyScenario: string): MoneyStep[] {
  return [
    {
      id: 'reset',
      caption: 'Reset to the start of the season.',
      run: () => {
        useClockStore.getState().reset();
        useResponsesStore.getState().reset();
      },
    },
    {
      id: 'pick_survey_scenario',
      caption: 'Select the mustard follow-up scenario on the phone.',
      run: () => useUiStore.getState().selectScenario(surveyScenario),
    },
    {
      id: 'show_hindi',
      caption: 'Switch the farmer view to Hindi.',
      run: () => useUiStore.getState().setLanguage('hi-IN'),
    },
    {
      id: 'step_clock_to_due',
      caption: 'Advance the simulated clock until the survey is due.',
      run: () => useClockStore.getState().jumpToNextDue(),
    },
    {
      id: 'open_phone_hint',
      caption: 'Farmer taps the sheet and answers "advice did not work".',
      run: () => window.dispatchEvent(new CustomEvent('jaak:focus-phone')),
    },
    {
      id: 'reveal_follow_up',
      caption: 'A follow-up case appears in the queue — no operator action needed.',
      run: () => window.dispatchEvent(new CustomEvent('jaak:console-tab', { detail: 'queues' })),
    },
  ];
}

export interface DirectorState {
  index: number;
  done: boolean;
}

export function initDirector(): DirectorState {
  return { index: 0, done: false };
}

/** Run the current step and advance. Returns the next state. */
export function stepForward(steps: MoneyStep[], state: DirectorState): DirectorState {
  if (state.done || state.index >= steps.length) return { index: steps.length, done: true };
  steps[state.index]!.run();
  const nextIndex = state.index + 1;
  return { index: nextIndex, done: nextIndex >= steps.length };
}

/** Run every step in order (used by the one-click money moment). */
export function runAll(steps: MoneyStep[]): void {
  let st = initDirector();
  while (!st.done) st = stepForward(steps, st);
}

/** Reset all demo-affecting stores to their initial state. */
export function resetDemo(): void {
  useClockStore.getState().reset();
  useResponsesStore.getState().reset();
  useDemoStore.getState().reset();
}
