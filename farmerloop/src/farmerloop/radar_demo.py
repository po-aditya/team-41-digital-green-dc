"""Offline synthetic scenario and deterministic Radar analysis."""

import argparse
import json

from .radar.scenario import VARIANTS, build_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("hi-IN", "en-IN"), default="hi-IN")
    parser.add_argument("--variant", choices=VARIANTS, default="base")
    parser.add_argument("--json", action="store_true", help="print full synthetic envelope to stdout")
    parser.add_argument("--analyze", action="store_true", help="compute metrics and detection signals from records")
    parser.add_argument("--findings", action="store_true", help="build evidence-backed findings (includes analysis)")
    args = parser.parse_args()
    scenario = build_scenario(language=args.language, variant=args.variant)
    if args.findings:
        from .radar.findings import build_findings
        report = build_findings(scenario)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(report["label"])
            for finding in report["findings"]:
                print(f"\n{finding['finding_id']} — {finding['title']}")
                print(finding["observation"])
                print(finding["interpretation"])
                print("Human review:", finding["human_review_action"])
                print("Evidence assessment:", finding["evidence_assessment"])
                for limitation in finding["limitations"]:
                    print("  Limitation:", limitation)
                print("Source chains:", len(finding["source_chains"]))
            print("Use --findings --json for all source records and resolvable evidence references.")
        return
    if args.analyze:
        from .radar.analyze import analyze
        result = analyze(scenario)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("FarmerLoop — SYNTHETIC Radar analysis (offline)")
            print(result["threshold_label"])
            print("Comparison:", result["comparison_status"])
            for cohort in result["cohorts"]:
                print(cohort["district"])
                for name, rate in cohort["rates"].items():
                    print(f"  {name}: {rate['numerator']}/{rate['denominator']} ({rate['unit']})")
                print("  Signals:", ", ".join(cohort["signals"]) or "none")
            print("Diagnostics:", len(result["diagnostics"]))
            print("Low feedback is not evidence of better agricultural outcomes.")
        return
    if args.json:
        print(json.dumps(scenario.dump(), ensure_ascii=False, indent=2))
        return
    print("FarmerLoop — SYNTHETIC regional scenario (Checkpoint 1, offline)")
    print(scenario.description)
    print(f"Built {len(scenario.targets)} targets, {len(scenario.surveys)} surveys, "
          f"{len(scenario.responses)} response records through the existing pipeline.")
    print(f"Observation cutoff: {scenario.observation_cutoff}")
    print("Fixture expectations only — use --analyze or --findings for computed results:")
    for district, expected in scenario.expected.items():
        print(f"  District {district}: {json.dumps(expected, sort_keys=True)}")
    print(scenario.variant_notes)
    print("Source trace example:")
    print(json.dumps(scenario.targets[0], indent=2))
    print("Use --json for all synthetic source records, decisions, surveys and responses.")


if __name__ == "__main__":
    main()
