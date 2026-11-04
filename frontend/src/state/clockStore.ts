import { create } from 'zustand';
import { advance, nextDue, SEASON_END, type ClockModel, type Diff } from './clockDiff';

const SEASON_START = '2026-11-01T07:00:00+05:30';

interface ClockStore {
  nowIso: string;
  model: ClockModel | null;
  lastDiff: Diff | null;
  setModel: (model: ClockModel) => void;
  step: (ms: number) => void;
  stepHours: (h: number) => void;
  stepDays: (d: number) => void;
  jumpToNextDue: () => void;
  setNow: (iso: string) => void;
  reset: () => void;
}

function applyAdvance(model: ClockModel | null, iso: string): Diff | null {
  return model ? advance(model, iso) : null;
}

export const useClockStore = create<ClockStore>((set, get) => ({
  nowIso: SEASON_START,
  model: null,
  lastDiff: null,
  setModel: (model) => set({ model, lastDiff: applyAdvance(model, get().nowIso) }),
  step: (ms) => {
    const next = new Date(Date.parse(get().nowIso) + ms).toISOString();
    // keep IST offset in the display string
    const iso = toIst(next);
    set({ nowIso: iso, lastDiff: applyAdvance(get().model, iso) });
  },
  stepHours: (h) => get().step(h * 3600_000),
  stepDays: (d) => get().step(d * 86_400_000),
  jumpToNextDue: () => {
    const m = get().model;
    if (!m) return;
    const nd = nextDue(m, get().nowIso);
    if (nd) set({ nowIso: nd, lastDiff: applyAdvance(m, nd) });
  },
  setNow: (iso) => set({ nowIso: iso, lastDiff: applyAdvance(get().model, iso) }),
  reset: () => set({ nowIso: SEASON_START, lastDiff: applyAdvance(get().model, SEASON_START) }),
}));

export { SEASON_START, SEASON_END };

/** Render a UTC ISO string as an IST (+05:30) ISO string. */
function toIst(utcIso: string): string {
  const d = new Date(utcIso);
  const istMs = d.getTime() + 5.5 * 3600_000;
  const s = new Date(istMs).toISOString().replace('Z', '+05:30');
  return s;
}
