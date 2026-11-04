import styles from './SegmentedProgress.module.css';

/** Segmented pill progress bar: one segment per step. Reused by the phone sheet
 *  and the console pipeline strip. */
export function SegmentedProgress({
  total,
  filled,
  labels,
  ariaLabel,
}: {
  total: number;
  filled: number;
  labels?: string[];
  ariaLabel?: string;
}) {
  return (
    <div
      className={styles.track}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={filled}
      aria-label={ariaLabel}
    >
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`${styles.seg} ${i < filled ? styles.on : ''}`}
          title={labels?.[i]}
        />
      ))}
    </div>
  );
}
