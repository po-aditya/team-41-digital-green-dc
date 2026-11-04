import json
import subprocess
import sys
from pathlib import Path

import pytest

from mel_agent.budget import BudgetController
from mel_agent.demo import run_demo
from mel_agent.llm.pricing import PricingTable

ROOT = Path(__file__).resolve().parents[1]


def test_demo_all_cases_pass_offline(pipeline, settings):
    budget = BudgetController(pipeline.store, settings, PricingTable.load(settings.pricing_file))
    result = run_demo(pipeline, budget, settings)
    assert result["all_passed"], {k: v for k, v in result["cases"].items() if not v["passed"]}
    assert set(result["cases"]) == {"1_valid_eligible", "2_junk_suppressed", "3_invalid_quarantined", "4_critical_human",
                                    "5_temporal_rejected", "6_end_to_end_delivery", "7_idempotency", "8_budget_cutoff"}
    assert result["cases"]["8_budget_cutoff"]["refused"]["committed_usd"] <= 225
    assert result["cases"]["6_end_to_end_delivery"]["final_state"] == "answered"


def test_cli_evaluate_and_demo_subprocess(tmp_path):
    env = {"MEL_DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-m", "mel_agent", "evaluate", "--out", str(tmp_path / "rep")], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    rep = json.loads((tmp_path / "rep" / "golden_evaluation.json").read_text())
    assert rep["eligibility"]["tp"] == 93 and (tmp_path / "rep" / "golden_evaluation.md").exists()
    r = subprocess.run([sys.executable, "-m", "mel_agent", "demo", "--out", str(tmp_path / "demo")], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "demo" / "demo_result.json").read_text())["all_passed"]


def test_cli_refuses_bedrock_without_opt_in(tmp_path):
    env = {"MEL_DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-m", "mel_agent", "generate", "--provider", "bedrock", "--limit", "1"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "MEL_ALLOW_PAID_INFERENCE" in r.stderr
