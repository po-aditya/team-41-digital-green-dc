"""Loads the synthetic insights, farmers, crop calendar, rules and schemas."""
import csv
import json
from datetime import date
from functools import lru_cache

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from . import config


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@lru_cache
def insights():
    return read_jsonl(config.DATA / "insights.jsonl")


@lru_cache
def insights_by_id():
    return {i["insight_id"]: i for i in insights()}


@lru_cache
def golden():
    return read_jsonl(config.DATA / "golden_set.jsonl")


@lru_cache
def farmers():
    with open(config.DATA / "farmers.csv", encoding="utf-8") as f:
        return {r["farmer_id"]: r for r in csv.DictReader(f)}


@lru_cache
def rules():
    return json.loads(config.RULES_FILE.read_text(encoding="utf-8"))


@lru_cache
def outcome_codes():
    return json.loads(config.OUTCOMES_FILE.read_text(encoding="utf-8"))


@lru_cache
def crop_last_day():
    """Last date on the calendar for each crop (end of its latest stage)."""
    last = {}
    with open(config.DATA / "crop_calendar_bihar_rabi.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                end = date.fromisoformat(r["end_date"])
            except (TypeError, ValueError):
                continue
            crop = r["crop"].strip().lower()
            last[crop] = max(last.get(crop, end), end)
    return last


@lru_cache
def _registry():
    reg = Registry()
    for p in config.SCHEMAS.glob("*.schema.json"):
        s = json.loads(p.read_text(encoding="utf-8"))
        res = Resource.from_contents(s)
        reg = reg.with_resource(s["$id"], res).with_resource(p.name, res)
    return reg


@lru_cache
def validator(name):
    """name: insight, survey, schedule_handoff, response, no_survey, bottom_sheet."""
    s = json.loads((config.SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(s, registry=_registry())


def schema_errors(name, obj):
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
            for e in validator(name).iter_errors(obj)]


@lru_cache
def scenario_examples():
    """Worked surveys from Digital Green, used as examples in the writer prompt."""
    out = []
    for d in sorted(config.SCENARIOS.iterdir()):
        if not (d / "survey.en-IN.json").exists():
            continue
        ins = json.loads((d / "insight.json").read_text(encoding="utf-8"))
        en = json.loads((d / "survey.en-IN.json").read_text(encoding="utf-8"))
        hi = json.loads((d / "survey.hi-IN.json").read_text(encoding="utf-8"))
        out.append({"name": d.name, "insight": ins, "en-IN": en, "hi-IN": hi})
    return out
