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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
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
