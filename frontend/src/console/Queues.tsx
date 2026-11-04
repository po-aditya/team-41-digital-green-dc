import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, UserCog } from 'lucide-react';
import { useDataSource } from '../data/SourceProvider';
import { useResponsesStore } from '../state/responsesStore';
import { qk } from '../data/queryKeys';
import { Chip } from '../ui/Chip';
import { QueryBoundary } from '../ui/States';
import styles from './Queues.module.css';

const REASON_TONE: Record<string, 'amber' | 'critical' | 'neutral'> = {
  advice_did_not_work: 'amber',
  crop_or_animal_damaged: 'critical',
  could_not_reach_expert: 'amber',
  could_not_get_input: 'neutral',
};

export function Queues() {
  const ds = useDataSource();
  const [tab, setTab] = useState<'followups' | 'human'>('followups');
  const followUps = useQuery({ queryKey: qk.followUps, queryFn: ({ signal }) => ds.getFollowUps(signal) });
  const localFollowUps = useResponsesStore((st) => st.followUps);
  const human = useQuery({ queryKey: qk.humanQueue, queryFn: ({ signal }) => ds.getHumanQueue(signal) });
  const [humanStatus, setHumanStatus] = useState<Record<string, string>>({});

  // Backend follow-ups plus any created live this session (negative answers).
  const backend = followUps.data ?? [];
  const extra = localFollowUps.filter((l) => !backend.some((b) => b.survey_id === l.survey_id));
  const mergedFollowUps = [...extra, ...backend];

  return (
    <div className={styles.card}>
      <div className={styles.tabs} role="tablist">
        <button role="tab" aria-selected={tab === 'followups'} onClick={() => setTab('followups')}>
          Follow-up queue
        </button>
        <button role="tab" aria-selected={tab === 'human'} onClick={() => setTab('human')}>
          Human queue
        </button>
      </div>

      {tab === 'followups' ? (
        <QueryBoundary status={followUps.status} error={followUps.error} data={mergedFollowUps} onRetry={() => followUps.refetch()} empty={(d) => d.length === 0} emptyLabel="No follow-ups yet.">
          {(items) => (
            <ul className={styles.list}>
              {items.map((f) => (
                <li key={f.survey_id} className={styles.row}>
                  <span className={styles.sid}>{f.survey_id}</span>
                  <span className={styles.farmer}>{f.farmer_id}</span>
                  <span className={styles.reasons}>
                    {f.reasons.map((r) => (
                      <Chip key={r} tone={REASON_TONE[r] ?? 'amber'} icon={<AlertTriangle size={12} />}>{r}</Chip>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </QueryBoundary>
      ) : (
        <>
          <p className={styles.sim}>simulated reviewer view · no backend endpoint · acknowledgement is a fixed template, never new advice</p>
          <QueryBoundary status={human.status} error={human.error} data={human.data} onRetry={() => human.refetch()} empty={(d) => d.length === 0} emptyLabel="No critical insights.">
            {(items) => (
              <ul className={styles.list}>
                {items.map((h) => {
                  const status = humanStatus[h.insight.insight_id] ?? h.status;
                  return (
                    <li key={h.insight.insight_id} className={styles.row}>
                      <UserCog size={16} aria-hidden="true" />
                      <span className={styles.sid}>{h.insight.insight_id}</span>
                      <span className={styles.farmer} lang={h.insight.conversation_language}>{h.insight.query_summary}</span>
                      <select
                        aria-label={`Status for ${h.insight.insight_id}`}
                        value={status}
                        onChange={(e) => setHumanStatus((s) => ({ ...s, [h.insight.insight_id]: e.target.value }))}
                      >
                        <option value="new">new</option>
                        <option value="in_review">in review</option>
                        <option value="resolved">resolved</option>
                      </select>
                    </li>
                  );
                })}
              </ul>
            )}
          </QueryBoundary>
          <p className={styles.ack}>
            Acknowledgement (fixed template): "Thank you. A FarmerChat team member will follow up with you."
          </p>
        </>
      )}
    </div>
  );
}
