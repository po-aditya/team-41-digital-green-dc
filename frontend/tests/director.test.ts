import { describe, it, expect, beforeEach } from 'vitest';
import {
  initDirector,
  moneyMomentSteps,
  resetDemo,
  runAll,
  stepForward,
} from '../src/demo/director';
import { useClockStore } from '../src/state/clockStore';
import { useUiStore } from '../src/state/uiStore';
import { useDemoStore } from '../src/state/demoStore';
import { useResponsesStore } from '../src/state/responsesStore';

const SCENARIO = '1-mustard-aphid-spray';

describe('money-moment director', () => {
  beforeEach(() => {
    resetDemo();
    useUiStore.getState().setLanguage('en-IN');
    useUiStore.getState().selectScenario(null);
  });

  it('exposes steps in a fixed, named order', () => {
    const ids = moneyMomentSteps(SCENARIO).map((s) => s.id);
    expect(ids).toEqual([
      'reset',
      'pick_survey_scenario',
      'show_hindi',
      'step_clock_to_due',
      'open_phone_hint',
      'reveal_follow_up',
    ]);
  });

  it('stepForward advances one step at a time and finishes', () => {
    const steps = moneyMomentSteps(SCENARIO);
    let st = initDirector();
    expect(st.index).toBe(0);
    expect(st.done).toBe(false);
    for (let i = 0; i < steps.length; i++) st = stepForward(steps, st);
    expect(st.done).toBe(true);
    expect(st.index).toBe(steps.length);
    // stepping past the end is a no-op
    const after = stepForward(steps, st);
    expect(after).toEqual(st);
  });

  it('pick_survey_scenario and show_hindi mutate the ui store in order', () => {
    const steps = moneyMomentSteps(SCENARIO);
    let st = initDirector();
    st = stepForward(steps, st); // reset
    st = stepForward(steps, st); // pick_survey_scenario
    expect(useUiStore.getState().activeScenario).toBe(SCENARIO);
    expect(useUiStore.getState().language).toBe('en-IN'); // not yet Hindi
    stepForward(steps, st); // show_hindi
    expect(useUiStore.getState().language).toBe('hi-IN');
  });

  it('runAll drives the whole sequence and ends on the survey scenario in Hindi', () => {
    runAll(moneyMomentSteps(SCENARIO));
    expect(useUiStore.getState().activeScenario).toBe(SCENARIO);
    expect(useUiStore.getState().language).toBe('hi-IN');
  });

  it('resetDemo returns the stores to their initial state', () => {
    useDemoStore.getState().start();
    useClockStore.getState().stepDays(3);
    useResponsesStore.getState().record(
      { survey_id: 'S-1', farmer_id: 'F-1', source_insight_ids: [], channel: 'app', language: 'en-IN',
        status: 'completed', failure_code: null, sheet_outcome: 'finished', answers: {}, items: [],
        complete: true, delivery_attempt: 1, timestamps: {}, recorded_at: 'x', answered_by: 'farmer',
        raw_event: null, retry_decision: 'none', retry_after_minutes: null, counts_toward_cap: true,
        farmerchat_reply: null, needs_follow_up: false, follow_up_reasons: [], response_key: 'S-1:app' },
      null,
      false,
    );
    resetDemo();
    expect(useDemoStore.getState().active).toBe(false);
    expect(useResponsesStore.getState().responses).toEqual([]);
    expect(useResponsesStore.getState().followUps).toEqual([]);
  });
});
