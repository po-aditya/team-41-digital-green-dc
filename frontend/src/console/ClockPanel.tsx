import { useEffect } from 'react';
import { Clock, ChevronRight, FastForward } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useDataSource } from '../data/SourceProvider';
import { qk } from '../data/queryKeys';
import { useClockStore, SEASON_START, SEASON_END } from '../state/clockStore';
import type { ClockModel } from '../state/clockDiff';
import { Chip } from '../ui/Chip';
import { LiveRegion } from '../ui/LiveRegion';
import styles from './ClockPanel.module.css';

function fmt(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  });
}

export function ClockPanel() {
  const ds = useDataSource();
  const { nowIso, lastDiff, setModel, stepHours, stepDays, jumpToNextDue } = useClockStore();

  const timeline = useQuery({
    queryKey: qk.timeline({}, 0),
    queryFn: ({ signal }) => ds.listTimeline({}, { offset: 0, limit: 200 }, signal),
  });

  useEffect(() => {
    if (!timeline.data) return;
    const m: ClockModel = {
      seasonEnd: SEASON_END,
      cap: { max_surveys: 1, window_days: 7, exempt_priority: ['high'] },
      surveys: timeline.data.rows
        .filter((r) => r.state !== 'no_survey')
        .map((r) => ({
          survey_id: r.survey_id,
          farmer_id: r.farmer_id,
          not_before: r.not_before,
          not_after: r.not_after,
          expires_at: r.expires_at,
          priority: 'normal' as const,
        })),
    };
    setModel(m);
  }, [timeline.data, setModel]);

  const span = Date.parse(SEASON_END) - Date.parse(SEASON_START);
  const pos = Math.max(0, Math.min(1, (Date.parse(nowIso) - Date.parse(SEASON_START)) / span));

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <Clock size={16} aria-hidden="true" />
        <span className={styles.now}>{fmt(nowIso)} IST</span>
        <span className={styles.sim}>simulated in UI, no backend endpoint</span>
      </div>

      <div className={styles.scrubWrap}>
        <input
          type="range"
          min={0}
          max={1000}
          value={Math.round(pos * 1000)}
          aria-label="Season scrubber (Nov to Mar)"
          onChange={(e) => {
            const frac = Number(e.target.value) / 1000;
            const iso = new Date(Date.parse(SEASON_START) + frac * span).toISOString().replace('Z', '+05:30');
            useClockStore.getState().setNow(iso);
          }}
          className={styles.scrub}
        />
        <div className={styles.scrubLabels}><span>Nov</span><span>Mar</span></div>
      </div>

      <div className={styles.steps}>
        <button type="button" onClick={() => stepHours(1)}>+1h</button>
        <button type="button" onClick={() => stepDays(1)}>+1 day</button>
        <button type="button" onClick={() => stepDays(7)}>+1 week</button>
        <button type="button" className={styles.jump} onClick={jumpToNextDue}>
          <FastForward size={14} /> Next due
        </button>
      </div>

      {lastDiff && (
        <div className={styles.diff} aria-label="Advance result">
          <Chip tone="green" icon={<ChevronRight size={12} />}>{lastDiff.delivered.length} delivered</Chip>
          <Chip tone="amber">{lastDiff.deferredByCap.length} deferred (cap)</Chip>
          <Chip tone="amber">{lastDiff.expired.length} expired</Chip>
          <Chip tone="neutral">{lastDiff.blockedUnsafe} blocked unsafe</Chip>
        </div>
      )}
      <LiveRegion
        message={
          lastDiff
            ? `Clock ${fmt(nowIso)}. ${lastDiff.delivered.length} delivered, ${lastDiff.deferredByCap.length} deferred, ${lastDiff.expired.length} expired.`
            : ''
        }
      />
    </div>
  );
}
