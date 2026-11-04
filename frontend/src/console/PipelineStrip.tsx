import { useQuery } from '@tanstack/react-query';
import { useDataSource } from '../data/SourceProvider';
import { qk } from '../data/queryKeys';
import { SegmentedProgress } from '../ui/SegmentedProgress';
import styles from './PipelineStrip.module.css';

const STAGES = ['Ingest', 'Decide', 'Generate', 'Schedule', 'Deliver', 'Answer'] as const;

export function PipelineStrip() {
  const ds = useDataSource();
  const stats = useQuery({ queryKey: qk.ingestStats, queryFn: ({ signal }) => ds.getIngestStats(signal) });
  const scenarios = useQuery({ queryKey: qk.scenarios, queryFn: ({ signal }) => ds.listScenarios(signal) });

  const scheduled = scenarios.data?.filter((s) => s.decision === 'survey').length ?? 0;
  const noSurvey = scenarios.data?.filter((s) => s.decision === 'no_survey').length ?? 0;

  return (
    <div className={styles.strip}>
      <div className={styles.header}>
        <span className={styles.title}>Pipeline</span>
        <span className={styles.sim}>batch counts simulated in UI; Generate is live via POST /v1/surveys</span>
      </div>
      <SegmentedProgress total={STAGES.length} filled={STAGES.length} labels={[...STAGES]} ariaLabel="Pipeline stages" />
      <div className={styles.stages}>
        {STAGES.map((s) => (
          <span key={s} className={styles.stage}>{s}</span>
        ))}
      </div>
      <dl className={styles.counts}>
        <div><dt>Ingested</dt><dd>{stats.data?.total?.toLocaleString() ?? '…'}</dd></div>
        <div><dt>Valid</dt><dd>{stats.data?.valid?.toLocaleString() ?? '…'}</dd></div>
        <div><dt>Quarantined</dt><dd>{stats.data?.quarantined?.toLocaleString() ?? '…'}</dd></div>
        <div><dt>Scenarios surveyed</dt><dd>{scheduled}</dd></div>
        <div><dt>No-survey</dt><dd>{noSurvey}</dd></div>
      </dl>
    </div>
  );
}
