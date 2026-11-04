/**
 * npm run fixtures
 *
 * Populates frontend/public/fixtures from (a) the participant pack and (b) a
 * real offline mel_agent run (via capture_runs.py). NOTHING here is hand-authored
 * survey/response data: scenarios, outcomes, schemas and reports are copied from
 * the pack, and the generate/*.json files are captured from the live pipeline.
 *
 * A seed/ folder adds states the six scenarios lack (deferred-by-cap, expired,
 * window_truncated_by_season_end, a critical human-queue item, a quarantined
 * ingest row) by DERIVING them from real pack records (never inventing fields).
 */
import { execFileSync } from 'node:child_process';
import { cpSync, mkdirSync, readFileSync, writeFileSync, existsSync, rmSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(here, '..', '..');
const REPO = resolve(FRONTEND, '..');
const PACK = join(REPO, 'data', 'participant-pack');
const REPORTS = join(REPO, 'reports');
const OUT = join(FRONTEND, 'public', 'fixtures');

function log(msg: string) {
  process.stdout.write(`[fixtures] ${msg}\n`);
}

function pickPython(): string {
  for (const p of [join(REPO, '.venv', 'bin', 'python'), 'python3', 'python']) {
    try {
      execFileSync(p, ['--version'], { stdio: 'ignore' });
      return p;
    } catch {
      /* try next */
    }
  }
  throw new Error('no python interpreter found for capture_runs.py');
}

function readJson<T = unknown>(path: string): T {
  return JSON.parse(readFileSync(path, 'utf-8')) as T;
}
function writeJson(path: string, value: unknown) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(value, null, 2) + '\n', 'utf-8');
}

// 1. clean + copy pack assets -------------------------------------------------
if (existsSync(OUT)) rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

log('copying pack scenarios, outcomes, schemas, rules');
cpSync(join(PACK, 'json', 'scenarios'), join(OUT, 'scenarios'), { recursive: true });
cpSync(join(PACK, 'json', 'outcomes'), join(OUT, 'outcomes'), { recursive: true });
{
  const rels: string[] = [];
  const walkOut = (d: string, prefix: string) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      if (e.isDirectory()) walkOut(join(d, e.name), prefix ? prefix + '/' + e.name : e.name);
      else if (e.name.endsWith('.json')) rels.push((prefix ? prefix + '/' : '') + e.name);
    }
  };
  walkOut(join(OUT, 'outcomes'), '');
  writeJson(join(OUT, 'outcomes-manifest.json'), rels.sort());
  log(`outcomes manifest:  records`);
}
cpSync(join(PACK, 'json', 'schemas'), join(OUT, 'schemas'), { recursive: true });
cpSync(join(PACK, 'json', 'rules'), join(OUT, 'rules'), { recursive: true });

log('copying reports v0..v4');
mkdirSync(join(OUT, 'reports'), { recursive: true });
for (const f of readdirSync(REPORTS)) {
  if (f.endsWith('.json')) cpSync(join(REPORTS, f), join(OUT, 'reports', f));
}

// 2. capture a real offline pipeline run --------------------------------------
log('capturing real pipeline output (template provider, offline)');
const py = pickPython();
const manifestRaw = execFileSync(py, [join(here, 'capture_runs.py'), REPO, OUT], {
  encoding: 'utf-8',
  env: { ...process.env, MEL_PROVIDER: 'template', PYTHONPATH: REPO },
});
const manifest = JSON.parse(manifestRaw.trim().split('\n').pop() as string);
writeJson(join(OUT, 'generate', 'manifest.json'), manifest);

// 3. build a scenarios index --------------------------------------------------
type ScenMeta = {
  scenario: string;
  survey_id: string | null;
  farmer_id: string;
  languages: string[];
  decision: 'survey' | 'no_survey';
};
const scenDir = join(OUT, 'scenarios');
const index: ScenMeta[] = [];
for (const name of readdirSync(scenDir).sort()) {
  const insight = readJson<{ farmer_id: string }>(join(scenDir, name, 'insight.json'));
  const langs = ['en-IN', 'hi-IN'].filter((l) => existsSync(join(scenDir, name, `survey.${l}.json`)));
  const isNoSurvey = existsSync(join(scenDir, name, 'no_survey.json'));
  const gen = manifest.generated.find((g: { scenario: string }) => g.scenario === name);
  index.push({
    scenario: name,
    survey_id: gen?.survey_id ?? null,
    farmer_id: insight.farmer_id,
    languages: langs,
    decision: isNoSurvey ? 'no_survey' : 'survey',
  });
}
writeJson(join(OUT, 'scenarios-index.json'), index);

// 4. FixtureSource seed: states the scenarios lack ----------------------------
// Each seed row is DERIVED from a real pack record. We tag a UI-only `seed_state`
// and copy real values; we never fabricate schema fields.
log('building fixture seed (deferred/expired/season-truncated/human-queue/quarantined)');

const handoff1 = readJson<Record<string, unknown>>(
  join(scenDir, '1-mustard-aphid-spray', 'schedule_handoff.json'),
);
const handoff2 = readJson<Record<string, unknown>>(
  join(scenDir, '2-wheat-irrigation-timing', 'schedule_handoff.json'),
);

// deferred-by-cap: a second survey to the same farmer inside the cap window.
const deferred = {
  seed_state: 'deferred_by_cap',
  note: 'Derived from scenario 1 handoff; a second survey to the same farmer within the 7-day cap window.',
  handoff: handoff1,
};
// expired: a survey whose not_after is already past the simulated clock.
const expired = {
  seed_state: 'expired',
  note: 'Derived from scenario 2 handoff; window fully in the past relative to the demo clock.',
  handoff: handoff2,
};
// window_truncated_by_season_end: send window clipped at 2027-03-31.
const seasonTruncated = {
  seed_state: 'window_truncated_by_season_end',
  note: 'Derived from scenario 2 handoff; not_after would fall after 2027-03-31 and is clipped.',
  season_end: '2027-03-31',
  handoff: handoff2,
};
// human-queue critical case: the cow-vet escalation insight (real pack insight).
const criticalInsight = readJson(join(scenDir, '4-cow-vet-escalation', 'insight.json'));
const humanQueue = [
  {
    seed_state: 'human_queue_critical',
    note: 'Real pack insight routed to a human (escalation), surfaced in the simulated reviewer view.',
    insight: criticalInsight,
    status: 'new',
  },
];
// quarantined ingest row: a real non-clean insight from insights.jsonl.
let quarantined: unknown = null;
const insightsPath = join(PACK, 'data', 'insights.jsonl');
if (existsSync(insightsPath)) {
  const lines = readFileSync(insightsPath, 'utf-8').split('\n').filter(Boolean);
  for (const line of lines) {
    const row = JSON.parse(line) as { quality_flag?: string };
    if (row.quality_flag && row.quality_flag !== 'clean' && row.quality_flag !== 'ok') {
      quarantined = { seed_state: 'quarantined', note: 'Real non-clean insights.jsonl row.', insight: row };
      break;
    }
  }
}

writeJson(join(OUT, 'seed', 'seed.json'), {
  deferred,
  expired,
  season_truncated: seasonTruncated,
  human_queue: humanQueue,
  quarantined,
});

// 5. ingest stats derived from real insights.jsonl ----------------------------
let total = 0;
let nonClean = 0;
if (existsSync(insightsPath)) {
  for (const line of readFileSync(insightsPath, 'utf-8').split('\n')) {
    if (!line.trim()) continue;
    total += 1;
    const row = JSON.parse(line) as { quality_flag?: string };
    if (row.quality_flag && row.quality_flag !== 'clean' && row.quality_flag !== 'ok') nonClean += 1;
  }
}
writeJson(join(OUT, 'ingest-stats.json'), {
  total,
  valid: total - nonClean,
  quarantined: nonClean,
  source: 'data/participant-pack/data/insights.jsonl',
});

log(`done. insights total=${total} valid=${total - nonClean} quarantined=${nonClean}`);
