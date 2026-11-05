"""Checks for the presentation deck at docs/pitch-deck.html.

The deck is a static, self-contained HTML file. These tests keep it honest and safe:
- the five required slides exist, in order;
- every headline number carries a ``data-metric`` key whose ``data-count`` must equal
  the recorded validation evidence (so the slides cannot drift from what was measured);
- the AWS architecture slide names the services that Terraform actually declares;
- no external scripts, stylesheets, inline event handlers or ``javascript:`` URLs.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "docs" / "pitch-deck.html"
SEASON = ROOT / "docs" / "validation" / "primary-full-season.json"
GOLDEN = ROOT / "docs" / "validation" / "primary-golden-evaluation.json"

EXPECTED_SLIDES = [
    "problem",
    "architecture",
    "flow",
    "demo",
    "impact",
]


class _DeckParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.slides: list[str] = []
        self.metrics: dict[str, str] = {}
        self.aws_nodes: set[str] = set()
        self.scripts_with_src: list[str] = []
        self.external_links: list[str] = []
        self.event_handlers: list[tuple[str, str]] = []
        self.js_urls: list[str] = []
        self.questions: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "data-insight" in a:
            self.questions.append(a)
        if tag == "section" and "slide" in a.get("class", "").split():
            self.slides.append(a.get("data-slide", ""))
        if "data-metric" in a:
            self.metrics[a["data-metric"]] = a.get("data-count", "")
        if "data-aws" in a:
            self.aws_nodes.add(a["data-aws"])
        if tag == "script" and a.get("src"):
            self.scripts_with_src.append(a["src"])
        if tag == "link" and a.get("href", "").startswith(("http:", "https:", "//")):
            self.external_links.append(a["href"])
        for k, v in a.items():
            if k.startswith("on"):
                self.event_handlers.append((tag, k))
            if k in ("href", "src", "action") and v.strip().lower().startswith("javascript:"):
                self.js_urls.append(v)


@pytest.fixture(scope="module")
def deck() -> _DeckParser:
    assert DECK.is_file(), f"missing {DECK}"
    p = _DeckParser()
    p.feed(DECK.read_text(encoding="utf-8"))
    return p


def _expected_metrics() -> dict[str, int]:
    s = json.loads(SEASON.read_text(encoding="utf-8"))
    g = json.loads(GOLDEN.read_text(encoding="utf-8"))["eligibility"]
    return {
        "insights": s["ingest"]["insights_lines"],
        "quarantined": s["ingest"]["insights_quarantined"],
        "farmers": s["ingest"]["farmers"],
        "surveys": s["generate"]["surveys_accepted"],
        "no_survey": s["summary"]["decisions"]["by_decision"]["no_survey"],
        "human_queue": s["decide"]["by_internal_reason"]["critical_needs_human_call"],
        "sent": s["broadcast"]["totals"]["sent"],
        "answered": s["broadcast"]["totals"]["answered"],
        "follow_up": s["summary"]["responses"]["needs_follow_up"],
        "blocked_unsafe": s["broadcast"]["totals"]["blocked_unsafe"],
        "cap_suppressed": s["broadcast"]["totals"]["cap_suppressed"],
        "golden_tp": g["tp"],
        "golden_fp": g["fp"],
        "golden_tn": g["tn"],
        "golden_fn": g["fn"],
    }


def test_five_slides_in_required_order(deck: _DeckParser) -> None:
    assert deck.slides == EXPECTED_SLIDES


@pytest.mark.parametrize("key,value", sorted(_expected_metrics().items()))
def test_metric_matches_recorded_evidence(deck: _DeckParser, key: str, value: int) -> None:
    assert key in deck.metrics, f"slide metric {key!r} missing"
    assert deck.metrics[key] == str(value), f"{key}: deck says {deck.metrics[key]}, evidence says {value}"


def test_architecture_names_terraform_services(deck: _DeckParser) -> None:
    tf = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "Terraform").glob("*.tf"))
    declared = set(re.findall(r'resource "aws_([a-z0-9]+)', tf))
    # Every Terraform-declared service family must appear on the diagram.
    wanted = {"lb": "alb", "instance": "ec2", "ebs": "ebs", "ecr": "ecr", "iam": "iam", "vpc": "vpc",
              "cognito": "cognito", "acm": "acm", "route53": "route53"}
    assert {"lb", "instance", "ebs", "ecr", "vpc"} <= declared, f"unexpected Terraform layout: {declared}"
    for tf_name, node in wanted.items():
        if tf_name in declared:
            assert node in deck.aws_nodes, f"diagram missing {node} ({tf_name} is declared in Terraform)"
    # Services used at runtime but not declared as resources.
    for node in ("secrets", "ssm", "bedrock"):
        assert node in deck.aws_nodes


def test_deck_is_self_contained_and_has_no_inline_handlers(deck: _DeckParser) -> None:
    assert deck.scripts_with_src == []
    assert deck.external_links == []
    assert deck.event_handlers == []
    assert deck.js_urls == []


def test_deck_declares_restrictive_csp() -> None:
    html = DECK.read_text(encoding="utf-8")
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    assert m, "missing CSP meta"
    csp = m.group(1)
    assert "default-src 'none'" in csp
    assert "connect-src" not in csp  # no network access needed
    assert "'unsafe-eval'" not in csp
    assert "base-uri 'none'" in csp


def test_no_external_urls_or_embeds() -> None:
    html = DECK.read_text(encoding="utf-8")
    assert not re.search(r"(?i)\b(?:https?:)?//[a-z0-9-]+(?:\.[a-z0-9-]+)+", html), "external URL found"
    assert not re.search(r"(?i)<(?:iframe|object|embed|img)\b|@import", html)


def test_csp_hash_matches_inline_script() -> None:
    """Editing the script without refreshing the CSP hash would silently disable the deck."""
    import base64
    import hashlib

    html = DECK.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(scripts) == 1
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
    assert f"'sha256-{digest}'" in html, "CSP script hash is stale; recompute it"
    assert "'unsafe-inline'" not in re.search(r"script-src ([^;]+)", html).group(1)


# ---------------------------------------------------------------------------
# Fact-check regressions: every claim below was CONTRADICTED or UNVERIFIABLE in the
# first version of the deck. These tests tie the corrected text to its source.
# ---------------------------------------------------------------------------

PACK = ROOT / "data" / "participant-pack"
RESPONSE_SCHEMA = PACK / "json" / "schemas" / "response.schema.json"


def _insights(ids: set[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with (PACK / "data" / "insights.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                if row.get("insight_id") in ids:
                    out[row["insight_id"]] = row
    return out


def _html() -> str:
    return DECK.read_text(encoding="utf-8")


def _script() -> str:
    return re.findall(r"<script>(.*?)</script>", _html(), re.S)[0]


def test_slide1_farmers_are_real_insights_and_questions_are_catalogue_renderings(deck: _DeckParser) -> None:
    from mel_agent.generation.catalog import allowed_intents, render_item, slots_for

    assert len(deck.questions) == 3
    rows = _insights({q["data-insight"] for q in deck.questions})
    html = _html()
    for q in deck.questions:
        ins = rows.get(q["data-insight"])
        assert ins is not None, f"{q['data-insight']} not in the participant pack"
        assert ins["quality_flag"] == "clean"
        assert q["data-intent"] in allowed_intents(ins["resolution_type"], ins["concern"])
        rendered = render_item("q1", q["data-intent"], "en-IN", slots_for(ins, "en-IN"))["prompt"]
        assert q["data-c"] == rendered
        assert ins["location"]["district"] in html


def test_broadcast_question_is_labelled_illustrative() -> None:
    assert "illustrative example we wrote, not a Digital Green survey" in _html()


def test_demo_questions_and_options_are_catalogue_text() -> None:
    from mel_agent.generation.catalog import render_item, slots_for

    ins = _insights({"I-000138"})["I-000138"]
    script = _script()
    assert '"F-000238"' in script and ins["farmer_id"] == "F-000238"
    for lang in ("hi-IN", "en-IN"):
        slots = slots_for(ins, lang)
        for intent in ("did_action", "state_now", "barrier"):
            item = render_item("q1", intent, lang, slots)
            assert json.dumps(item["prompt"], ensure_ascii=False) in script, (lang, intent)
            for opt in item["options"]:
                assert json.dumps(opt["label"], ensure_ascii=False) in script, (lang, opt["value"])
                if "follow_up" in opt:
                    assert f'f: "{opt["follow_up"]}"' in script


def test_phone_chrome_uses_product_bottom_sheet_labels() -> None:
    from mel_agent.delivery.bottom_sheet import _LABELS

    script = _script()
    for lang in ("hi-IN", "en-IN"):
        for key in ("title", "thank_you", "step"):
            assert json.dumps(_LABELS[lang][key], ensure_ascii=False) in script, (lang, key)


def test_record_excerpt_uses_only_response_schema_fields_and_values() -> None:
    from mel_agent.generation.catalog import FOLLOW_UP_REASONS

    schema = json.loads(RESPONSE_SCHEMA.read_text(encoding="utf-8"))
    props = schema["properties"]
    script = _script()
    fields = re.findall(r'"([a-z_]+)"', re.search(r"RECORD_FIELDS = \[(.*?)\];", script, re.S).group(1))
    assert fields and set(fields) <= set(schema["required"]), set(fields) - set(schema["required"])
    status = dict(re.findall(r'(STATUS_DONE|STATUS_NEGATIVE) = "([a-z_]+)"', script))
    assert set(status.values()) <= set(props["status"]["enum"]) and len(status) == 2
    assert re.search(r'SHEET_FINISHED = "([a-z_]+)"', script).group(1) in props["sheet_outcome"]["enum"]
    assert set(re.findall(r'f: "([a-z_]+)"', script)) <= set(FOLLOW_UP_REASONS)
    assert "insight_id:" not in script  # not a response field; the schema uses source_insight_ids
    m = re.search(r"Excerpt: (\d+) of the (\d+) required fields", _html())
    assert m and int(m.group(1)) == len(fields) and int(m.group(2)) == len(schema["required"])


def test_ecr_repository_names_match_terraform() -> None:
    tf = (ROOT / "Terraform" / "main.tf").read_text(encoding="utf-8")
    names = re.findall(r'"([a-z]+)"', re.search(r"image_names\s*=\s*toset\(\[(.*?)\]\)", tf).group(1))
    assert len(names) == 3
    line = next(l for l in _script().splitlines() if "Three repositories" in l)
    for name in names:
        assert re.search(rf"\b{name}\b", line), name


def test_contradicted_claims_stay_removed() -> None:
    html = _html()
    for phrase in ("exactly once", "least privilege", "real output from our run", "ready for Digital Green",
                   "Every resolved conversation", "api, prototype, farmerloop", ">schema valid<",
                   "कीड़ों के बारे में", "about FarmerChat's advice on bugs"):
        assert phrase.lower() not in html.lower(), phrase
