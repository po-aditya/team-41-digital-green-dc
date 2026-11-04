import { useEffect } from 'react';
import { X } from 'lucide-react';
import { DEMO_STEPS, useDemoStore } from '../state/demoStore';
import { LiveRegion } from '../ui/LiveRegion';
import styles from './DemoNarration.module.css';

/** Guided narration overlay. Space = next, Escape = exit. */
export function DemoNarration() {
  const { active, index, next, prev, exit } = useDemoStore();

  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === ' ') { e.preventDefault(); next(); }
      else if (e.key === 'Escape') exit();
      else if (e.key === 'ArrowLeft') prev();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, next, prev, exit]);

  if (!active) return null;
  const step = DEMO_STEPS[index]!;
  return (
    <div className={styles.bar} role="region" aria-label="Demo narration">
      <LiveRegion message={`${step.at} ${step.caption}`} />
      <span className={styles.at}>{step.at}</span>
      <p className={styles.caption}>{step.caption}</p>
      <div className={styles.controls}>
        <span className={styles.progress}>{index + 1}/{DEMO_STEPS.length}</span>
        <button type="button" onClick={prev} disabled={index === 0}>Back</button>
        <button type="button" onClick={next} disabled={index === DEMO_STEPS.length - 1}>Next (Space)</button>
        <button type="button" className={styles.exit} onClick={exit} aria-label="Exit demo"><X size={16} /></button>
      </div>
    </div>
  );
}
