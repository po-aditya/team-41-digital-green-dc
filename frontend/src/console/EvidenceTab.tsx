import { useQuery } from '@tanstack/react-query';
import { CheckCircle2 } from 'lucide-react';
import { useDataSource } from '../data/SourceProvider';
import { qk } from '../data/queryKeys';
import { confusionFromCases, primaryReport } from '../evidence/confusionMatrix';
import { RequirementsPanel } from './RequirementsPanel';
import { QueryBoundary } from '../ui/States';
import type { Report } from '../data/types';
import styles from './EvidenceTab.module.css';

const SCHEMAS = ['survey', 'response', 'schedule_handoff', 'no_survey', 'insight', 'bottom_sheet'];
const SCORE_KEYS = [
  'decision_accuracy', 'rule_accuracy', 'survey_recall', 'survey_precision',
  'window_exact', 'channel_match', 'format_ok', 'relevance', 'reference_intent', 'safety',
];

function pct(v: number | boolean | undefined): string {
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v !== 'number') return '—';
  return v <= 1 ? `${(v * 100).toFixed(1)}%` : String(v);
}

export function EvidenceTab() {
  const ds = useDataSource();
  const reports = useQuery({ queryKey: qk.reports, queryFn: ({ signal }) => ds.getReports(signal) });

  return (
    <div className={styles.tab}>
      <QueryBoundary status={reports.status} error={reports.error} data={reports.data} onRetry={() => reports.refetch()} empty={(d) => d.length === 0} emptyLabel="No evaluation reports found.">
        {(reps) => {
          const primary = primaryReport(reps)!;
          const matrix = confusionFromCases(primary.cases);
          return (
            <>
              <Golden reps={reps} primary={primary} />
              <div className={styles.twoCol}>
                <Matrix matrix={matrix} label={primary.name} />
                <Telemetry primary={primary} />
              </div>
              <Hindi reps={reps} />
              <SchemaBadges />
              <RequirementsPanel />
              <OpenQuestions />
              <footer className={styles.footer}>
                Self-reported, simulated answers. Not causal evidence. RCTs remain the verifier.
              </footer>
            </>
          );
        }}
      </QueryBoundary>
    </div>
  );
}

function Golden({ reps, primary }: { reps: Report[]; primary: Report }) {
  return (
    <section className={styles.card}>
      <h3 className={styles.h}>Golden-set evaluation · {primary.golden_cases} cases · {primary.name}</h3>
      <div className={styles.scores}>
        {SCORE_KEYS.map((k) => (
          <div key={k} className={styles.score}>
            <span className={styles.scoreVal}>{pct(primary.scores[k])}</span>
            <span className={styles.scoreKey}>{k}</span>
          </div>
        ))}
      </div>
      <h4 className={styles.sub}>Improvement iterations (v0 → v4)</h4>
      <table className={styles.iter}>
        <thead><tr><th>Run</th><th>Decision</th><th>Rule</th><th>Relevance</th><th>Scheduled</th></tr></thead>
        <tbody>
          {reps.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td>{pct(r.scores.decision_accuracy)}</td>
              <td>{pct(r.scores.rule_accuracy)}</td>
              <td>{pct(r.scores.relevance)}</td>
              <td>{r.status_counts ? `${r.status_counts.scheduled}/${r.golden_cases}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Matrix({ matrix, label }: { matrix: ReturnType<typeof confusionFromCases>; label: string }) {
  return (
    <section className={styles.card}>
      <h3 className={styles.h}>Confusion matrix · {label}</h3>
      {matrix ? (
        <>
          <div className={styles.matrix}>
            <div className={`${styles.cell} ${styles.tp}`}><b>{matrix.tp}</b><span>TP</span></div>
            <div className={`${styles.cell} ${styles.fp}`}><b>{matrix.fp}</b><span>FP</span></div>
            <div className={`${styles.cell} ${styles.fn}`}><b>{matrix.fn}</b><span>FN</span></div>
            <div className={`${styles.cell} ${styles.tn}`}><b>{matrix.tn}</b><span>TN</span></div>
          </div>
          <p className={styles.mstats}>
            precision {(matrix.precision * 100).toFixed(1)}% · recall {(matrix.recall * 100).toFixed(1)}% · F1 {(matrix.f1 * 100).toFixed(1)}%
          </p>
        </>
      ) : (
        <p className={styles.muted}>Not shown here — the report cases do not expose the per-case decision booleans.</p>
      )}
    </section>
  );
}

function Telemetry({ primary }: { primary: Report }) {
  const s = primary.speed;
  if (!s) {
    return (
      <section className={styles.card}>
        <h3 className={styles.h}>Telemetry</h3>
        <p className={styles.muted}>No telemetry recorded for {primary.name} (rules-only baseline).</p>
      </section>
    );
  }
  return (
    <section className={styles.card}>
      <h3 className={styles.h}>Telemetry</h3>
      <dl className={styles.kv}>
        <div><dt>Seconds / survey (avg)</dt><dd>{s.seconds_per_survey_avg?.toFixed(1) ?? '—'}</dd></div>
        <div><dt>Seconds / survey (p95)</dt><dd>{s.seconds_per_survey_p95?.toFixed(1) ?? '—'}</dd></div>
        <div><dt>Batch wall seconds</dt><dd>{s.batch_wall_seconds?.toFixed(0) ?? '—'}</dd></div>
        <div><dt>Input tokens</dt><dd>{s.agent_usage?.input_tokens?.toLocaleString() ?? '—'}</dd></div>
        <div><dt>Output tokens</dt><dd>{s.agent_usage?.output_tokens?.toLocaleString() ?? '—'}</dd></div>
        <div><dt>Estimated cost</dt><dd className={styles.muted}>not evidenced (cost_usd is null)</dd></div>
      </dl>
    </section>
  );
}

function Hindi({ reps }: { reps: Report[] }) {
  const hi = reps.find((r) => r.language === 'hi-IN');
  return (
    <section className={styles.card}>
      <h3 className={styles.h}>Hindi (hi-IN)</h3>
      {hi ? (
        <p>
          {hi.status_counts ? `${hi.status_counts.scheduled} of ${hi.golden_cases}` : `${hi.golden_cases}`} cases scheduled in the Hindi run;
          format_ok {pct(hi.scores.format_ok)}, safety {pct(hi.scores.safety)}. Hindi output needs native-speaker review.
        </p>
      ) : (
        <p className={styles.muted}>No Hindi report present.</p>
      )}
    </section>
  );
}

function SchemaBadges() {
  return (
    <section className={styles.card}>
      <h3 className={styles.h}>Schema validation</h3>
      <div className={styles.badges}>
        {SCHEMAS.map((s) => (
          <span key={s} className={styles.badge}>
            <CheckCircle2 size={14} aria-hidden="true" /> {s}.schema.json
          </span>
        ))}
      </div>
      <p className={styles.muted}>Every generated survey, response and hand-off validates against these six schemas (fixture validation test).</p>
    </section>
  );
}

function OpenQuestions() {
  const qs = [
    'Should a batch/broadcast or simulated-clock endpoint be added to the backend later?',
    'Will the real dataset include human-queue and quarantine states?',
    'Who owns native-speaker review of the Hindi UI chrome?',
    'Confirm the authoritative source for the golden confusion matrix.',
    'Should taps be persisted when no flow exists?',
  ];
  return (
    <section className={styles.card}>
      <h3 className={styles.h}>Open questions for Digital Green</h3>
      <p className={styles.muted}>CONTRACT_QUESTIONS.md is absent from this repository; these come from the spec.</p>
      <ul className={styles.oq}>{qs.map((q) => <li key={q}>{q}</li>)}</ul>
    </section>
  );
}
