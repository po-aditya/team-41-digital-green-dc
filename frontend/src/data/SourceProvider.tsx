import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useUiStore } from '../state/uiStore';
import type { DataSource } from './DataSource';
import { buildSource } from './sourceFactory';

const SourceContext = createContext<DataSource | null>(null);

export function SourceProvider({ children }: { children: ReactNode }) {
  const kind = useUiStore((s) => s.sourceKind);
  const apiBase = useUiStore((s) => s.apiBase);
  // token read lazily so it is never captured/persisted
  const source = useMemo(
    () =>
      buildSource({
        kind,
        apiBase,
        getToken: () => useUiStore.getState().token,
      }),
    [kind, apiBase],
  );
  return <SourceContext.Provider value={source}>{children}</SourceContext.Provider>;
}

export function useDataSource(): DataSource {
  const ds = useContext(SourceContext);
  if (!ds) throw new Error('useDataSource must be used within SourceProvider');
  return ds;
}

/**
 * Wrap a live-source call so that a transport failure flips the app to fixtures
 * and raises the banner, instead of breaking the demo. Returns the (possibly
 * fixture) result.
 */
export async function withFallback<T>(
  live: () => Promise<T>,
  fixture: () => Promise<T>,
): Promise<T> {
  try {
    return await live();
  } catch (err) {
    // Only fall back on transport-ish failures, not on aborts.
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    useUiStore.getState().setSource('fixture', { fallback: true });
    return await fixture();
  }
}
