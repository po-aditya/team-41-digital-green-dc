import type { TimelineFilter } from './DataSource';

export const qk = {
  health: ['health'] as const,
  scenarios: ['scenarios'] as const,
  scenario: (id: string) => ['scenario', id] as const,
  renders: (id: string, lang: string) => ['renders', id, lang] as const,
  responses: (id: string) => ['responses', id] as const,
  survey: (id: string) => ['survey', id] as const,
  followUps: ['followUps'] as const,
  timeline: (f: TimelineFilter, offset: number) => ['timeline', f, offset] as const,
  ingestStats: ['ingestStats'] as const,
  reports: ['reports'] as const,
  outcomes: ['outcomes'] as const,
  humanQueue: ['humanQueue'] as const,
};
