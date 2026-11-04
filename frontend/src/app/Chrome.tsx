import { ShieldAlert, Database, Cpu, WifiOff } from 'lucide-react';
import { useUiStore } from '../state/uiStore';
import { Chip } from '../ui/Chip';
import type { SourceKind } from '../data/DataSource';
import styles from './Chrome.module.css';

const SOURCE_LABEL: Record<SourceKind, string> = {
  live: 'Live API',
  pack: 'Pack scenarios',
  fixture: 'Fixtures',
};

/** Persistent, non-dismissable synthetic badge (safety steering). */
export function SyntheticBadge() {
  return (
    <span className={styles.synthetic} title="All data is synthetic; delivery is simulated.">
      <ShieldAlert size={14} aria-hidden="true" />
      SYNTHETIC DATA · SIMULATED DELIVERY
    </span>
  );
}

export function DataSourceChip() {
  const kind = useUiStore((s) => s.sourceKind);
  const setSource = useUiStore((s) => s.setSource);
  return (
    <label className={styles.selectChip} title="Active data source">
      <Database size={14} aria-hidden="true" />
      <span className="visually-hidden">Data source</span>
      <select value={kind} onChange={(e) => setSource(e.target.value as SourceKind)}>
        {(['fixture', 'pack', 'live'] as SourceKind[]).map((k) => (
          <option key={k} value={k}>
            {SOURCE_LABEL[k]}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Generation provider. Offline sources run the template provider; never Bedrock. */
export function ProvenanceChip() {
  const kind = useUiStore((s) => s.sourceKind);
  const label = kind === 'live' ? 'provider: template, offline' : 'template, offline';
  return (
    <Chip tone="neutral" icon={<Cpu size={14} />} title="Survey generation provider">
      {label}
    </Chip>
  );
}

export function LanguageToggle() {
  const language = useUiStore((s) => s.language);
  const setLanguage = useUiStore((s) => s.setLanguage);
  return (
    <div className={styles.langToggle} role="group" aria-label="Farmer view language">
      <button
        type="button"
        className={language === 'en-IN' ? styles.langOn : ''}
        aria-pressed={language === 'en-IN'}
        onClick={() => setLanguage('en-IN')}
      >
        EN
      </button>
      <button
        type="button"
        className={language === 'hi-IN' ? styles.langOn : ''}
        aria-pressed={language === 'hi-IN'}
        onClick={() => setLanguage('hi-IN')}
        lang="hi-IN"
      >
        हिन्दी
      </button>
    </div>
  );
}

export function FallbackBanner() {
  const fellBack = useUiStore((s) => s.fellBackToFixtures);
  const dismiss = useUiStore((s) => s.dismissFallbackBanner);
  if (!fellBack) return null;
  return (
    <div className={styles.banner} role="alert">
      <WifiOff size={16} aria-hidden="true" />
      <span>Live API unreachable — showing fixtures so the demo continues.</span>
      <button type="button" onClick={dismiss}>
        Dismiss
      </button>
    </div>
  );
}
