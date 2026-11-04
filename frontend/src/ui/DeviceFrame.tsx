import type { ReactNode } from 'react';
import { Signal, Wifi, BatteryFull } from 'lucide-react';
import styles from './DeviceFrame.module.css';

/** CSS-only phone frame: 9:41 status bar + home-indicator pill. */
export function DeviceFrame({ children }: { children: ReactNode }) {
  return (
    <div className={styles.phone}>
      <div className={styles.statusbar}>
        <span className={styles.time}>9:41</span>
        <span className={styles.icons}>
          <Signal size={14} />
          <Wifi size={14} />
          <BatteryFull size={16} />
        </span>
      </div>
      <div className={styles.screen}>{children}</div>
      <div className={styles.home} aria-hidden="true" />
    </div>
  );
}
