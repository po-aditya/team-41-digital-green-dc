import styles from './Backdrop.module.css';

/** Soft pastel green gradient with large blurred organic blobs. */
export function Backdrop() {
  return (
    <div className={styles.backdrop} aria-hidden="true">
      <span className={`${styles.blob} ${styles.b1}`} />
      <span className={`${styles.blob} ${styles.b2}`} />
      <span className={`${styles.blob} ${styles.b3}`} />
    </div>
  );
}
