import {
  CalendarClock,
  BellRing,
  PauseCircle,
  Send,
  CheckCircle2,
  XCircle,
  Scissors,
  Sprout,
  Ban,
  type LucideIcon,
} from 'lucide-react';
import type { ChipTone } from '../ui/Chip';
import type { TimelineState } from '../data/DataSource';

export interface ChipSpec {
  label: string;
  tone: ChipTone;
  icon: LucideIcon;
}

const MAP: Record<TimelineState, ChipSpec> = {
  scheduled: { label: 'Scheduled', tone: 'neutral', icon: CalendarClock },
  due: { label: 'Due', tone: 'green', icon: BellRing },
  deferred_by_cap: { label: 'Deferred (cap)', tone: 'amber', icon: PauseCircle },
  delivered: { label: 'Delivered', tone: 'green', icon: Send },
  answered: { label: 'Answered', tone: 'green', icon: CheckCircle2 },
  expired: { label: 'Expired', tone: 'amber', icon: XCircle },
  window_truncated_by_season_end: { label: 'Held back (season end)', tone: 'amber', icon: Scissors },
  crop_already_harvested: { label: 'Held back (harvested)', tone: 'amber', icon: Sprout },
  no_survey: { label: 'No survey', tone: 'neutral', icon: Ban },
};

/** Total mapping: every state yields exactly one icon+label chip. */
export function chipFor(state: TimelineState): ChipSpec {
  return MAP[state];
}

export const ALL_STATES = Object.keys(MAP) as TimelineState[];
