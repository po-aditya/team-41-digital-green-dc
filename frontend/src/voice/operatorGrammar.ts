/**
 * Operator-side fixed command grammar for JAAKBOT. NO LLM: a transcript is
 * normalised and matched against a fixed phrase table. Destructive commands
 * (reset) require confirmation. Every command maps to a named action the UI
 * can dispatch; all are also reachable by mouse/keyboard.
 */
export type OperatorAction =
  | 'advance_one_day'
  | 'jump_next_due'
  | 'open_follow_up'
  | 'show_hindi'
  | 'show_evidence'
  | 'start_demo'
  | 'reset';

export interface OperatorCommand {
  action: OperatorAction;
  label: string;
  destructive: boolean;
  phrases: string[];
}

export const OPERATOR_COMMANDS: OperatorCommand[] = [
  { action: 'advance_one_day', label: 'Advance one day', destructive: false, phrases: ['advance one day', 'next day', 'step one day', 'advance a day'] },
  { action: 'jump_next_due', label: 'Jump to next due survey', destructive: false, phrases: ['jump to next due survey', 'next due', 'jump to next due', 'next survey'] },
  { action: 'open_follow_up', label: 'Open follow-up queue', destructive: false, phrases: ['open follow-up queue', 'open follow up queue', 'show follow-ups', 'follow up queue'] },
  { action: 'show_hindi', label: 'Show Hindi', destructive: false, phrases: ['show hindi', 'switch to hindi', 'hindi'] },
  { action: 'show_evidence', label: 'Show evidence', destructive: false, phrases: ['show evidence', 'open evidence', 'evidence tab'] },
  { action: 'start_demo', label: 'Start demo', destructive: false, phrases: ['start demo', 'begin demo', 'run demo'] },
  { action: 'reset', label: 'Reset', destructive: true, phrases: ['reset', 'reset demo', 'start over'] },
];

export function normalizeCommand(text: string): string {
  return text
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[.,!?;:\s]+$/g, '')
    .trim();
}

/** Deterministic match: exact phrase equality after normalisation. Returns null
 *  when nothing matches (the UI shows "command not recognised"). */
export function matchCommand(text: string): OperatorCommand | null {
  const norm = normalizeCommand(text);
  if (!norm) return null;
  for (const cmd of OPERATOR_COMMANDS) {
    if (cmd.phrases.some((p) => normalizeCommand(p) === norm)) return cmd;
  }
  return null;
}
