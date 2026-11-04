import { useQuery } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { useDataSource } from '../data/SourceProvider';
import { qk } from '../data/queryKeys';
import { explainDecision } from '../state/rulesExplain';
import { chipFor } from '../state/statusChips';
import { Chip } from '../ui/Chip';
import { QueryBoundary } from '../ui/States';
import type { TimelineRow } from '../data/DataSource';
import styles from './SurveyDrawer.module.css';

export function SurveyDrawer({ row, onClose }: { row: TimelineRow; onClose: () => void }) {
  const ds = useDataSource();
  const detail = useQuery({
    queryKey: qk.scenario(row.scenario.replace(/^seed-/, '1-mustard-aphid-spray')),
    queryFn: ({ signal }) => ds.getScenario(row.scenario.startsWith('seed-') ? '1-mustard-aphid-spray' : row.scenario, signal),
  });
  const rules = useQuery({
    queryKey: ['rules'],
    queryFn: async () => (await fetch('/fixtures/rules/rules.json')).json(),
  });

  const spec = chipFor(row.state);
  const Icon = spec.icon;

  return (
    <aside className={styles.drawer} aria-label="Survey detail">
      <div className={styles.head}>
        <div>
          <span className={styles.sid}>{row.survey_id}</span>
          <Chip tone={spec.tone} icon={<Icon size={12} />}>{spec.label}</Chip>
        </div>
        <button type="button" className={styles.close} aria-label="Close drawer" onClick={onClose}>
          <X size={18} />
        </button>
      </div>

      <QueryBoundary status={detail.status} error={detail.error} data={detail.data} onRetry={() => detail.refetch()}>
        {(d) => {
          const insight = d.insight;
          const decision = d.generate?.decision;
          const expl = decision ? explainDecision(decision, rules.data ?? null, insight.resolution_type) : null;
          const survey = d.surveys[row.language] ?? d.surveys['en-IN'] ?? d.surveys['hi-IN'];
          return (
            <div className={styles.body}>
              <Section title="Source insight">
                <Row k="Insight" v={insight.insight_id} />
                <Row k="Query" v={insight.query_summary} />
                <Row k="Advice" v={insight.advice_summary} />
                <Row k="Crop / animal" v={insight.asset.name ?? '—'} />
                <Row k="Severity" v={insight.severity} />
                <Row k="Resolution" v={insight.resolution_type} />
                <Row k="Action window (days)" v={String(insight.action_window_days ?? '—')} />
              </Section>

              <Section title="Decision">
                {expl ? (
                  <>
                    <Row k="Rule" v={`${expl.rule} · ${expl.reasonCode}`} />
                    <Row k="Reason" v={expl.reason} />
                    {expl.asks && <Row k="Survey checks" v={expl.asks} />}
                    <Row k="Outcome" v={expl.survey ? 'survey scheduled' : 'no survey'} />
                  </>
                ) : (
                  <p className={styles.muted}>No captured decision for this row.</p>
                )}
                {d.noSurvey && <Row k="No-survey code" v={`${d.noSurvey.reason_code}`} />}
              </Section>

              {survey && (
                <Section title="Survey">
                  {survey.items.map((it) => (
                    <div key={it.item_id} className={styles.item}>
                      <p className={styles.q} lang={survey.language}>{it.prompt}</p>
                      <ul className={styles.opts}>
                        {(it.options ?? []).map((o) => (
                          <li key={o.value} lang={survey.language}>
                            {o.label}
                            {o.follow_up && <span className={styles.fu}> → {o.follow_up}</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  {survey.self_eval && (
                    <Row k="Self-eval" v={`schema_valid=${survey.self_eval.schema_valid}${survey.self_eval.relevance_score != null ? `, relevance=${survey.self_eval.relevance_score}` : ''}`} />
                  )}
                </Section>
              )}

              {d.handoff && (
                <Section title="Schedule & hand-off">
                  <Row k="Send window" v={`${d.handoff.send_window.not_before} → ${d.handoff.send_window.not_after}`} />
                  <Row k="Send hours" v={`${d.handoff.send_hours.from}–${d.handoff.send_hours.to}`} />
                  <Row k="Channel order" v={d.handoff.channel_order.map((c) => c.channel).join(' → ')} />
                  <Row k="Priority" v={d.handoff.priority} />
                  <Row k="Frequency cap" v={`${d.handoff.frequency_cap.max_surveys}/${d.handoff.frequency_cap.window_days}d`} />
                  <Row k="Expires" v={d.handoff.expires_at} />
                  <Row k="Flow id" v={d.handoff.farmerchat_flow.flow_id} />
                </Section>
              )}

              <Section title="Provenance">
                <Row k="Generation provider" v="template, offline (not Bedrock)" />
                <Row k="Data source" v={ds.kind} />
              </Section>
            </div>
          );
        }}
      </QueryBoundary>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>{title}</h3>
      {children}
    </section>
  );
}
function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className={styles.kv}>
      <span className={styles.k}>{k}</span>
      <span className={styles.v}>{v}</span>
    </div>
  );
}
