import { describe, it, expect, beforeEach } from 'vitest';
import { dispatchOperator } from '../src/demo/OperatorControls';
import { OPERATOR_COMMANDS } from '../src/voice/operatorGrammar';
import { useClockStore } from '../src/state/clockStore';
import { useUiStore } from '../src/state/uiStore';
import { useDemoStore } from '../src/state/demoStore';

const cmd = (action: string) => OPERATOR_COMMANDS.find((c) => c.action === action)!;

describe('dispatchOperator wires commands to store actions', () => {
  beforeEach(() => {
    useClockStore.getState().reset();
    useDemoStore.getState().reset();
    useUiStore.getState().setLanguage('en-IN');
  });

  it('show_hindi switches the farmer language to Hindi', () => {
    dispatchOperator(cmd('show_hindi'));
    expect(useUiStore.getState().language).toBe('hi-IN');
  });

  it('start_demo activates the guided narration at step 0', () => {
    dispatchOperator(cmd('start_demo'));
    expect(useDemoStore.getState().active).toBe(true);
    expect(useDemoStore.getState().index).toBe(0);
  });

  it('reset deactivates the demo', () => {
    useDemoStore.getState().start();
    dispatchOperator(cmd('reset'));
    expect(useDemoStore.getState().active).toBe(false);
  });

  it('advance_one_day moves the simulated clock forward by a day', () => {
    const before = Date.parse(useClockStore.getState().nowIso);
    dispatchOperator(cmd('advance_one_day'));
    const after = Date.parse(useClockStore.getState().nowIso);
    expect(after - before).toBeGreaterThanOrEqual(86_400_000 - 1000);
  });

  it('show_evidence and open_follow_up emit a console-tab event', () => {
    const seen: string[] = [];
    const handler = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener('jaak:console-tab', handler as EventListener);
    dispatchOperator(cmd('show_evidence'));
    dispatchOperator(cmd('open_follow_up'));
    window.removeEventListener('jaak:console-tab', handler as EventListener);
    expect(seen).toEqual(['evidence', 'queues']);
  });
});
