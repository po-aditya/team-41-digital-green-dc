import json

from mel_agent.data.pack import pack_paths
from mel_agent.evaluation.golden import evaluate_golden, render_markdown


def test_golden_evaluation_metrics_and_explanations(settings, rules, calendar, registry):
    report = evaluate_golden(pack_paths(settings), rules, calendar, registry, settings).to_dict()
    m = report["eligibility"]
    assert report["cases"] == 150 and m["tp"] + m["fp"] + m["tn"] + m["fn"] == 150
    assert m["fp"] == 0 and m["fn"] <= 2 and m["precision"] == 1.0 and m["accuracy"] >= 0.98
    assert m["no_survey_reason_code_agreement"] == "55/55"
    assert all(mm["cause"] for mm in report["mismatches"])
    assert report["channel"]["first_channel_matches_golden"] == report["channel"]["surveys_compared"] == m["tp"]
    f = report["format"]
    assert f["generation_failures"] == 0 and f["survey_schema_valid"] == f["handoff_schema_valid"] == f["generated"] == m["tp"]
    assert report["timing"]["windows_overlap"] >= 0.9 * m["tp"]
    assert 0 < report["relevance"]["lexical_overlap_mean"] <= 1
    assert report["relevance"]["surveys_naming_the_asset"] == m["tp"]


def test_hindi_evaluation_runs(settings, rules, calendar, registry):
    report = evaluate_golden(pack_paths(settings), rules, calendar, registry, settings, language="hi-IN").to_dict()
    assert report["format"]["generation_failures"] == 0 and report["format"]["language"] == "hi-IN"
    assert report["relevance"]["lexical_overlap_mean"] is None and "not applicable" in report["relevance"]["method"]
    assert report["relevance"]["surveys_naming_the_asset"] == report["relevance"]["of"] == report["eligibility"]["tp"]


def test_markdown_render(settings, rules, calendar, registry):
    report = evaluate_golden(pack_paths(settings), rules, calendar, registry, settings).to_dict()
    md = render_markdown(report)
    assert "| ours: survey | TP 93" in md and "## Mismatches" in md
    json.dumps(report)  # serialisable
