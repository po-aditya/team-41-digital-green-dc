import styles from './OptionRow.module.css';

/** Full-width rounded answer row with a circular radio on the left. */
export function OptionRow({
  label,
  selected,
  onSelect,
  lang,
}: {
  label: string;
  selected: boolean;
  onSelect: () => void;
  lang?: string;
}) {
  return (
    <button
      type="button"
      className={`${styles.row} ${selected ? styles.selected : ''}`}
      aria-pressed={selected}
      onClick={onSelect}
      lang={lang}
    >
      <span className={`${styles.radio} ${selected ? styles.radioOn : ''}`} aria-hidden="true">
        {selected && <span className={styles.dot} />}
      </span>
      <span className={styles.label}>{label}</span>
    </button>
  );
}
