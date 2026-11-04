import { QueryClient } from '@tanstack/react-query';

/** No timer polling; rely on explicit invalidation after writes. */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        retry: 1,
        refetchOnWindowFocus: false,
        refetchInterval: false,
      },
    },
  });
}
