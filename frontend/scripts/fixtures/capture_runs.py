"""Capture real mel_agent pipeline output offline (template provider) for the
six scenarios plus a seeded slice, so the UI's fixtures are never hand-invented.

Usage: python scripts/fixtures/capture_runs.py <repo_root> <out_dir>
Writes <out_dir>/generate/<scenario>.json (the exact POST /v1/surveys result)
and prints a JSON manifest to stdout.
"""
import json
import os
import sys

repo_root = sys.argv[1]
out_dir = sys.argv[2]
os.chdir(repo_root)
os.environ.setdefault("MEL_PROVIDER", "template")
sys.path.insert(0, repo_root)

from mel_agent import pipeline  # noqa: E402

SCEN = os.path.join(repo_root, "data", "participant-pack", "json", "scenarios")
gen_dir = os.path.join(out_dir, "generate")
os.makedirs(gen_dir, exist_ok=True)

manifest = {"generated": [], "provider": "template (offline)"}
for name in sorted(os.listdir(SCEN)):
    ins_path = os.path.join(SCEN, name, "insight.json")
    if not os.path.isfile(ins_path):
        continue
    insight = json.load(open(ins_path, encoding="utf-8"))
    lang = insight.get("conversation_language", "hi-IN")
    result = pipeline.process(insight, language=lang)
    # strip wall-clock seconds so output is deterministic across runs
    result.pop("seconds", None)
    if isinstance(result.get("usage"), dict):
        result["usage"].pop("seconds", None)
        for m in result["usage"].get("by_model", {}).values():
            if isinstance(m, dict):
                m.pop("seconds", None)
    out_path = os.path.join(gen_dir, f"{name}.json")
    json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    manifest["generated"].append({"scenario": name, "status": result["status"],
                                  "survey_id": (result.get("survey") or {}).get("survey_id")})

print(json.dumps(manifest, ensure_ascii=False))
