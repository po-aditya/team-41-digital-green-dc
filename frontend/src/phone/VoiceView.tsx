import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, PhoneOff, Volume2 } from 'lucide-react';
import type { Language, VoiceRender } from '../data/types';
import type { VoiceProvider, SttSession } from '../voice/VoiceProvider';
import {
  acceptConfirmation,
  answerCall,
  answers,
  finishClosing,
  hangUp,
  initVoice,
  rejectConfirmation,
  reportBusy,
  reportNoAnswer,
  submitKeypad,
  submitSilence,
  submitTranscript,
  toResponseItems,
  type VoiceState,
} from '../voice/farmerStateMachine';
import { LiveRegion } from '../ui/LiveRegion';
import { PrimaryButton } from '../ui/PrimaryButton';
import { SimulateSpeechChips } from './SimulateSpeechChips';
import styles from './VoiceView.module.css';

export interface VoiceComplete {
  answers: Record<string, string>;
  items: ReturnType<typeof toResponseItems>;
  endReason: VoiceState['endReason'];
  failureCode: string | null;
}

export function VoiceView({
  render,
  lang,
  provider,
  onComplete,
}: {
  render: VoiceRender;
  lang: Language;
  provider: VoiceProvider;
  onComplete: (r: VoiceComplete) => void;
}) {
  const [state, setState] = useState<VoiceState>(() => initVoice(render));
  const [listening, setListening] = useState(false);
  const sttRef = useRef<SttSession | null>(null);
  const speechSupported = provider.isSpeechSupported(lang);

  // speak the prompt when it changes (captions always shown regardless)
  useEffect(() => {
    if (provider.hasAudio && state.prompt) void provider.speak(state.prompt, lang);
  }, [state.prompt, provider, lang]);

  // fire onComplete once the call ends
  const endedRef = useRef(false);
  useEffect(() => {
    if (state.phase === 'ended' && !endedRef.current) {
      endedRef.current = true;
      onComplete({
        answers: answers(state),
        items: toResponseItems(render, state),
        endReason: state.endReason,
        failureCode: state.failureCode,
      });
    }
  }, [state, render, onComplete]);

  const currentItem = state.itemIndex >= 0 ? render.items[state.itemIndex] : null;

  const stopListening = () => {
    sttRef.current?.stop();
    sttRef.current = null;
    setListening(false);
  };
  const startListening = () => {
    if (!speechSupported) return;
    setListening(true);
    sttRef.current = provider.startStt(
      lang,
      (t) => {
        setState((s) => submitTranscript(render, s, t));
        stopListening();
      },
      () => setListening(false),
    );
  };

  return (
    <div className={styles.call}>
      <LiveRegion message={state.prompt} />
      <div className={styles.header}>
        <span className={styles.who}>JAAKBOT</span>
        <span className={styles.status}>
          {state.phase === 'ringing'
            ? 'Ringing…'
            : state.phase === 'ended'
              ? 'Call ended'
              : 'On call'}
        </span>
        {provider.leavesBrowser && <span className={styles.leaves}>audio leaves the browser</span>}
      </div>

      <div className={`${styles.captionBox} ${listening ? styles.listening : ''}`}>
        {provider.hasAudio && <Volume2 size={16} aria-hidden="true" />}
        <p className={styles.caption} lang={lang}>
          {state.prompt || (state.phase === 'ringing' ? render.opening : '')}
        </p>
      </div>

      {state.phase === 'ringing' && (
        <PrimaryButton onClick={() => setState(answerCall(render, state))}>Answer call</PrimaryButton>
      )}

      {state.phase === 'confirming' && (
        <div className={styles.confirm}>
          <p className={styles.heard} lang={lang}>
            You said: {state.prompt}
          </p>
          <div className={styles.confirmBtns}>
            <PrimaryButton onClick={() => setState(acceptConfirmation(render, state))}>Yes, correct</PrimaryButton>
            <button type="button" className={styles.change} onClick={() => setState(rejectConfirmation(render, state))}>
              Change
            </button>
          </div>
        </div>
      )}

      {state.phase === 'asking' && currentItem && (
        <>
          <div className={styles.keypad} role="group" aria-label="Keypad">
            {Object.keys(currentItem.keypad).map((digit) => (
              <button
                key={digit}
                type="button"
                className={styles.key}
                onClick={() => setState(submitKeypad(render, state, digit))}
              >
                <span className={styles.keyDigit}>{digit}</span>
                <span className={styles.keyLabel} lang={lang}>
                  {currentItem.speech[currentItem.keypad[digit]!]?.[0] ?? currentItem.keypad[digit]}
                </span>
              </button>
            ))}
          </div>

          <div className={styles.micRow}>
            {listening ? (
              <button type="button" className={styles.micOn} onClick={stopListening}>
                <MicOff size={18} /> Stop
              </button>
            ) : (
              <button
                type="button"
                className={styles.mic}
                disabled={!speechSupported}
                onClick={startListening}
                title={speechSupported ? 'Speak your answer' : 'Voice not available in this browser'}
              >
                <Mic size={18} /> Speak
              </button>
            )}
            <button type="button" className={styles.silence} onClick={() => setState(submitSilence(render, state))}>
              (silence)
            </button>
          </div>
          {!speechSupported && (
            <p className={styles.hint}>
              Voice input is not available in this browser. Use the keypad or the chips below.
            </p>
          )}

          <div className={styles.simLabel}>Simulate a spoken answer:</div>
          <SimulateSpeechChips
            item={currentItem}
            lang={lang}
            onSay={(t) => setState(submitTranscript(render, state, t))}
          />
        </>
      )}

      {state.phase === 'closing' && (
        <PrimaryButton onClick={() => setState(finishClosing(state))}>Finish</PrimaryButton>
      )}

      {state.phase !== 'ended' && (
        <div className={styles.callControls}>
          <button type="button" className={styles.hangup} onClick={() => setState(hangUp(render, state))}>
            <PhoneOff size={16} /> Hang up
          </button>
          <button type="button" className={styles.simFail} onClick={() => setState(reportBusy(state))}>
            line busy
          </button>
          <button type="button" className={styles.simFail} onClick={() => setState(reportNoAnswer(state))}>
            no answer
          </button>
        </div>
      )}

      <p className={styles.privacy}>
        No audio is recorded or sent. The mic turns on only when you tap it.
      </p>
    </div>
  );
}
