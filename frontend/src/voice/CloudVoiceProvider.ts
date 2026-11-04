import type { Language } from '../data/types';
import type { SttSession, VoiceProvider } from './VoiceProvider';

/**
 * Placeholder for a cloud STT/TTS provider (e.g. Amazon Transcribe/Polly).
 * OFF by default. When enabled, leavesBrowser is true and the UI must show a
 * clear "audio leaves the browser" indicator. Not wired to any network here.
 */
export class CloudVoiceProvider implements VoiceProvider {
  readonly kind = 'cloud' as const;
  readonly leavesBrowser = true;
  readonly hasAudio = false;
  isSpeechSupported(_lang: Language): boolean {
    return false;
  }
  startStt(_lang: Language, _onResult: (t: string) => void, onEnd?: () => void): SttSession {
    onEnd?.();
    return { stop() {} };
  }
  async speak(): Promise<void> {}
}
