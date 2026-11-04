import type { Language } from '../data/types';
import type { SttSession, VoiceProvider } from './VoiceProvider';

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start(): void;
  stop(): void;
};

function getRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/**
 * Real browser voice via the Web Speech API + speechSynthesis, feature-detected.
 * Audio stays in the browser (the engine may still route to a cloud service for
 * recognition in some browsers; that is the browser's behaviour, not ours).
 */
export class BrowserVoiceProvider implements VoiceProvider {
  readonly kind = 'browser' as const;
  readonly leavesBrowser = false;
  readonly hasAudio =
    typeof window !== 'undefined' && typeof window.speechSynthesis !== 'undefined';

  isSpeechSupported(_lang: Language): boolean {
    return getRecognitionCtor() !== null;
  }

  startStt(lang: Language, onResult: (t: string) => void, onEnd?: () => void): SttSession {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      onEnd?.();
      return { stop() {} };
    }
    const rec = new Ctor();
    rec.lang = lang;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      const first = e.results[0]?.[0]?.transcript;
      if (first) onResult(first);
    };
    rec.onend = () => onEnd?.();
    rec.onerror = () => onEnd?.();
    rec.start();
    return {
      stop() {
        try {
          rec.stop();
        } catch {
          /* already stopped */
        }
      },
    };
  }

  async speak(text: string, lang: Language): Promise<void> {
    if (typeof window === 'undefined' || !window.speechSynthesis) return;
    await new Promise<void>((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang;
      u.onend = () => resolve();
      u.onerror = () => resolve();
      window.speechSynthesis.speak(u);
    });
  }
}
