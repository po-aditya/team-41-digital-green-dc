import type { VoiceItem } from '../data/types';
import styles from './SimulateSpeechChips.module.css';

/** Offline "simulate speech" row: one chip per option (first synonym as label),
 *  plus an "unclear" chip. Clicking sends that exact transcript to the matcher. */
export function SimulateSpeechChips({
  item,
  lang,
  onSay,
}: {
  item: VoiceItem;
  lang: string;
  onSay: (transcript: string) => void;
}) {
  return (
    <div className={styles.row} aria-label="Simulate a spoken answer">
      {Object.entries(item.speech ?? {}).map(([value, synonyms]) => {
        const label = synonyms[0] ?? value;
        return (
          <button key={value} type="button" className={styles.chip} lang={lang} onClick={() => onSay(label)}>
            {label}
          </button>
        );
      })}
      <button type="button" className={`${styles.chip} ${styles.unclear}`} onClick={() => onSay('mmm hmm not sure')}>
        unclear
      </button>
    </div>
  );
}
