import { useEffect, useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { makeQueryClient } from '../data/client';
import { SourceProvider } from '../data/SourceProvider';
import { Backdrop } from '../ui/Backdrop';
import {
  DataSourceChip,
  FallbackBanner,
  LanguageToggle,
  ProvenanceChip,
  SyntheticBadge,
} from './Chrome';
import { ConsolePane } from '../console/ConsolePane';
import { PhonePane } from '../phone/PhonePane';
import { OperatorControls } from '../demo/OperatorControls';
import { DemoNarration } from '../demo/DemoNarration';
import styles from './App.module.css';

const queryClient = makeQueryClient();

function useNarrow(breakpoint = 1100) {
  const [narrow, setNarrow] = useState(
    typeof window !== 'undefined' ? window.innerWidth < breakpoint : false,
  );
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < breakpoint);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [breakpoint]);
  return narrow;
}

export function App() {
  const narrow = useNarrow();
  const [tab, setTab] = useState<'console' | 'phone'>('console');

  return (
    <QueryClientProvider client={queryClient}>
      <SourceProvider>
        <Backdrop />
        <div className={styles.app}>
          <header className={styles.topbar}>
            <div className={styles.brand}>
              <span className={styles.logo}>FarmerChat</span>
              <span className={styles.sub}>MEL Survey Agent</span>
            </div>
            <div className={styles.chips}>
              <SyntheticBadge />
              <DataSourceChip />
              <ProvenanceChip />
              <LanguageToggle />
              <OperatorControls />
            </div>
          </header>
          <FallbackBanner />

          {narrow && (
            <div className={styles.tabs} role="tablist">
              <button role="tab" aria-selected={tab === 'console'} onClick={() => setTab('console')}>
                Console
              </button>
              <button role="tab" aria-selected={tab === 'phone'} onClick={() => setTab('phone')}>
                Phone
              </button>
            </div>
          )}

          <main className={narrow ? styles.stacked : styles.split}>
            {(!narrow || tab === 'console') && (
              <section className={styles.console} aria-label="Operator console">
                <ConsolePane />
              </section>
            )}
            {(!narrow || tab === 'phone') && (
              <section className={styles.phone} aria-label="Farmer phone simulator">
                <PhonePane />
              </section>
            )}
          </main>

          <DemoNarration />
        </div>
      </SourceProvider>
    </QueryClientProvider>
  );
}
