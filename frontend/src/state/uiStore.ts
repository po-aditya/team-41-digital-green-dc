import { create } from 'zustand';
import type { SourceKind } from '../data/DataSource';
import type { Channel, Language } from '../data/types';

export interface UiState {
  sourceKind: SourceKind;
  /** set true only by the auto-fallback path, to show the banner. */
  fellBackToFixtures: boolean;
  apiBase: string;
  /** operator token: in memory only, never persisted. */
  token: string | null;

  language: Language; // farmer-view language
  activeScenario: string | null;
  activeChannel: Channel;
  activeSurveyId: string | null;

  setSource: (kind: SourceKind, opts?: { fallback?: boolean }) => void;
  setApiBase: (base: string) => void;
  setToken: (token: string | null) => void;
  setLanguage: (lang: Language) => void;
  selectScenario: (scenario: string | null) => void;
  setChannel: (channel: Channel) => void;
  selectSurvey: (surveyId: string | null) => void;
  dismissFallbackBanner: () => void;
}

const envBase =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_BASE) || '';

export const useUiStore = create<UiState>((set) => ({
  // default to fixtures so the demo never dies on stage
  sourceKind: envBase ? 'live' : 'fixture',
  fellBackToFixtures: false,
  apiBase: envBase,
  token: null,
  language: 'hi-IN',
  activeScenario: null,
  activeChannel: 'app',
  activeSurveyId: null,

  setSource: (kind, opts) => set({ sourceKind: kind, fellBackToFixtures: opts?.fallback ?? false }),
  setApiBase: (base) => set({ apiBase: base }),
  setToken: (token) => set({ token }),
  setLanguage: (language) => set({ language }),
  selectScenario: (activeScenario) => set({ activeScenario }),
  setChannel: (activeChannel) => set({ activeChannel }),
  selectSurvey: (activeSurveyId) => set({ activeSurveyId }),
  dismissFallbackBanner: () => set({ fellBackToFixtures: false }),
}));
