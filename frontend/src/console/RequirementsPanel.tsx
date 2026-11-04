import { CheckCircle2, CircleDashed, MinusCircle } from 'lucide-react';
import styles from './RequirementsPanel.module.css';

type Status = 'evidenced' | 'partly' | 'not_shown';

interface Req {
  item: string;
  category: string;
  how: string;
  status: Status;
}

// Mirrors the Requirements Traceability table in requirements.md. Status is set
// honestly against THIS repo; "not_shown" = the brief cites it but the repo lacks it.
const ROWS: Req[] = [
  { item: 'Insight ingestion', category: 'Must', how: 'Pipeline Ingest: 6,999 insights, 723 quarantined (insights.jsonl)', status: 'evidenced' },
  { item: 'Survey generation', category: 'Must', how: 'Generate via POST /v1/surveys; drawer shows the returned survey', status: 'evidenced' },
  { item: 'Survey JSON contract', category: 'Must', how: 'Six schema badges; fixtures validated against json/schemas', status: 'evidenced' },
  { item: 'Self-evaluation', category: 'Must', how: 'Drawer self-eval (schema_valid, relevance) from the generate result', status: 'evidenced' },
  { item: 'Evaluation harness (golden)', category: 'Must', how: 'reports v0..v4 scores + status_counts over 150 cases', status: 'evidenced' },
  { item: 'Scheduler', category: 'Must', how: 'Drawer send window + channel order + cap + expiry from schedule_handoff', status: 'evidenced' },
  { item: 'Broadcaster + simulated app', category: 'Should', how: 'Phone renders per render/*.json; batch broadcast over HTTP has no endpoint', status: 'partly' },
  { item: 'Hindi (hi-IN)', category: 'Should', how: 'hi-IN surveys/renders verbatim; v4 report is Hindi', status: 'evidenced' },
  { item: 'Telemetry', category: 'Should', how: 'reports.speed latency + tokens; cost = not evidenced (cost_usd null)', status: 'partly' },
  { item: 'Response write-back', category: 'Exploratory', how: 'Tap persists via POST .../responses when a flow exists; else simulated', status: 'partly' },
  { item: 'Negative-outcome follow-up', category: 'Exploratory', how: 'Negative answer -> follow-up case; GET /v1/follow-ups queue', status: 'evidenced' },
  { item: 'Alternative channels', category: 'Exploratory', how: 'App/Web/WhatsApp/Telegram/Voice render from the pack', status: 'evidenced' },
  { item: 'Clock / broadcast diffs / stats / human queue', category: 'No endpoint', how: 'Simulated in UI, labelled; no backend endpoint in this repo', status: 'partly' },
  { item: 'Confusion matrix (exact brief numbers)', category: 'Derived', how: 'Computed from report cases (expected vs agent survey); brief TP/FP figures not in repo', status: 'evidenced' },
  { item: 'Cost per survey', category: 'Not in repo', how: 'cost_usd is null in every report', status: 'not_shown' },
  { item: 'Real farmer delivery / production / live weather', category: 'Out of scope', how: 'Never claimed; synthetic badge + honesty footer', status: 'not_shown' },
  { item: 'DoD: six Must Haves working', category: 'DoD', how: 'Ingest, Generate, contract, self-eval, harness, scheduler', status: 'evidenced' },
  { item: 'DoD: golden scores + improvement iteration', category: 'DoD', how: 'v0 -> v4 iterations shown with per-metric scores', status: 'evidenced' },
  { item: 'DoD: invalid/low-scoring NOT scheduled', category: 'DoD', how: 'status_counts (no_survey/writer_skipped/rejected); scenario 6', status: 'evidenced' },
  { item: 'DoD: validates vs six schemas', category: 'DoD', how: 'Six schema badges; fixture validation test', status: 'evidenced' },
];

const ICON: Record<Status, typeof CheckCircle2> = {
  evidenced: CheckCircle2,
  partly: CircleDashed,
  not_shown: MinusCircle,
};
const LABEL: Record<Status, string> = {
  evidenced: 'Evidenced',
  partly: 'Partly',
  not_shown: 'Not shown here',
};
const TONE: Record<Status, string> = {
  evidenced: styles.evidenced ?? '',
  partly: styles.partly ?? '',
  not_shown: styles.notShown ?? '',
};

export function RequirementsPanel() {
  return (
    <div className={styles.panel}>
      <h3 className={styles.h}>Requirements traceability</h3>
      <table className={styles.table}>
        <thead>
          <tr><th>Item</th><th>Category</th><th>How the UI shows it</th><th>Status</th></tr>
        </thead>
        <tbody>
          {ROWS.map((r) => {
            const Icon = ICON[r.status];
            return (
              <tr key={r.item}>
                <td className={styles.item}>{r.item}</td>
                <td className={styles.cat}>{r.category}</td>
                <td className={styles.how}>{r.how}</td>
                <td className={`${styles.status} ${TONE[r.status]}`}>
                  <Icon size={14} aria-hidden="true" /> {LABEL[r.status]}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export const REQUIREMENT_ROWS = ROWS;
