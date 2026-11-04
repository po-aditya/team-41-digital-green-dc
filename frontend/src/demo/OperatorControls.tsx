import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Mic, Play, RotateCcw, Zap } from 'lucide-react';
import { useDataSource } from '../data/SourceProvider';
import { qk } from '../data/queryKeys';
import { moneyMomentSteps, resetDemo, runAll } from './director';
import { matchCommand, type OperatorCommand } from '../voice/operatorGrammar';
import { useClockStore } from '../state/clockStore';
import { useDemoStore } from '../state/demoStore';
import { useUiStore } from '../state/uiStore';
import { BrowserVoiceProvider } from '../voice/BrowserVoiceProvider';
import styles from './OperatorControls.module.css';

/** Dispatches a recognised operator command to the stores. Also used by tests. */
export function dispatchOperator(cmd: OperatorCommand) {
  const clock = useClockStore.getState();
  const demo = useDemoStore.getState();
  const ui = useUiStore.getState();
  switch (cmd.action) {
    case 'advance_one_day': clock.stepDays(1); break;
    case 'jump_next_due': clock.jumpToNextDue(); break;
    case 'show_hindi': ui.setLanguage('hi-IN'); break;
    case 'open_follow_up': window.dispatchEvent(new CustomEvent('jaak:console-tab', { detail: 'queues' })); break;
    case 'show_evidence': window.dispatchEvent(new CustomEvent('jaak:console-tab', { detail: 'evidence' })); break;
    case 'start_demo': demo.start(); break;
    case 'reset': resetDemo(); break;
  }
}

export function OperatorControls() {
  const [toast, setToast] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<OperatorCommand | null>(null);
  const [listening, setListening] = useState(false);
  const demo = useDemoStore();
  const ds = useDataSource();
  const scenarios = useQuery({ queryKey: qk.scenarios, queryFn: ({ signal }) => ds.listScenarios(signal) });
  const surveyScenario = scenarios.data?.find((x) => x.decision === 'survey')?.scenario ?? null;
  const provider = new BrowserVoiceProvider();
  const speechOk = provider.isSpeechSupported('en-IN');

  const handle = (cmd: OperatorCommand | null, raw?: string) => {
    if (!cmd) {
      setToast(raw ? `Not recognised: "${raw}"` : 'Command not recognised');
      return;
    }
    if (cmd.destructive) {
      setConfirm(cmd);
      return;
    }
    setToast(`Command: ${cmd.label}`);
    dispatchOperator(cmd);
  };

  const listen = () => {
    if (!speechOk) {
      setToast('Voice control not available in this browser');
      return;
    }
    setListening(true);
    provider.startStt(
      'en-IN',
      (t) => { handle(matchCommand(t), t); setListening(false); },
      () => setListening(false),
    );
  };

  return (
    <div className={styles.wrap}>
      <button type="button" className={`${styles.mic} ${listening ? styles.on : ''}`} onClick={listen} title="Operator voice control">
        <Mic size={15} /> {listening ? 'Listening…' : 'Voice'}
      </button>
      <button type="button" className={styles.demo} onClick={() => demo.start()} title="Start guided demo">
        <Play size={14} /> Demo
      </button>
      <button
        type="button"
        className={styles.money}
        disabled={!surveyScenario}
        onClick={() => { if (surveyScenario) { setToast('Money moment'); runAll(moneyMomentSteps(surveyScenario)); } }}
        title="Run the money moment"
      >
        <Zap size={14} /> Money moment
      </button>
      <button type="button" className={styles.reset} onClick={() => setConfirm({ action: 'reset', label: 'Reset', destructive: true, phrases: [] })} title="Reset">
        <RotateCcw size={14} />
      </button>

      {toast && (
        <div className={styles.toast} role="status" onAnimationEnd={() => setToast(null)}>
          {toast}
        </div>
      )}
      {confirm && (
        <div className={styles.confirm} role="alertdialog" aria-label="Confirm reset">
          <span>Reset the demo?</span>
          <button type="button" onClick={() => { dispatchOperator(confirm); setConfirm(null); setToast('Reset'); }}>Yes</button>
          <button type="button" onClick={() => setConfirm(null)}>No</button>
        </div>
      )}
    </div>
  );
}
