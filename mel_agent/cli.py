"""Command line entry points.

  python -m mel_agent.cli eval --name v1 [--policy baseline] [--language hi-IN] [--limit 20] [--rules-only]
  python -m mel_agent.cli generate [--limit 300 --seed 7] [--workers 16]  # -> out/results.jsonl (resumable)
  python -m mel_agent.cli season                                      # simulate the season from out/results.jsonl
"""
import argparse
import json
import sys
import time
from datetime import datetime

from . import batch, config, data, evaluate, pipeline, rules, season


def cmd_eval(a):
    evaluate.run(a.name, policy=a.policy, language=a.language, limit=a.limit, use_llm=not a.rules_only,
                 workers=a.workers)


def cmd_generate(a):
    population = data.insights()
    if a.limit:
        targets = batch.stratified_sample(population, a.limit, a.seed, a.policy)
        label = f"stratified sample of {len(targets)} (seed {a.seed})"
    else:
        targets = list(population)
        label = f"all {len(targets)} insights"
    config.OUT.mkdir(parents=True, exist_ok=True)
    path = config.OUT / (a.out or "results.jsonl")
    sessions_path = path.with_suffix(".sessions.jsonl")
    run_settings = batch.settings(a.policy, a.language)

    # Resume: reuse finished results made with the same settings; errors are retried.
    existing = batch.load_results(path)
    done = {k for k, r in existing.items() if batch.reusable(r, run_settings)}
    stale = [k for k, r in existing.items() if not batch.reusable(r, run_settings) and r.get("status") != "error"]
    if stale:
        print(f"note: {len(stale)} results in {path.name} were made with other settings and will be redone")
    todo = [i for i in targets if i["insight_id"] not in done]
    print(f"{label}: {len(targets) - len(todo)} already done, {len(todo)} to run, "
          f"{a.workers or config.WORKERS} workers", flush=True)

    counts = {s: 0 for s in batch.STATUSES}
    t0 = time.time()
    with open(path, "a", encoding="utf-8") as f:
        def on_result(r):
            r["run_settings"] = run_settings
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            counts[r["status"]] += 1
            n = sum(counts.values())
            if r["status"] == "error":
                print(f"ERROR {r['insight_id']}: {r.get('error')}", flush=True)
            if n % 25 == 0 or n == len(todo):
                print(f"{n}/{len(todo)} in {time.time() - t0:.0f}s {counts}", flush=True)
        if todo:
            pipeline.run_batch(todo, language=a.language, policy=a.policy, workers=a.workers, on_result=on_result)
    wall = time.time() - t0
    with open(sessions_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": rules.fmt_ts(datetime.now(rules.IST)), "ran": len(todo), "workers": a.workers or config.WORKERS,
                            "wall_seconds": round(wall, 2), "limit": a.limit, "seed": a.seed}) + "\n")

    all_results = batch.load_results(path)
    ids = {i["insight_id"] for i in targets}
    results = [all_results[k] for k in sorted(ids) if k in all_results]
    sessions = [s for s in data.read_jsonl(sessions_path) if s.get("limit") == a.limit and s.get("seed") == a.seed]
    summary = batch.summarize(results, sum(s["wall_seconds"] for s in sessions), sessions)
    payload = {"settings": run_settings, "selection": {"limit": a.limit, "seed": a.seed, "targets": len(targets)},
               "results_file": _rel(path), **summary}
    if a.limit:
        payload["composition"] = batch.composition(targets, population, a.policy)
        payload["extrapolation"] = batch.extrapolate(summary, results, population, a.policy)
    name = a.report or ("sample-run" if a.limit else "generate-run")
    report = batch.write_report(name, payload)
    if a.history:
        batch.append_history(name, payload)
    print(json.dumps({k: v for k, v in payload.items() if k not in ("composition", "sessions")}, indent=1,
                     ensure_ascii=False))
    print(f"report: {_rel(report)}")


def _rel(p):
    try:
        return str(p.relative_to(config.ROOT))
    except ValueError:
        return str(p)


def cmd_season(a):
    path = config.OUT / (a.results or "results.jsonl")
    hs = [r["handoff"] for r in batch.load_results(path).values() if r.get("handoff")]
    s = season.Season(hs)
    s.advance(datetime(2027, 4, 10, tzinfo=rules.IST))
    print(json.dumps(s.summary(), indent=1))
    print("cap violations:", len(s.cap_violations()))


def main(argv=None):
    p = argparse.ArgumentParser(prog="mel_agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eval")
    e.add_argument("--name", required=True)
    e.add_argument("--policy", default=rules.DEFAULT_POLICY, choices=rules.POLICIES)
    e.add_argument("--language", default="en-IN")
    e.add_argument("--limit", type=int)
    e.add_argument("--workers", type=int)
    e.add_argument("--rules-only", action="store_true")
    e.set_defaults(fn=cmd_eval)
    g = sub.add_parser("generate")
    g.add_argument("--limit", type=int, help="stratified random sample of N insights instead of all")
    g.add_argument("--seed", type=int, default=7, help="random seed for --limit (default 7)")
    g.add_argument("--report", help="report name in reports/ (default sample-run or generate-run)")
    g.add_argument("--history", action="store_true", help="also append a line to reports/history.jsonl")
    g.add_argument("--language", default=None, help="default: each insight's conversation_language")
    g.add_argument("--policy", default=rules.DEFAULT_POLICY, choices=rules.POLICIES)
    g.add_argument("--workers", type=int)
    g.add_argument("--out")
    g.set_defaults(fn=cmd_generate)
    s = sub.add_parser("season")
    s.add_argument("--results")
    s.set_defaults(fn=cmd_season)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
