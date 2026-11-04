import { describe, it, expect } from 'vitest';
import { chipFor, ALL_STATES } from '../src/state/statusChips';

describe('status chip mapping (Property 7: total, icon+label)', () => {
  it('returns exactly one icon+label for every state, never undefined', () => {
    for (const s of ALL_STATES) {
      const spec = chipFor(s);
      expect(spec).toBeDefined();
      expect(spec.label.length).toBeGreaterThan(0);
      expect(spec.icon).toBeTruthy();
      expect(['neutral', 'green', 'amber', 'critical']).toContain(spec.tone);
    }
  });
  it('covers all nine timeline states', () => {
    expect(ALL_STATES).toHaveLength(9);
  });
});
