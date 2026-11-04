/**
 * Swappable voice provider. No required cloud keys. Speech-to-text and
 * text-to-speech are optional capabilities; the simulated provider always works
 * (chips + captions) so the demo runs offline with no microphone.
 */
import type { Language } from '../data/types';

export interface SttSession {
  stop(): void;
}

export interface VoiceProvider {
  readonly kind: 'browser' | 'simulated' | 'cloud';
  /** true only for a cloud provider; the UI shows an "audio leaves the browser" badge. */
  readonly leavesBrowser: boolean;
  isSpeechSupported(lang: Language): boolean;
  /** start listening; onResult is called with a final transcript. Returns a stoppable session. */
  startStt(lang: Language, onResult: (transcript: string) => void, onEnd?: () => void): SttSession;
  /** speak text; resolves when done (or immediately if TTS unavailable). */
  speak(text: string, lang: Language): Promise<void>;
  /** does this provider actually emit audio (vs captions only)? */
  readonly hasAudio: boolean;
}
