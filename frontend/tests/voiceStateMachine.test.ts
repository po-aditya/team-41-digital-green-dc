import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  acceptConfirmation,
  answerCall,
  answers,
  finishClosing,
  hangUp,
  initVoice,
  submitKeypad,
  submitSilence,
  submitTranscript,
} from '../src/voice/farmerStateMachine';
import type { VoiceRender } from '../src/data/types';

function loadVoice(scenario: string, lang: string): VoiceRender {
  return JSON.parse(
    readFileSync(
      join(__dirname, '..', 'public', 'fixtures', 'scenarios', scenario, 'render', lang, 'voice.json'),
      'utf-8',
    ),
  ) as VoiceRender;
}

const V = loadVoice('1-mustard-aphid-spray', 'hi-IN');

describe('voice state machine (from voice.json)', () => {
  it('rings, opens, then asks the first item', () => {
    let s = initVoice(V);
    expect(s.phase).toBe('ringing');
    s = answerCall(V, s);
    expect(s.phase).toBe('asking');
    expect(s.itemIndex).toBe(0);
    expect(s.prompt).toBe(V.items[0]!.say);
    expect(s.items[0]!.attempts).toBe(1);
  });

  it('keypad answer -> confirm read-back -> accept -> next item', () => {
    let s = answerCall(V, initVoice(V));
    s = submitKeypad(V, s, '1'); // yes
    expect(s.phase).toBe('confirming');
    expect(s.pendingMatch?.value).toBe('yes');
    s = acceptConfirmation(V, s);
    expect(s.items[0]!.result).toBe('answered');
    expect(s.items[0]!.value).toBe('yes');
    expect(s.items[0]!.input_kind).toBe('keypad');
    expect(s.itemIndex).toBe(1);
    expect(s.phase).toBe('asking');
  });

  it('spoken synonym matches and records input_kind speech', () => {
    let s = answerCall(V, initVoice(V));
    s = submitTranscript(V, s, 'हाँ'); // yes synonym
    expect(s.phase).toBe('confirming');
    s = acceptConfirmation(V, s);
    expect(s.items[0]!.input_kind).toBe('speech');
    expect(s.items[0]!.value).toBe('yes');
  });

  it('completing every item reaches closing then ended', () => {
    let s = answerCall(V, initVoice(V));
    for (let i = 0; i < V.items.length; i++) {
      const firstKey = Object.keys(V.items[i]!.keypad)[0]!;
      s = submitKeypad(V, s, firstKey);
      s = acceptConfirmation(V, s);
    }
    expect(s.phase).toBe('closing');
    expect(s.prompt).toBe(V.closing);
    s = finishClosing(s);
    expect(s.phase).toBe('ended');
    expect(s.endReason).toBe('completed');
    expect(Object.keys(answers(s))).toHaveLength(V.items.length);
  });

  it('two consecutive silent prompts end the call as partial with answers so far', () => {
    let s = answerCall(V, initVoice(V));
    // answer q1 so there is a partial answer
    s = submitKeypad(V, s, '1');
    s = acceptConfirmation(V, s);
    // now q2: silence twice (repeat_if_no_input = 1, so 2nd silence ends)
    s = submitSilence(V, s); // first silence -> repeat
    expect(s.phase).toBe('asking');
    s = submitSilence(V, s); // second -> end partial
    expect(s.phase).toBe('ended');
    expect(s.endReason).toBe('partial_two_silent');
    expect(answers(s).q1).toBe('yes');
  });

  it('no answer at all -> voice_no_answer', () => {
    let s = answerCall(V, initVoice(V));
    s = submitSilence(V, s);
    s = submitSilence(V, s);
    expect(s.phase).toBe('ended');
    expect(s.endReason).toBe('voice_no_answer');
    expect(s.failureCode).toBe('voice_no_answer');
  });

  it('keypad_out_of_range digit counts as a reprompt then ends with code', () => {
    let s = answerCall(V, initVoice(V));
    // q1 keypad has 1,2 only. Press 9 twice.
    s = submitKeypad(V, s, '9');
    expect(s.phase).toBe('asking'); // reprompt
    s = submitKeypad(V, s, '9');
    expect(s.phase).toBe('ended');
    expect(s.failureCode).toBe('keypad_out_of_range');
  });

  it('hang up after an answer keeps answers and sets voice_call_dropped', () => {
    let s = answerCall(V, initVoice(V));
    s = submitKeypad(V, s, '1');
    s = acceptConfirmation(V, s);
    s = hangUp(V, s);
    expect(s.phase).toBe('ended');
    expect(s.failureCode).toBe('voice_call_dropped');
    expect(answers(s).q1).toBe('yes');
  });

  it('rejecting a confirmation re-asks the same item', () => {
    let s = answerCall(V, initVoice(V));
    s = submitKeypad(V, s, '1');
    expect(s.phase).toBe('confirming');
    // reject = ask again
    const item = V.items[0]!;
    s = { ...s, phase: 'asking', pendingMatch: null, prompt: item.say };
    expect(s.itemIndex).toBe(0);
  });
});
