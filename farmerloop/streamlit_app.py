"""Temporary, offline viewer for the existing synthetic Regional Learning Radar."""

import streamlit as st

from farmerloop.radar.findings import build_findings, resolve_evidence
from farmerloop.radar.scenario import build_scenario


st.set_page_config(page_title="FarmerLoop demo", layout="centered")
st.title("FarmerLoop Intelligence")
st.write("Regional Learning Radar — temporary demo")
st.info("Simulated data only. Both districts and all farmers are fictional. "
        "This demo does not send messages or call AWS.")
st.write("Compare seed-access feedback from two districts and inspect the evidence.")

with st.form("run_demo"):
    language = st.selectbox("Survey language", ["English", "Hindi"])
    submitted = st.form_submit_button("Run demo", type="primary")

if submitted:
    st.session_state.pop("radar_report", None)
    try:
        with st.spinner("Running the offline scenario…"):
            scenario = build_scenario(language={"English": "en-IN", "Hindi": "hi-IN"}[language])
            st.session_state.radar_report = build_findings(scenario)
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"Could not run the demo: {exc}")

report = st.session_state.get("radar_report")
if report is None:
    st.caption("Run the demo to build 60 fictional surveys and their simulated responses.")
    st.stop()

analysis = report["analysis"]
cohorts = analysis["cohorts"]
st.caption(f"Survey language: {cohorts[0]['context']['language']} · "
           f"Simulated observation cutoff: {report['observation_cutoff']}")
st.subheader("District comparison")
rows = []
for cohort in cohorts:
    c = cohort["counts"]
    rows.append({
        "District": cohort["district"],
        "Surveys due": c["targets"],
        "Attempted": c["attempted_surveys"],
        "Delivered": c["delivered"],
        "Seed-access answers": c["barrier_answers"],
        "Reported barriers": c["barrier_reports"],
    })
st.dataframe(rows, hide_index=True)
st.caption("Seed-access answers count accepted answers to the seed-access question. "
           "Reported barriers count respondents who could not obtain the recommended seed.")
st.warning("Little or no feedback does not mean better agricultural outcomes.")

st.subheader("Radar findings")
for finding in report["findings"]:
    st.markdown(f"**{finding['district']} — {finding['title']}**")
    st.write(finding["observation"])
    st.write(finding["interpretation"])
    st.write("Suggested human review: " + finding["human_review_action"])
    with st.expander("View supporting evidence"):
        st.caption("Each entry links one fictional farmer's source insight, survey, "
                   "scheduling handoff and response records. No action is sent.")
        chains = finding["source_chains"]
        selected = st.selectbox(
            "Fictional farmer",
            range(len(chains)),
            format_func=lambda i, chains=chains: resolve_evidence(report, chains[i]["target"])["farmer_id"],
            key=finding["finding_id"],
        )
        chain = chains[selected]
        survey = resolve_evidence(report, chain["survey"])
        for item in survey["items"]:
            st.write(item["prompt"])
            st.caption(" / ".join(option["label"] for option in item.get("options") or []))
        st.json({
            "target": resolve_evidence(report, chain["target"]),
            "insight": resolve_evidence(report, chain["insight"]),
            "survey": survey,
            "handoff": resolve_evidence(report, chain["handoff"]),
            "responses": [resolve_evidence(report, ref) for ref in chain["attempts"]],
            "evidence_gap": chain["evidence_gap"],
            "barrier_answer_missing": chain["barrier_answer_missing"],
        }, expanded=False)

st.caption("Findings use demonstration thresholds, not statistical significance. "
           "This fixed scenario demonstrates the Radar; it is not a full evaluation of FarmerLoop.")
