import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useDataSource } from '../data/SourceProvider';
import { useUiStore } from '../state/uiStore';
import { useResponsesStore } from '../state/responsesStore';
import { qk } from '../data/queryKeys';
import { DeviceFrame } from '../ui/DeviceFrame';
import { Dialog } from '../ui/Dialog';
import { QueryBoundary } from '../ui/States';
import { BottomSheet } from './BottomSheet';
import { ChannelSwitcher } from './ChannelSwitcher';
import { WhatsAppView } from './WhatsAppView';
import { TelegramView } from './TelegramView';
import { VoiceView } from './VoiceView';
import { BrowserVoiceProvider } from '../voice/BrowserVoiceProvider';
import { SimulatedVoiceProvider } from '../voice/SimulatedVoiceProvider';
import { buildResponse, tapInputKind, toFollowUp } from './responseBuilder';
import type {
  BottomSheetRender,
  Channel,
  ChatMessageRender,
  ScheduleHandoff,
  Survey,
  VoiceRender,
} from '../data/types';
import styles from './PhonePane.module.css';

export function PhonePane() {
  const ds = useDataSource();
  const language = useUiStore((s) => s.language);
  const activeScenario = useUiStore((s) => s.activeScenario);
  const selectScenario = useUiStore((s) => s.selectScenario);
  const channel = useUiStore((s) => s.activeChannel);
  const setChannel = useUiStore((s) => s.setChannel);
  const recordResponse = useResponsesStore((s) => s.record);

  const scenarios = useQuery({ queryKey: qk.scenarios, queryFn: ({ signal }) => ds.listScenarios(signal) });
  const scenario = activeScenario ?? scenarios.data?.find((x) => x.decision === 'survey')?.scenario ?? null;

  const detail = useQuery({
    queryKey: scenario ? qk.scenario(scenario) : ['scenario', 'none'],
    queryFn: ({ signal }) => ds.getScenario(scenario!, signal),
    enabled: !!scenario,
  });
  const renders = useQuery({
    queryKey: scenario ? qk.renders(scenario, language) : ['renders', 'none'],
    queryFn: ({ signal }) => ds.getRenders(scenario!, language, signal),
    enabled: !!scenario,
  });

  const [sheetOpen, setSheetOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const appRender = renders.data?.[channel === 'web' ? 'web' : 'app'] as BottomSheetRender | undefined;
  const chatRender = renders.data?.[channel] as ChatMessageRender | undefined;
  const voiceRender = renders.data?.voice as VoiceRender | undefined;

  const survey: Survey | undefined = detail.data?.surveys[language] ?? detail.data?.surveys['en-IN'];
  const handoff: ScheduleHandoff | null = detail.data?.handoff ?? null;

  // Record a completed set of answers: build the ResponseRecord, persist it via
  // POST when a real flow exists (else label it simulated), and create a
  // follow-up case for a negative answer. Returns the note to show.
  const submit = useCallback(
    async (ch: Channel, answers: Record<string, string>): Promise<string> => {
      if (!survey) return `Answered (simulated tap, not persisted)`;
      const record = buildResponse({ survey, channel: ch, language, answers, inputKind: tapInputKind(ch) });
      const followUp = toFollowUp(record);
      const flowId = handoff?.farmerchat_flow.flow_id ?? null;
      let persisted = false;
      if (flowId) {
        try {
          await ds.postResponse(flowId, record);
          persisted = true;
        } catch {
          persisted = false;
        }
      }
      recordResponse(record, followUp, persisted);
      const base = persisted ? 'recorded via POST /v1/surveys/{flow}/responses' : 'simulated tap, not persisted';
      if (followUp) return `Follow-up case created: ${followUp.reasons.join(', ')} (${base})`;
      return `Answered (${base})`;
    },
    [survey, language, handoff, ds, recordResponse],
  );

  // pick a voice provider: real browser speech if available, else simulated
  const voiceProvider = useMemo(() => {
    const browser = new BrowserVoiceProvider();
    return browser.isSpeechSupported(language) ? browser : new SimulatedVoiceProvider();
  }, [language]);

  const isSheetChannel = channel === 'app' || channel === 'web';

  return (
    <div className={styles.wrap}>
      <div className={styles.selector}>
        <label>
          <span className="visually-hidden">Scenario</span>
          <select value={scenario ?? ''} onChange={(e) => { selectScenario(e.target.value); setNote(null); }}>
            {scenarios.data?.map((s) => (
              <option key={s.scenario} value={s.scenario}>
                {s.scenario}
                {s.decision === 'no_survey' ? ' (no survey)' : ''}
              </option>
            ))}
          </select>
        </label>
      </div>

      <ChannelSwitcher value={channel} onChange={(c) => { setChannel(c); setNote(null); }} />

      <DeviceFrame>
        <QueryBoundary
          status={renders.status}
          error={renders.error}
          data={renders.data}
          onRetry={() => renders.refetch()}
          loadingLabel="Loading channel…"
        >
          {() => {
            if (note) return <div className={styles.chat}><div className={styles.doneNote} lang={language}>{note}</div></div>;

            if (isSheetChannel) {
              if (!appRender) return <div className={styles.chat}><p className={styles.noRender}>No {channel} sheet render.</p></div>;
              return (
                <div className={styles.chat}>
                  <div className={styles.advice} lang={detail.data?.insight.conversation_language}>
                    <p className={styles.adviceLabel}>FarmerChat</p>
                    <p>{detail.data?.insight.advice_summary ?? ''}</p>
                  </div>
                  <button type="button" className={styles.push} onClick={() => setSheetOpen(true)}>
                    <strong lang={language}>{appRender.sheet.title}</strong>
                    <span>Tap to answer</span>
                  </button>
                  <Dialog open={sheetOpen} onClose={() => setSheetOpen(false)} labelledBy="sheet-title">
                    <BottomSheet
                      render={appRender}
                      lang={language}
                      onComplete={(s) => {
                        setSheetOpen(false);
                        void submit(channel, s.answers).then(setNote);
                      }}
                      onClose={() => setSheetOpen(false)}
                    />
                  </Dialog>
                </div>
              );
            }

            if (channel === 'whatsapp' && chatRender)
              return <WhatsAppView render={chatRender} lang={language} onAnswer={(id, v) => void submit('whatsapp', { [id]: v }).then(setNote)} />;
            if (channel === 'telegram' && chatRender)
              return <TelegramView render={chatRender} lang={language} onAnswer={(id, v) => void submit('telegram', { [id]: v }).then(setNote)} />;
            if (channel === 'voice' && voiceRender)
              return (
                <VoiceView
                  render={voiceRender}
                  lang={language}
                  provider={voiceProvider}
                  onComplete={(r) => {
                    if (r.failureCode) {
                      setNote(`Call ended: ${r.failureCode} (simulated)`);
                      return;
                    }
                    void submit('voice', r.answers).then(setNote);
                  }}
                />
              );
            return <div className={styles.chat}><p className={styles.noRender}>No render for this channel.</p></div>;
          }}
        </QueryBoundary>
      </DeviceFrame>
    </div>
  );
}
