import type { ReactNode } from 'react';
import styles from './States.module.css';

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className={styles.state} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ label = 'Nothing here yet.' }: { label?: string }) {
  return (
    <div className={styles.state} role="status">
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className={styles.error} role="alert">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className={styles.retry} onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function QueryBoundary<T>(props: {
  status: 'pending' | 'error' | 'success';
  error?: unknown;
  data?: T;
  onRetry?: () => void;
  empty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
  loadingLabel?: string;
  emptyLabel?: string;
}) {
  if (props.status === 'pending') return <LoadingState label={props.loadingLabel} />;
  if (props.status === 'error') {
    const msg = props.error instanceof Error ? props.error.message : 'Something went wrong.';
    return <ErrorState message={msg} onRetry={props.onRetry} />;
  }
  const data = props.data as T;
  if (props.empty?.(data)) return <EmptyState label={props.emptyLabel} />;
  return <>{props.children(data)}</>;
}
