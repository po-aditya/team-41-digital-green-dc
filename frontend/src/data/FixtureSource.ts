import { FixturesBackedSource } from './fixturesBacked';
import type { SourceKind } from './DataSource';

/** A seeded slice of a real offline backend run plus the pack, for states the
 *  six scenarios lack (deferred-by-cap, expired, season-truncated, human queue). */
export class FixtureSource extends FixturesBackedSource {
  readonly kind: SourceKind = 'fixture';
}
