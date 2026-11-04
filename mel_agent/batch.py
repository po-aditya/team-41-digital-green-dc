"""Batch runs over the insights dataset: stratified sampling, resumable results, reports
and extrapolation to the full dataset."""
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime

from . import config, data, rules, writer

STATUSES = ("scheduled", "rejected", "writer_skipped", "no_survey", "error")

# Dimensions the sample must cover: every value seen in the dataset appears at least once.
COVERAGE = {
    "asset": lambda i: (i.get("asset") or {}).get("name"),
    "resolution_type": lambda i: i.get("resolution_type"),
    "conversation_language": lambda i: i.get("conversation_language"),
}


def settings(policy, language):
    """Everything that changes what the agent produces. A result is only reused on resume
    if it was made with the same settings."""
    return {"policy": policy, "language": language, "writer_model": config.WRITER_MODEL,
            "checker_model": config.CHECKER_MODEL, "min_relevance": config.MIN_RELEVANCE,
            "prompt_version": writer.PROMPT_VERSION}


# ---------------------------------------------------------------- sampling

def _quotas(sizes, n):
    """Proportional allocation by largest remainder, at least 1 per stratum."""
    total = sum(sizes.values())
    exact = {s: n * k / total for s, k in sizes.items()}
    quota = {s: max(1, math.floor(e)) for s, e in exact.items()}
    left = n - sum(quota.values())
    for s in sorted(exact, key=lambda s: exact[s] - math.floor(exact[s]), reverse=True):
        if left <= 0:
            break
        quota[s] += 1
        left -= 1
    while sum(quota.values()) > n:  # minimums pushed us over: trim the largest strata
        s = max(quota, key=lambda s: quota[s] - exact[s])
        quota[s] -= 1
    return quota, exact


def stratified_sample(insights, n, seed, policy=rules.DEFAULT_POLICY):
    """A random sample of n insights, stratified by the agent's decision rule (R1 to R8, so
    every junk and no-survey category is in proportion), that also contains every asset
    (crop or animal), resolution type and conversation language at least once."""
    pool = sorted(insights, key=lambda i: i["insight_id"])
    if n >= len(pool):
        return pool
    rng = random.Random(seed)
    stratum = {i["insight_id"]: rules.decide(i, policy).rule for i in pool}
    groups = defaultdict(list)
    for i in pool:
        groups[stratum[i["insight_id"]]].append(i)
    for g in groups.values():
        rng.shuffle(g)
    quota, exact = _quotas({s: len(g) for s, g in groups.items()}, n)

    chosen, required = {}, set()
    taken = Counter()

    def take(i, req=False):
        chosen[i["insight_id"]] = i
        taken[stratum[i["insight_id"]]] += 1
        if req:
            required.add(i["insight_id"])

    shuffled = pool[:]
    rng.shuffle(shuffled)
    for dim, f in COVERAGE.items():
        for value in sorted({f(i) for i in pool}, key=str):
            if any(f(i) == value for i in chosen.values()):
                continue
            cands = [i for i in shuffled if f(i) == value and i["insight_id"] not in chosen]
            room = [i for i in cands if taken[stratum[i["insight_id"]]] < quota[stratum[i["insight_id"]]]]
            take((room or cands)[0], req=True)

    for s, g in sorted(groups.items()):
        for i in g:
            if taken[s] >= quota[s]:
                break
            if i["insight_id"] not in chosen:
                take(i)

    if len(required) > n:
        raise ValueError(f"--limit {n} is too small: covering every asset, resolution type and language "
                         f"needs at least {len(required)} insights with seed {seed}")
    while len(chosen) > n:  # coverage picks overfilled some strata: drop optional picks
        s = max((s for s in taken if any(stratum[k] == s and k not in required for k in chosen)),
                key=lambda s: taken[s] - exact[s])
        drop = next(k for k in reversed(list(chosen)) if stratum[k] == s and k not in required)
        del chosen[drop]
        taken[s] -= 1
    return sorted(chosen.values(), key=lambda i: i["insight_id"])


def composition(sample, population, policy=rules.DEFAULT_POLICY):
    def count(rows, f):
        return Counter(str(f(i)) for i in rows)
    out = {"rule": {}}
    pr = count(population, lambda i: rules.decide(i, policy).rule)
    sr = count(sample, lambda i: rules.decide(i, policy).rule)
    for k in sorted(pr):
        out["rule"][k] = {"population": pr[k], "sample": sr.get(k, 0),
                          "proportional": round(len(sample) * pr[k] / len(population), 1)}
    for dim, f in COVERAGE.items():
        p, s = count(population, f), count(sample, f)
        out[dim] = {k: {"population": p[k], "sample": s.get(k, 0)} for k in sorted(p)}
        out[f"{dim}_all_covered"] = all(s.get(k, 0) > 0 for k in p)
    return out


# ---------------------------------------------------------------- resumable results

def load_results(path):
    """All results in the file, last line per insight wins (a rerun of an error replaces it)."""
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: {path.name} line {n} is not valid JSON (an interrupted write?); ignoring it")
                continue
            out[r["insight_id"]] = r
    return out


def reusable(r, run_settings):
    return r.get("run_settings") == run_settings and r.get("status") != "error"


# ---------------------------------------------------------------- reports

def _p95(xs):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, math.ceil(0.95 * len(xs)) - 1)], 2) if xs else None


def summarize(results, wall_seconds, sessions):
    surveyed = [r for r in results if r["decision"]["survey"]]
    secs = [r["seconds"] for r in surveyed]
    by_model = {}
    cost = None
    retries = 0
    for r in results:
        u = r["usage"]
        retries += u.get("retries", 0)
        if u.get("cost_usd") is not None:
            cost = (cost or 0.0) + u["cost_usd"]
        for model, m in u["by_model"].items():
            t = by_model.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            for k in t:
                t[k] += m[k]
    errors = [{"insight_id": r["insight_id"], "error": r.get("error")} for r in results if r["status"] == "error"]
    langs = sorted({(r.get("survey") or {}).get("language") for r in surveyed} - {None})
    judged = [r["check"]["judge"]["relevance_score"] for r in surveyed if (r.get("check") or {}).get("judge")]
    total_tokens = sum(m["input_tokens"] + m["output_tokens"] for m in by_model.values())
    return {
        "insights_processed": len(results),
        "status": {s: sum(1 for r in results if r["status"] == s) for s in STATUSES},
        "batch_wall_seconds": round(wall_seconds, 2),
        "sessions": sessions,
        "seconds_per_survey_avg": round(statistics.mean(secs), 2) if secs else None,
        "seconds_per_survey_p95": _p95(secs),
        "surveyed_insights": len(surveyed),
        "rejected_by_language": {lg: sum(1 for r in surveyed if r["status"] == "rejected"
                                         and (r.get("survey") or {}).get("language") == lg) for lg in langs},
        "surveyed_by_language": {lg: sum(1 for r in surveyed if (r.get("survey") or {}).get("language") == lg)
                                 for lg in langs},
        "self_check_relevance_avg": round(statistics.mean(judged), 4) if judged else None,
        "self_check_judged": len(judged),
        "tokens_per_survey": round(total_tokens / len(surveyed)) if surveyed else None,
        "tokens_by_model": by_model,
        "tokens_total": {"input": sum(m["input_tokens"] for m in by_model.values()),
                         "output": sum(m["output_tokens"] for m in by_model.values())},
        "bedrock_retries": retries,
        "cost_usd": None if cost is None else round(cost, 4),
        "cost_note": None if cost is not None else
        "Not estimated: set MEL_WRITER_PRICE and MEL_CHECKER_PRICE (USD per 1M tokens, 'input,output').",
        "errors": errors,
    }


def extrapolate(summary, results, population, policy=rules.DEFAULT_POLICY):
    """Scales the sample to the full dataset. Only insights that get a survey (R8) call the
    models, so time and tokens scale with the number of surveyed insights, and decisions are
    exact because the rules are deterministic."""
    full_decisions = Counter(rules.decide(i, policy).survey for i in population)
    full_surveyed = full_decisions[True]
    n_surveyed = summary["surveyed_insights"]
    f = full_surveyed / n_surveyed if n_surveyed else 0
    surveyed = [r for r in results if r["decision"]["survey"]]
    rate = {s: sum(1 for r in surveyed if r["status"] == s) / n_surveyed if n_surveyed else 0
            for s in ("scheduled", "rejected", "writer_skipped", "error")}
    return {
        "population_insights": len(population),
        "population_surveyed_exact": full_surveyed,
        "population_no_survey_exact": full_decisions[False],
        "scale_factor": round(f, 3),
        "expected_status": {s: round(full_surveyed * v) for s, v in rate.items()} | {"no_survey": full_decisions[False]},
        "expected_wall_seconds": round(summary["batch_wall_seconds"] * f),
        "expected_wall_hours": round(summary["batch_wall_seconds"] * f / 3600, 2),
        "expected_tokens_by_model": {m: {"input_tokens": round(v["input_tokens"] * f),
                                         "output_tokens": round(v["output_tokens"] * f)}
                                     for m, v in summary["tokens_by_model"].items()},
        "expected_cost_usd": None if summary["cost_usd"] is None else round(summary["cost_usd"] * f, 2),
        "assumes": "same worker count and Bedrock throughput as the sample run; wall time scales with surveyed insights",
    }


def append_history(name, payload):
    """One line in reports/history.jsonl for a batch run. kind="batch" keeps it apart from
    golden-set evaluation lines, which have golden_cases and scores."""
    s = payload
    line = {"name": name, "at": rules.fmt_ts(datetime.now(rules.IST)), "kind": "batch",
            "policy": s["settings"]["policy"], "language": s["settings"]["language"],
            "prompt_version": s["settings"]["prompt_version"], "min_relevance": s["settings"]["min_relevance"],
            "selection": s["selection"], "insights_processed": s["insights_processed"], "status": s["status"],
            "rejected_by_language": s["rejected_by_language"], "self_check_relevance_avg": s["self_check_relevance_avg"],
            "batch_wall_seconds": s["batch_wall_seconds"], "seconds_per_survey_avg": s["seconds_per_survey_avg"],
            "seconds_per_survey_p95": s["seconds_per_survey_p95"], "tokens_per_survey": s["tokens_per_survey"],
            "tokens_by_model": s["tokens_by_model"], "errors": len(s["errors"])}
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    with open(config.REPORTS / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def write_report(name, payload):
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "at": rules.fmt_ts(datetime.now(rules.IST)), **payload}
    path = config.REPORTS / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
