"""LocalScenarioAdapter: Surveys and Farmer_Records from the local pack, Response_Records to a folder."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Optional

from .config import ROOT

PACK = ROOT / "data" / "participant-pack"
FIXTURES = ROOT / "tests" / "fixtures" / "jaak" / "surveys"


class LocalScenarioAdapter:
    def __init__(self, outputs_dir: Optional[Path] = None, pack_dir: Optional[Path] = None,
                 fixtures_dir: Optional[Path] = None) -> None:
        self._pack = Path(pack_dir or PACK).resolve()
        self._fixtures = Path(fixtures_dir or FIXTURES)
        self._out = Path(outputs_dir or ROOT / "outputs").resolve()
        if self._out == self._pack or self._pack in self._out.parents:
            raise ValueError("outputs folder must not be inside the participant pack")
        self._index = self._build_index()

    # -- discovery -------------------------------------------------------
    def _build_index(self) -> dict:
        idx: dict = {}

        def add(path: Path, scenario: str) -> None:
            doc = json.loads(path.read_text(encoding="utf-8"))
            entry = idx.setdefault(doc["survey_id"], {"scenario": scenario, "farmer_id": doc["farmer_id"], "files": {}})
            entry["files"].setdefault(doc["language"], path)

        scen = self._pack / "json" / "scenarios"
        for d in sorted(p for p in scen.iterdir() if p.is_dir()) if scen.exists() else []:
            for f in sorted(d.glob("survey.*.json")):
                add(f, d.name)
        for f in sorted(self._fixtures.glob("*.json")) if self._fixtures.exists() else []:
            add(f, f"fixture-{f.stem}")   # fills languages a scenario does not ship
        return idx

    def list_scenarios(self) -> list:
        return [{"scenario": e["scenario"], "survey_id": sid, "farmer_id": e["farmer_id"],
                 "languages": sorted(e["files"])} for sid, e in sorted(self._index.items(), key=lambda kv: kv[1]["scenario"])]

    # -- AgentAdapter ----------------------------------------------------
    def get_survey(self, survey_id: str, language: Optional[str] = None) -> dict:
        entry = self._index.get(survey_id)
        if entry is None:
            raise LookupError("unknown survey")
        lang = language or ("en-IN" if "en-IN" in entry["files"] else sorted(entry["files"])[0])
        path = entry["files"].get(lang)
        if path is None:
            raise LookupError(f"no {lang} survey for this scenario")
        return json.loads(path.read_text(encoding="utf-8"))

    def get_farmer(self, farmer_id: str) -> dict:
        with open(self._pack / "data" / "farmers.csv", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("farmer_id") == farmer_id:
                    return {"farmer_id": row["farmer_id"], "language": row["language"]}   # nothing else leaves
        raise LookupError("unknown farmer")

    def submit_response(self, response_record: dict) -> str:
        self._out.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(response_record.get("response_key", "response")))
        path = self._out / f"{name}-{response_record.get('language', 'xx')}.json"
        path.write_text(json.dumps(response_record, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def validate_response(self, response_record: dict) -> list:
        from mel_agent import data   # schemas with cross-file refs, read-only
        return [f"{'/'.join(str(p) for p in e.absolute_path) or '/'}: {e.validator}"
                for e in data.validator("response").iter_errors(response_record)]
