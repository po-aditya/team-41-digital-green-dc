import { describe, it, expect } from 'vitest';
import { matchCommand, OPERATOR_COMMANDS, normalizeCommand } from '../src/voice/operatorGrammar';

describe('operator command grammar (fixed, no LLM)', () => {
  it('matches each canonical phrase to its action', () => {
    for (const cmd of OPERATOR_COMMANDS) {
      for (const p of cmd.phrases) {
        expect(matchCommand(p)?.action).toBe(cmd.action);
      }
    }
  });
  it('is case- and punctuation-insensitive', () => {
    expect(matchCommand('  Advance One Day.  ')?.action).toBe('advance_one_day');
    expect(matchCommand('RESET!')?.action).toBe('reset');
  });
  it('reset is the only destructive command', () => {
    expect(matchCommand('reset')?.destructive).toBe(true);
    expect(matchCommand('advance one day')?.destructive).toBe(false);
  });
  it('returns null for anything outside the grammar (never guesses)', () => {
    expect(matchCommand('what is the weather')).toBeNull();
    expect(matchCommand('delete everything')).toBeNull();
    expect(matchCommand('')).toBeNull();
    expect(matchCommand('tell me a joke')).toBeNull();
  });
  it('normalizeCommand collapses whitespace and trailing punctuation', () => {
    expect(normalizeCommand('  next   due?? ')).toBe('next due');
  });
});
