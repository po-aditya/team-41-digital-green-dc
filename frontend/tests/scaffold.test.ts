import { describe, it, expect } from 'vitest';

describe('scaffold', () => {
  it('runs vitest', () => {
    expect(1 + 1).toBe(2);
  });
  it('has VITE env typing available', () => {
    // import.meta.env exists under vite/vitest
    expect(typeof import.meta.env).toBe('object');
  });
});
