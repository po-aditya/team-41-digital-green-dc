"""Evaluation against the 150-case golden set, plus downstream property checks.

The golden set is evaluation data only: nothing in the decision path reads it.
Numbers here are computed on every run; none are typed in.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mel_agent.config import Settings
from mel_agent.contracts import SchemaName, SchemaRegistry
from mel_agent.data.pack import PackPaths, Rules
from mel_agent.generation.generator import SurveyGenerator
from mel_agent.generation.models import SurveyProvider, SurveyRequest
from mel_agent.generation.templates import ASSET_HI
from mel_agent.rules.eligibility import CropCalendar, decide
from mel_agent.rules.scheduling import build_handoff, channel_order_for, priority_for, survey_id_for
from mel_agent.time_utils import parse_ist

_WORD = re.compile(r"[a-z]{3,}")
_STOP = {"the", "you", "your", "did", "have", "has", "how", "now", "and", "for", "what", "was", "were", "are", "any", "not", "yet", "far", "much"}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


@dataclass
class GoldenReport:
    cases: int
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    reason_code_agreement: int = 0
    reason_code_total: int = 0
    by_golden_rule: dict[str, dict[str, int]] = field(default_factory=dict)
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    timing: dict[str, Any] = field(default_factory=dict)
    channel: dict[str, Any] = field(default_factory=dict)
    format: dict[str, Any] = field(default_factory=dict)
    relevance: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0

    def metrics(self) -> dict[str, Any]:
        tp, fp, tn, fn = self.tp, self.fp, self.tn, self.fn
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        accuracy = (tp + tn) / self.cases if self.cases else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
        return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
                "precision": round(precision, 4) if precision is not None else None,
                "recall": round(recall, 4) if recall is not None else None,
                "accuracy": round(accuracy, 4) if accuracy is not None else None,
                "f1": round(f1, 4) if f1 is not None else None,
                "no_survey_reason_code_agreement": f"{self.reason_code_agreement}/{self.reason_code_total}"}

    def to_dict(self) -> dict[str, Any]:
        return {"cases": self.cases, "eligibility": self.metrics(), "by_golden_rule": self.by_golden_rule, "mismatches": self.mismatches,
                "timing": self.timing, "channel": self.channel, "format": self.format, "relevance": self.relevance,
                "elapsed_s": round(self.elapsed_s, 3),
                "notes": [
                    "Eligibility uses rules.json + the content-based junk signature; the golden labels are never read by the decision code.",
                    "Timing is computed with the rules.json formula (which reproduces the pack's worked scenarios). The golden set uses a different "
                    "formula (09:00 start, no action-window clamp), so date agreement is reported separately from overlap.",
                    "Relevance is a lexical proxy (token overlap with the golden item texts), not a judgement of language quality.",
                ]}


def _explain_mismatch(golden: dict[str, Any], ours_rule: str, ours_reason: str, insight: dict[str, Any], rules: Rules, calendar: CropCalendar) -> str:
    if golden.get("rule") == "R8" and ours_rule == "R7":
        return ("rules.json timing (start not before the action window ends) puts the first send date after this crop's calendar end; "
                "the golden formula (no action-window clamp) starts earlier and keeps the survey. Contract disagreement, not a code defect.")
    if golden.get("rule") == "R8" and ours_reason == "window_truncated_by_season_end":
        return ("rules.json requires a window at least min_width_days wide AND nothing after 31 March; both cannot hold for this insight, "
                "so it is held back rather than sent with a truncated window. The golden set accepts the truncated (even zero-width) window. "
                "Conservative decision pending Digital Green's ruling.")
    if golden.get("rule") == "R8" and ours_rule == "R6":
        return "rules.json timing starts after 31 March; the golden formula starts earlier."
    if golden.get("rule") != "R8" and ours_rule == "R8":
        return f"golden suppresses with {golden.get('reason_code')}; our rules found no matching suppression condition."
    return "different rule matched first; see precedence table in docs/IMPLEMENTATION_PLAN.md."


def evaluate_golden(paths: PackPaths, rules: Rules, calendar: CropCalendar, registry: SchemaRegistry, settings: Settings,
                    provider: SurveyProvider | None = None, language: str = "en-IN") -> GoldenReport:
    started = time.perf_counter()
    cases = [json.loads(l) for l in paths.golden_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    report = GoldenReport(cases=len(cases))
    generator = SurveyGenerator(settings, registry, provider)
    same_start = same_end = same_both = overlap = within_golden = 0
    first_channel_match = method_match = surveys = 0
    schema_valid = handoff_valid = 0
    item_count_in_range = 0
    item_count_equal = 0
    jaccards: list[float] = []
    asset_mentions = 0
    gen_failures = 0
    for case in cases:
        insight, expected = case["insight"], case["expected"]
        ours = decide(insight, rules, calendar)
        g_survey, o_survey = bool(expected["survey"]), ours.survey
        rule_stats = report.by_golden_rule.setdefault(expected.get("rule", "?"), {"cases": 0, "agree": 0})
        rule_stats["cases"] += 1
        if g_survey and o_survey:
            report.tp += 1
        elif g_survey and not o_survey:
            report.fn += 1
        elif not g_survey and o_survey:
            report.fp += 1
        else:
            report.tn += 1
        agree = g_survey == o_survey
        if not g_survey:
            report.reason_code_total += 1
            if expected.get("reason_code") == ours.reason.value:
                report.reason_code_agreement += 1
            else:
                agree = False
        if agree:
            rule_stats["agree"] += 1
        else:
            report.mismatches.append({
                "insight_id": case["insight_id"], "golden_rule": expected.get("rule"), "golden_reason": expected.get("reason_code"),
                "golden_survey": g_survey, "our_rule": ours.rule, "our_reason": ours.reason.value, "our_survey": o_survey,
                "cause": _explain_mismatch(expected, ours.rule, ours.reason.value, insight, rules, calendar),
            })
        if g_survey and o_survey and ours.send_window is not None:
            surveys += 1
            w = ours.send_window.to_contract()
            gs, ge = expected["send_window"]["start"], expected["send_window"]["end"]
            s_ok, e_ok = w["not_before"][:10] == gs[:10], w["not_after"][:10] == ge[:10]
            same_start += s_ok; same_end += e_ok; same_both += s_ok and e_ok
            if parse_ist(w["not_before"]) <= parse_ist(ge) and parse_ist(w["not_after"]) >= parse_ist(gs):
                overlap += 1
            if parse_ist(w["not_before"]) >= parse_ist(gs) and parse_ist(w["not_after"]) <= parse_ist(ge):
                within_golden += 1
            prio = priority_for(insight, rules)
            order = channel_order_for(insight, prio, rules)
            first_channel_match += order[0]["channel"] == expected.get("channel")
            method_match += (insight.get("verification") or {}).get("method") == expected.get("method")
            request = SurveyRequest.build(survey_id_for(insight["insight_id"]), insight, None, language, ours.send_window,
                                          rules.asks_for_resolution(insight["resolution_type"]))
            result = generator.generate(request)
            if not result.accepted or result.survey is None:
                gen_failures += 1
                continue
            schema_valid += not registry.errors(SchemaName.SURVEY, result.survey)
            handoff_valid += not registry.errors(SchemaName.SCHEDULE_HANDOFF, build_handoff(insight, result.survey, ours.send_window, rules))
            n = len(result.survey["items"])
            item_count_in_range += 1 <= n <= 3
            item_count_equal += n == len(expected.get("items", []))
            if language.startswith("en"):
                golden_tokens = set().union(*(_tokens(it["text"]) | set().union(*(_tokens(o) for o in it["options"])) for it in expected.get("items", [])))
                our_tokens = set().union(*(_tokens(it["prompt"]) | set().union(*(_tokens(o["label"]) for o in it.get("options", []))) for it in result.survey["items"]))
                jaccards.append(_jaccard(golden_tokens, our_tokens))
            asset = (insight.get("asset") or {}).get("name")
            asset_terms = {asset} if asset else set()
            if language == "hi-IN" and asset in ASSET_HI:
                asset_terms.add(ASSET_HI[asset])
            asset_mentions += bool(asset_terms) and any(t in it["prompt"].lower() for t in asset_terms for it in result.survey["items"])
    report.timing = {"surveys_compared": surveys, "same_start_date": same_start, "same_end_date": same_end, "same_both_dates": same_both,
                     "windows_overlap": overlap, "our_window_within_golden": within_golden}
    report.channel = {"surveys_compared": surveys, "first_channel_matches_golden": first_channel_match, "verification_method_matches_golden": method_match}
    report.format = {"generated": surveys - gen_failures, "generation_failures": gen_failures, "survey_schema_valid": schema_valid,
                     "handoff_schema_valid": handoff_valid, "item_count_1_to_3": item_count_in_range, "item_count_equals_golden": item_count_equal,
                     "language": language}
    report.relevance = {"lexical_overlap_mean": round(sum(jaccards) / len(jaccards), 4) if jaccards else None,
                        "lexical_overlap_min": round(min(jaccards), 4) if jaccards else None,
                        "surveys_naming_the_asset": asset_mentions, "of": surveys - gen_failures,
                        "method": ("Jaccard over content words of prompts+labels vs golden item texts+options (proxy only)" if language.startswith("en")
                                   else "lexical overlap not applicable: golden items are English; asset naming uses the Hindi glossary")}
    report.elapsed_s = time.perf_counter() - started
    return report


def render_markdown(report: dict[str, Any], title: str = "Golden-set evaluation") -> str:
    m = report["eligibility"]
    lines = [f"# {title}", "", f"Cases: {report['cases']}", "",
             "## Eligibility (survey / no survey)", "",
             "| | golden: survey | golden: no survey |", "|---|---|---|",
             f"| ours: survey | TP {m['tp']} | FP {m['fp']} |", f"| ours: no survey | FN {m['fn']} | TN {m['tn']} |", "",
             f"Precision {m['precision']}, recall {m['recall']}, accuracy {m['accuracy']}, F1 {m['f1']}. "
             f"No-survey reason-code agreement {m['no_survey_reason_code_agreement']}.", "",
             "## Agreement by golden rule", "", "| rule | cases | agree |", "|---|---|---|"]
    for rule, st in sorted(report["by_golden_rule"].items()):
        lines.append(f"| {rule} | {st['cases']} | {st['agree']} |")
    lines += ["", "## Mismatches", ""]
    if not report["mismatches"]:
        lines.append("None.")
    for mm in report["mismatches"]:
        lines.append(f"- **{mm['insight_id']}**: golden {mm['golden_rule']}/{mm['golden_reason'] or 'survey'} vs ours {mm['our_rule']}/{mm['our_reason']}. {mm['cause']}")
    t, c, f, r = report["timing"], report["channel"], report["format"], report["relevance"]
    lines += ["", "## Timing (rules.json formula vs golden windows)", "",
              f"Of {t['surveys_compared']} surveys both sides agree on: same start date {t['same_start_date']}, same end date {t['same_end_date']}, "
              f"both {t['same_both_dates']}, overlapping windows {t['windows_overlap']}, ours inside golden {t['our_window_within_golden']}.",
              "", "## Channel", "", f"First channel matches golden: {c['first_channel_matches_golden']}/{c['surveys_compared']}.",
              "", f"## Format ({f['language']})", "",
              f"Generated {f['generated']} (failures {f['generation_failures']}); survey schema valid {f['survey_schema_valid']}; "
              f"hand-off schema valid {f['handoff_schema_valid']}; 1–3 items {f['item_count_1_to_3']}; same item count as golden {f['item_count_equals_golden']}.",
              "", "## Relevance proxy", "",
              f"Lexical overlap with golden items: mean {r['lexical_overlap_mean']}, min {r['lexical_overlap_min']}; "
              f"surveys naming the crop/animal {r['surveys_naming_the_asset']}/{r['of']}. {r['method']}.", ""]
    lines += ["## Notes", ""] + [f"- {n}" for n in report["notes"]]
    return "\n".join(lines) + "\n"
