import { FixturesBackedSource } from './fixturesBacked';
import type { SourceKind } from './DataSource';

/** Reads the six scenarios + outcomes copied from the participant pack. */
export class PackSource extends FixturesBackedSource {
  readonly kind: SourceKind = 'pack';
}
