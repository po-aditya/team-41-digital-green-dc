import { useEffect, useState } from 'react';
import { Check } from 'lucide-react';
import styles from './Confetti.module.css';

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false;
}

/** Green/white confetti burst; a static green check under reduced motion. */
export function Confetti({ active }: { active: boolean }) {
  const [reduced, setReduced] = useState(false);
  useEffect(() => setReduced(prefersReducedMotion()), []);
  if (!active) return null;
  if (reduced) {
    return (
      <div className={styles.staticWrap} role="img" aria-label="completed">
        <Check size={48} color="var(--green-brand)" strokeWidth={3} />
      </div>
    );
  }
  const pieces = Array.from({ length: 28 });
  const greens = ['var(--green-brand)', 'var(--green-deep)', 'var(--green-light-2)', 'var(--white)'];
  return (
    <div className={styles.wrap} aria-hidden="true">
      {pieces.map((_, i) => (
        <span
          key={i}
          className={styles.piece}
          style={{
            left: `${(i / pieces.length) * 100}%`,
            background: greens[i % greens.length],
            animationDelay: `${(i % 7) * 40}ms`,
          }}
        />
      ))}
    </div>
  );
}
