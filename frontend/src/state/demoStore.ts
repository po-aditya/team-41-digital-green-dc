import { create } from 'zustand';

export interface DemoStep {
  id: string;
  at: string; // narration timestamp label
  caption: string;
}

/** The 4-minute guided walkthrough. Narration only; each step is advanced by
 *  Space or the Next button. The actual UI actions are wired in the director. */
export const DEMO_STEPS: DemoStep[] = [
  { id: 'intro', at: '0:00', caption: 'Problem and evidence: FarmerChat insights in, the agent decides who deserves a follow-up survey. All data is synthetic.' },
  { id: 'pipeline', at: '0:30', caption: 'Insights ingested; decisions explained by rule. Scenario 6 (zero-tillage) gets NO survey — restraint.' },
  { id: 'clock', at: '1:00', caption: 'Step the simulated clock. The mustard survey becomes due and drops on the phone, in Hindi.' },
  { id: 'voice', at: '1:45', caption: 'JAAKBOT: the farmer answers by voice. JAAKBOT confirms. The thank-you shows. input_kind = speech.' },
  { id: 'followup', at: '2:30', caption: 'A negative answer creates a follow-up case. The cow-vet case shows the human-queue path.' },
  { id: 'capexpiry', at: '3:00', caption: 'One survey deferred by the frequency cap; one held back by the 31 March season end.' },
  { id: 'evidence', at: '3:30', caption: 'Evidence: golden results, Hindi validity, cost and latency, the requirements panel, and the honest-limits footer.' },
];

interface DemoStore {
  active: boolean;
  index: number;
  start: () => void;
  exit: () => void;
  next: () => void;
  prev: () => void;
  reset: () => void;
}

export const useDemoStore = create<DemoStore>((set, get) => ({
  active: false,
  index: 0,
  start: () => set({ active: true, index: 0 }),
  exit: () => set({ active: false }),
  next: () => set({ index: Math.min(get().index + 1, DEMO_STEPS.length - 1) }),
  prev: () => set({ index: Math.max(get().index - 1, 0) }),
  reset: () => set({ active: false, index: 0 }),
}));
