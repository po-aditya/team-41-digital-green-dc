import type { DataSource, SourceKind } from './DataSource';
import { PackSource } from './PackSource';
import { FixtureSource } from './FixtureSource';
import { LiveApiSource } from './LiveApiSource';

export interface BuildSourceArgs {
  kind: SourceKind;
  apiBase: string;
  getToken: () => string | null;
  fixturesBase?: string;
}

export function buildSource(args: BuildSourceArgs): DataSource {
  switch (args.kind) {
    case 'live':
      return new LiveApiSource({
        baseUrl: args.apiBase,
        getToken: args.getToken,
        fixturesBase: args.fixturesBase,
      });
    case 'pack':
      return new PackSource(args.fixturesBase);
    case 'fixture':
    default:
      return new FixtureSource(args.fixturesBase);
  }
}
