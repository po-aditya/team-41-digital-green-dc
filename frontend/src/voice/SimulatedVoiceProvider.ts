import type { Language } from '../data/types';
import type { SttSession, VoiceProvider } from './VoiceProvider';

/**
 * Always-available provider: no microphone, no speech synthesis, no network.
 * STT is driven by the "simulate speech" chips (the caller calls onResult
 * directly), and TTS is a no-op; captions carry everything. Safe in any browser.
 */
export class SimulatedVoiceProvider implements VoiceProvider {
  readonly kind = 'simulated' as const;
  readonly leavesBrowser = false;
  readonly hasAudio = false;

  isSpeechSupported(_lang: Language): boolean {
    return false;
  }
  startStt(_lang: Language, _onResult: (t: string) => void, onEnd?: () => void): SttSession {
    // simulated: nothing to listen to; the chip row calls the engine directly.
    onEnd?.();
    return { stop() {} };
  }
  async speak(): Promise<void> {
    // captions only
  }
}
