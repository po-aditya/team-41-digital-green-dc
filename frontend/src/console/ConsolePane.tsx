import { useEffect, useState } from 'react';
import { ClockPanel } from './ClockPanel';
import { PipelineStrip } from './PipelineStrip';
import { SurveyTimeline } from './SurveyTimeline';
import { SurveyDrawer } from './SurveyDrawer';
import { Queues } from './Queues';
import { EvidenceTab } from './EvidenceTab';
import type { TimelineRow } from '../data/DataSource';
import styles from './ConsolePane.module.css';

type Tab = 'console' | 'queues' | 'evidence';

export function ConsolePane() {
  const [tab, setTab] = useState<Tab>('console');
  const [selected, setSelected] = useState<TimelineRow | null>(null);

  // Operator voice commands (and the demo director) can switch tabs by
  // dispatching a `jaak:console-tab` CustomEvent on window.
  useEffect(() => {
    const onTab = (e: Event) => {
      const detail = (e as CustomEvent).detail as Tab | undefined;
      if (detail === 'console' || detail === 'queues' || detail === 'evidence') {
        setTab(detail);
      }
    };
    window.addEventListener('jaak:console-tab', onTab as EventListener);
    return () => window.removeEventListener('jaak:console-tab', onTab as EventListener);
  }, []);

  return (
    <div className={styles.console}>
      <div className={styles.tabs} role="tablist" aria-label="Console view">
        <button role="tab" aria-selected={tab === 'console'} onClick={() => setTab('console')}>Pipeline & timeline</button>
        <button role="tab" aria-selected={tab === 'queues'} onClick={() => setTab('queues')}>Queues</button>
        <button role="tab" aria-selected={tab === 'evidence'} onClick={() => setTab('evidence')}>Evidence</button>
      </div>

      {tab === 'console' && (
        <>
          <ClockPanel />
          <PipelineStrip />
          <div className={styles.grid}>
            <SurveyTimeline onSelect={setSelected} selectedId={selected?.survey_id ?? null} />
            {selected && <SurveyDrawer row={selected} onClose={() => setSelected(null)} />}
          </div>
        </>
      )}
      {tab === 'queues' && <Queues />}
      {tab === 'evidence' && <EvidenceTab />}
    </div>
  );
}
