"""Command line entry points.

  python -m mel_agent.cli eval --name v1 [--policy baseline] [--language hi-IN] [--limit 20] [--rules-only]
  python -m mel_agent.cli generate [--limit 200] [--language hi-IN]   # full dataset -> out/results.jsonl
  python -m mel_agent.cli season                                      # simulate the season from out/results.jsonl
"""
import argparse
import json
import sys
import time
from datetime import datetime

from . import config, data, evaluate, pipeline, rules, season


def cmd_eval(a):
    evaluate.run(a.name, policy=a.policy, language=a.language, limit=a.limit, use_llm=not a.rules_only,
                 workers=a.workers)


def cmd_generate(a):
    ins = data.insights()[:a.limit] if a.limit else data.insights()
    config.OUT.mkdir(parents=True, exist_ok=True)
    path = config.OUT / (a.out or "results.jsonl")
    done = [0]
    t0 = time.time()
    f = open(path, "w", encoding="utf-8")

    def on_result(r):
        done[0] += 1
        if done[0] % 100 == 0 or done[0] == len(ins):
            print(f"{done[0]}/{len(ins)} in {time.time() - t0:.0f}s", flush=True)

    results, stats = pipeline.run_batch(ins, language=a.language, policy=a.policy, workers=a.workers, on_result=on_result)
    for r in results:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    f.close()
    stats["policy"], stats["language"], stats["writer_model"] = a.policy, a.language, config.WRITER_MODEL
    (config.OUT / "batch_stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(json.dumps(stats, indent=1))


def cmd_season(a):
    path = config.OUT / (a.results or "results.jsonl")
    hs = [r["handoff"] for r in data.read_jsonl(path) if r.get("handoff")]
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
    g.add_argument("--limit", type=int)
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
