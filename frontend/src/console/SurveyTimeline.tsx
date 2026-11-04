import { useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useDataSource } from '../data/SourceProvider';
import { qk } from '../data/queryKeys';
import { chipFor } from '../state/statusChips';
import { Chip } from '../ui/Chip';
import { QueryBoundary } from '../ui/States';
import type { TimelineFilter, TimelineRow } from '../data/DataSource';
import styles from './SurveyTimeline.module.css';

export function SurveyTimeline({
  onSelect,
  selectedId,
}: {
  onSelect: (row: TimelineRow) => void;
  selectedId: string | null;
}) {
  const ds = useDataSource();
  const [filter, setFilter] = useState<TimelineFilter>({});
  const q = useQuery({
    queryKey: qk.timeline(filter, 0),
    queryFn: ({ signal }) => ds.listTimeline(filter, { offset: 0, limit: 200 }, signal),
  });

  const rows = useMemo(() => q.data?.rows ?? [], [q.data]);
  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 54,
    overscan: 8,
  });

  const crops = useMemo(() => unique(rows.map((r) => r.crop).filter(Boolean) as string[]), [rows]);

  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span className={styles.title}>Survey timeline</span>
        <span className={styles.count}>{q.data?.total ?? 0} rows</span>
      </div>

      <div className={styles.filters}>
        <select aria-label="Filter by language" value={filter.language ?? ''} onChange={(e) => setFilter((f) => ({ ...f, language: e.target.value ? (e.target.value as TimelineFilter['language']) : undefined }))}>
          <option value="">All languages</option>
          <option value="en-IN">en-IN</option>
          <option value="hi-IN">hi-IN</option>
        </select>
        <select aria-label="Filter by crop" value={filter.crop ?? ''} onChange={(e) => setFilter((f) => ({ ...f, crop: e.target.value || undefined }))}>
          <option value="">All crops</option>
          {crops.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select aria-label="Filter by state" value={filter.state ?? ''} onChange={(e) => setFilter((f) => ({ ...f, state: (e.target.value || undefined) as TimelineFilter['state'] }))}>
          <option value="">All states</option>
          {['scheduled', 'deferred_by_cap', 'expired', 'window_truncated_by_season_end', 'no_survey'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      <QueryBoundary status={q.status} error={q.error} data={q.data} onRetry={() => q.refetch()} empty={(d) => d.rows.length === 0} emptyLabel="No surveys match.">
        {() => (
          <div ref={parentRef} className={styles.scroll}>
            <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
              {rowVirtualizer.getVirtualItems().map((vi) => {
                const row = rows[vi.index]!;
                const spec = chipFor(row.state);
                const Icon = spec.icon;
                return (
                  <button
                    key={row.survey_id + row.language}
                    type="button"
                    className={`${styles.row} ${selectedId === row.survey_id ? styles.selected : ''}`}
                    style={{ position: 'absolute', top: vi.start, height: vi.size, width: '100%' }}
                    onClick={() => onSelect(row)}
                  >
                    <span className={styles.sid}>{row.survey_id}</span>
                    <span className={styles.meta}>{row.crop ?? '—'} · {row.topic} · {row.language}</span>
                    <Chip tone={spec.tone} icon={<Icon size={12} />}>{spec.label}</Chip>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </QueryBoundary>
    </div>
  );
}

function unique<T>(a: T[]): T[] {
  return [...new Set(a)];
}
