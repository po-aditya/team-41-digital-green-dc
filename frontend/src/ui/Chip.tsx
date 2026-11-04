import type { ReactNode } from 'react';
import styles from './Chip.module.css';

export type ChipTone = 'neutral' | 'green' | 'amber' | 'critical';

/** A pill chip. State is always icon + text label, never colour alone. */
export function Chip({
  tone = 'neutral',
  icon,
  children,
  title,
}: {
  tone?: ChipTone;
  icon?: ReactNode;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`${styles.chip} ${styles[tone]}`} title={title}>
      {icon && <span className={styles.icon} aria-hidden="true">{icon}</span>}
      <span>{children}</span>
    </span>
  );
}
