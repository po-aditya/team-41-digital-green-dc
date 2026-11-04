import { useEffect, useRef } from 'react';

/** Visually hidden ARIA live region for clock changes and JAAKBOT captions. */
export function LiveRegion({ message, assertive }: { message: string; assertive?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // force re-announce even if the same text repeats
    if (ref.current) ref.current.textContent = message;
  }, [message]);
  return (
    <div
      ref={ref}
      className="visually-hidden"
      role="status"
      aria-live={assertive ? 'assertive' : 'polite'}
      aria-atomic="true"
    />
  );
}
