import { create } from 'zustand';
import type { FollowUp, ResponseRecord } from '../data/types';

/**
 * Locally-captured responses and the follow-up cases they create during the
 * demo. These are UI state: when a real flow exists the record is also POSTed
 * via the data source, but the follow-up list the operator sees is the union of
 * the backend `GET /v1/follow-ups` and any cases created live in this session.
 */
interface ResponsesStore {
  responses: ResponseRecord[];
  followUps: FollowUp[];
  /** true once a response has been persisted via POST (vs simulated only). */
  lastPersisted: boolean | null;
  record: (r: ResponseRecord, followUp: FollowUp | null, persisted: boolean) => void;
  reset: () => void;
}

export const useResponsesStore = create<ResponsesStore>((set) => ({
  responses: [],
  followUps: [],
  lastPersisted: null,
  record: (r, followUp, persisted) =>
    set((s) => ({
      responses: [...s.responses.filter((x) => x.response_key !== r.response_key), r],
      followUps: followUp
        ? [...s.followUps.filter((x) => x.survey_id !== followUp.survey_id), followUp]
        : s.followUps,
      lastPersisted: persisted,
    })),
  reset: () => set({ responses: [], followUps: [], lastPersisted: null }),
}));
