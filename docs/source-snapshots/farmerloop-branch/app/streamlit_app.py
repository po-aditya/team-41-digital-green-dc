"""JAAKS, the MEL survey agent for FarmerChat: demo app.

  streamlit run app/streamlit_app.py
"""
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mel_agent import config, data, pipeline, rules, season  # noqa: E402
from mel_agent.rules import IST  # noqa: E402

# Logo: put the image at app/assets/jaaks-logo.png. Until then the app falls back to an emoji.
LOGO = Path(__file__).resolve().parent / "assets" / "jaaks-logo.png"
HAS_LOGO = LOGO.exists()
st.set_page_config(page_title="JAAKS · MEL Survey Agent", page_icon=str(LOGO) if HAS_LOGO else "🌱", layout="wide")
if HAS_LOGO:
    st.logo(str(LOGO), size="large")
st.markdown("""
<style>
/* ---------- phone frame: a keyed st.container whose key starts with "phone_" ---------- */
div[class*="st-key-phone_"]{width:360px !important;max-width:360px;margin:0 auto;min-height:720px;
  background:linear-gradient(180deg,#e7f3ec 0%,#d9ebe0 100%);border:12px solid #0d0d0d;border-radius:46px;
  box-shadow:0 0 0 2px #2b2b2b,0 30px 60px -20px #000c;padding:0 0 10px 0;gap:0 !important;overflow:hidden;
  position:relative;justify-content:flex-start}
div[class*="st-key-phone_"] > div{width:100% !important}
.ph-status{display:flex;justify-content:space-between;align-items:center;padding:10px 22px 4px;font:600 13px system-ui;
  color:#111;background:#f4faf6}
.ph-notch{width:110px;height:26px;background:#0d0d0d;border-radius:0 0 16px 16px;position:absolute;left:50%;
  transform:translateX(-50%);top:0}
.ph-appbar{display:flex;align-items:center;gap:10px;background:#1f9d5c;color:#fff;padding:12px 16px;font:700 15px system-ui}
.ph-appbar .av{width:30px;height:30px;border-radius:50%;background:#ffffff33;display:grid;place-items:center;font-size:16px}
.ph-appbar small{display:block;font-weight:400;font-size:11px;opacity:.85}
.ph-chat{padding:12px 12px 8px;font:13px/1.35 system-ui;color:#13241b;opacity:.45;min-height:150px}
.ph-chat .lbl{font-size:10px;text-transform:uppercase;letter-spacing:1px;text-align:center;margin-bottom:6px}
.ph-b{background:#fff;border-radius:14px 14px 14px 4px;padding:8px 10px;margin:0 30px 8px 0;box-shadow:0 1px 1px #0001}
.ph-b.me{background:#c9f0d8;border-radius:14px 14px 4px 14px;margin:0 0 8px 30px}
/* bottom sheet */
div[class*="st-key-sheet_"]{background:#fff;border-radius:24px 24px 0 0;margin-top:auto;padding:8px 18px 14px;
  box-shadow:0 -8px 24px #0002;gap:.45rem !important}
.ph-grab{width:42px;height:5px;border-radius:5px;background:#d0d7d3;margin:2px auto 8px}
.ph-ttl{display:flex;justify-content:space-between;gap:8px;font:12px system-ui;color:#5c7366}
.ph-prog{height:5px;background:#e3ece6;border-radius:5px;margin:8px 0 10px;overflow:hidden}
.ph-prog b{display:block;height:100%;background:#1f9d5c;border-radius:5px}
.ph-q{font:700 18px/1.35 system-ui;color:#13241b;margin:2px 0 6px}
.ph-done{text-align:center;padding:26px 6px 10px;font:600 16px/1.45 system-ui;color:#13241b}
.ph-done .tick{font-size:44px;display:block;margin-bottom:8px}
div[class*="st-key-sheet_"] button[data-testid="stBaseButton-secondary"]{width:100%;justify-content:flex-start;
  border:1.5px solid #cfe0d6;border-radius:14px;padding:12px 14px;min-height:48px;background:#fff;color:#13241b;
  font-weight:600;font-size:15px}
div[class*="st-key-sheet_"] button[data-testid="stBaseButton-secondary"]:hover{border-color:#1f9d5c;background:#eef8f2;color:#13241b}
div[class*="st-key-sheet_"] button[data-testid="stBaseButton-secondary"] p{font-size:15px}
div[class*="st-key-sheet_"] button[data-testid="stBaseButton-tertiary"]{color:#5c7366;font-size:14px}
div[class*="st-key-sheet_"] button[data-testid="stBaseButton-primary"]{width:100%;border-radius:14px;min-height:46px;
  background:#1f9d5c;border-color:#1f9d5c}
/* lock-screen notification */
.ph-lock{padding:40px 18px 10px;text-align:center;color:#fff;background:linear-gradient(180deg,#24493a,#16261e);
  min-height:430px}
.ph-lock .clock{font:200 64px system-ui;letter-spacing:-2px}
.ph-lock .date{font:500 14px system-ui;opacity:.85;margin-bottom:28px}
.ph-notif{background:#ffffffe6;color:#13241b;border-radius:18px;padding:12px 14px;text-align:left;font:13px/1.35 system-ui}
.ph-notif .app{display:flex;justify-content:space-between;font-size:11px;color:#5c7366;margin-bottom:4px}
.ph-notif b{font-size:14px}
div[class*="st-key-lockbtn_"]{padding:0 18px;background:#16261e;margin-top:-1px}
div[class*="st-key-lockbtn_"] button{width:100%;border-radius:14px;background:#ffffff22;color:#fff;border:1px solid #ffffff55}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;margin-right:4px}
.ok{background:#1f9d5c22;color:#1f9d5c}.bad{background:#ff6b6b22;color:#d33}.warn{background:#ffb54733;color:#a66300}
</style>""", unsafe_allow_html=True)

# Sheet wording from data/participant-pack/json/scenarios/*/render/*/app.json
SHEET_TEXT = {
    "hi-IN": {"title": "आपको मिली सलाह पर एक छोटा सवाल", "of": "{n} में से {i}", "skip": "छोड़ें", "close": "बंद करें",
              "thanks": "धन्यवाद। आपके जवाब से हम और अच्छी सलाह दे पाएँगे।", "open": "खोलें", "ok": "ठीक है",
              "closed": "सर्वे बंद किया गया।", "now": "अभी"},
    "en-IN": {"title": "A quick question about the advice you got", "of": "{i} of {n}", "skip": "Skip", "close": "Close",
              "thanks": "Thank you. Your answers help us give better advice.", "open": "Open", "ok": "OK",
              "closed": "Survey closed.", "now": "now"},
}


def pill(text, kind="ok"):
    return f'<span class="pill {kind}">{text}</span>'


@st.cache_data
def insights_df():
    rows = []
    for i in data.insights():
        d = rules.decide(i)
        rows.append({"insight_id": i["insight_id"], "farmer_id": i["farmer_id"], "date": i["created_at"][:10],
                     "crop": (i.get("asset") or {}).get("name"), "concern": i.get("concern"),
                     "resolution": i.get("resolution_type"), "severity": i.get("severity"),
                     "language": i.get("conversation_language"), "decision": "survey" if d.survey else "no survey",
                     "rule": d.rule, "query": i.get("query_summary")})
    return pd.DataFrame(rows)


def _safe_key(s):
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


def _when(ts):
    """'2026-12-06T09:00:00+05:30' -> (time, date) strings for the phone's status bar."""
    try:
        d = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        d = datetime.now(IST)
    return d.strftime("%H:%M"), d.strftime("%A, %d %B")


def sheet(survey, key, on_done=None, chat=None, clock=None, channel="app"):
    """Shows the survey on a simulated phone, the way FarmerChat's app presents it: a push
    notification first, then a bottom sheet over the chat with one question per step.

    chat:  (farmer question, FarmerChat advice) shown faded behind the sheet
    clock: ISO time shown in the status bar (defaults to the send window opening)
    """
    lang = survey["language"] if survey["language"] in SHEET_TEXT else "en-IN"
    t = SHEET_TEXT[lang]
    sk = _safe_key(f"s_{key}")
    state = st.session_state.setdefault(sk, {"step": -1, "answers": {}, "closed": False})
    items = survey["items"]
    hhmm, day = _when(clock or survey["send_window"]["not_before"])

    def finish():
        if on_done and not state.get("sent"):
            state["sent"] = True
            on_done(state["answers"])

    with st.container(key=f"phone_{sk}"):
        st.markdown(f'<div class="ph-notch"></div><div class="ph-status"><span>{hhmm}</span>'
                    f'<span>▂▄▆ 4G &nbsp;🔋</span></div>', unsafe_allow_html=True)

        # 1. lock screen with the push notification
        if state["step"] == -1:
            st.markdown(f'<div class="ph-lock"><div class="clock">{hhmm}</div><div class="date">{html.escape(day)}</div>'
                        f'<div class="ph-notif"><div class="app"><span>🌾 FarmerChat</span><span>{t["now"]}</span></div>'
                        f'<b>{html.escape(t["title"])}</b><br>{html.escape(items[0]["prompt"])}</div></div>',
                        unsafe_allow_html=True)
            with st.container(key=f"lockbtn_{sk}"):
                if st.button(f"👆 {t['open']}", key=f"{sk}_open"):
                    state["step"] = 0
                    st.rerun()
            return None

        # 2. the FarmerChat chat, faded behind the sheet
        bubbles = ""
        if chat:
            q, a = chat
            bubbles = (f'<div class="lbl">earlier chat (summary)</div>'
                       f'<div class="ph-b me">{html.escape(q or "")}</div><div class="ph-b">{html.escape(a or "")}</div>')
        st.markdown(f'<div class="ph-appbar"><div class="av">🌾</div><div>FarmerChat<small>{channel} · {lang}</small></div></div>'
                    f'<div class="ph-chat">{bubbles}</div>', unsafe_allow_html=True)

        # 3. the bottom sheet
        with st.container(key=f"sheet_{sk}"):
            st.markdown('<div class="ph-grab"></div>', unsafe_allow_html=True)
            if state["closed"] or state["step"] >= len(items):
                msg = t["closed"] if state["closed"] and not state["answers"] else t["thanks"]
                st.markdown(f'<div class="ph-done"><span class="tick">{"✅" if state["answers"] else "👋"}</span>'
                            f'{html.escape(msg)}</div>', unsafe_allow_html=True)
                finish()
                if st.button("↺ Show again (demo)", key=f"{sk}_reset", type="tertiary"):
                    st.session_state.pop(sk)
                    st.rerun()
                return state["answers"]

            n, it = state["step"], items[state["step"]]
            st.markdown(f'<div class="ph-ttl"><span>{html.escape(t["title"])}</span>'
                        f'<span>{t["of"].format(i=n + 1, n=len(items))}</span></div>'
                        f'<div class="ph-prog"><b style="width:{(n + 1) / len(items) * 100:.0f}%"></b></div>'
                        f'<div class="ph-q">{html.escape(it["prompt"])}</div>', unsafe_allow_html=True)
            if it["type"] == "survey-scale":
                v = st.slider("answer", it["scale_min"], it["scale_max"], key=f"{sk}_{n}_scale",
                              label_visibility="collapsed")
                if st.button(t["ok"], key=f"{sk}_{n}_ok", type="primary"):
                    state["answers"][it["item_id"]] = int(v)
                    state["step"] += 1
                    st.rerun()
            else:
                for o in it["options"]:
                    if st.button(o["label"], key=f"{sk}_{n}_{o['value']}"):
                        state["answers"][it["item_id"]] = o["value"]
                        state["step"] += 1
                        st.rerun()
            c1, c2 = st.columns(2)
            if c1.button(t["skip"], key=f"{sk}_{n}_skip", type="tertiary"):
                state["step"] += 1
                st.rerun()
            if c2.button(t["close"], key=f"{sk}_{n}_close", type="tertiary"):
                state["closed"] = True
                st.rerun()
    # Not shown to the farmer: which answers trigger a follow-up.
    flagged = [f"{o['label']} → {o['follow_up']}" for o in it.get("options", []) if o.get("follow_up")]
    if it.get("follow_up_reason"):
        flagged.append(f"≤ {it['follow_up_at_or_below']} → {it['follow_up_reason']}")
    if flagged:
        st.caption("Reviewer view, hidden from the farmer. These answers trigger a follow-up: " + "; ".join(flagged))
    return None


def show_result(r, insight=None):
    d = r["decision"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Decision", "Survey" if d["survey"] else "No survey", d["rule"])
    c2.metric("Status", r["status"])
    c3.metric("Time", f"{r['seconds']:.1f} s")
    c4.metric("Tokens", f"{r['usage']['input_tokens'] + r['usage']['output_tokens']:,}")
    if not d["survey"]:
        st.info(f"**{d['reason_code']}**: {d['reason']}")
        st.json(r["no_survey"])
        return
    if r.get("error"):
        st.error(r["error"])
        return
    left, right = st.columns([1, 1.2])
    with left:
        if r["survey"]:
            ins = insight or {}
            sheet(r["survey"], key=r["survey"]["survey_id"] + r["survey"]["language"],
                  chat=(ins.get("query_summary"), ins.get("advice_summary")),
                  channel=d["channel_order"][0]["channel"] if d.get("channel_order") else "app")
    with right:
        w = d["send_window"]
        st.markdown(f"**Send window** {w['not_before'][:16].replace('T', ' ')} → {w['not_after'][:16].replace('T', ' ')}  \n"
                    f"**Priority** {d['priority']} · **Channels** " + " → ".join(c["channel"] for c in d["channel_order"]))
        chk = r.get("check") or {}
        j = chk.get("judge") or {}
        if chk:
            st.markdown(
                pill("schema valid" if not chk.get("deterministic") else "schema problems", "ok" if not chk.get("deterministic") else "bad")
                + pill(f"relevance {j.get('relevance_score', 0):.2f}", "ok" if j.get("relevance_score", 0) >= config.MIN_RELEVANCE else "bad")
                + pill("no new advice" if not j.get("gives_new_advice") else "gives advice", "ok" if not j.get("gives_new_advice") else "bad")
                + pill("no personal info" if not j.get("asks_personal_info") else "asks personal info", "ok" if not j.get("asks_personal_info") else "bad")
                + pill("scheduled" if chk.get("passed") else "NOT scheduled", "ok" if chk.get("passed") else "bad"),
                unsafe_allow_html=True)
            for reason in chk.get("reasons", []):
                st.warning(reason)
        st.caption("Rationale (reviewers only): " + (r["survey"] or {}).get("rationale", ""))
        tabs = st.tabs(["Survey JSON", "Scheduler hand-off", "Self-check"])
        tabs[0].json(r["survey"])
        tabs[1].json(r["handoff"] or {"note": "not handed off"})
        tabs[2].json(chk)


# ------------------------------------------------------------------ pages
head_logo, head_text = st.columns([1, 12], vertical_alignment="center")
if HAS_LOGO:
    head_logo.image(str(LOGO), width=72)
else:
    head_logo.markdown("<div style='font-size:52px'>🌱</div>", unsafe_allow_html=True)
head_text.title("JAAKS")
head_text.markdown("**MEL Survey Agent** for FarmerChat")
st.caption(f"Writer {config.WRITER_MODEL} · Checker {config.CHECKER_MODEL} · {config.AWS_REGION} · synthetic data only")
page = st.sidebar.radio("Page", ["Agent", "Season simulation", "Evaluation", "Dataset"])

if page == "Agent":
    st.subheader("Run the agent on one insight")
    df = insights_df()
    src = st.radio("Pick from", ["Worked examples", "Golden set", "All insights", "Paste JSON"], horizontal=True)
    insight = None
    if src == "Worked examples":
        ex = {e["name"]: e["insight"] for e in data.scenario_examples()}
        insight = ex[st.selectbox("Example", list(ex))]
    elif src == "Golden set":
        g = {f"{x['golden_id']} · {x['insight']['resolution_type']} · {x['insight']['query_summary'][:60]}": x for x in data.golden()}
        choice = g[st.selectbox("Golden case", list(g))]
        insight = choice["insight"]
        with st.expander("Expected by Digital Green"):
            st.json(choice["expected"])
    elif src == "All insights":
        f1, f2, f3 = st.columns(3)
        crop = f1.selectbox("Crop", ["any"] + sorted(df["crop"].dropna().unique()))
        res = f2.selectbox("Resolution", ["any"] + sorted(df["resolution"].dropna().unique()))
        dec = f3.selectbox("Decision", ["any", "survey", "no survey"])
        sub = df
        if crop != "any":
            sub = sub[sub.crop == crop]
        if res != "any":
            sub = sub[sub.resolution == res]
        if dec != "any":
            sub = sub[sub.decision == dec]
        st.caption(f"{len(sub):,} insights")
        if len(sub):
            pick = st.selectbox("Insight", (sub.insight_id + " · " + sub.query.str[:70]).tolist()[:500])
            insight = data.insights_by_id()[pick.split(" · ")[0]]
    else:
        txt = st.text_area("Insight JSON", height=220)
        if txt.strip():
            try:
                insight = json.loads(txt)
            except json.JSONDecodeError as e:
                st.error(f"Not valid JSON: {e}")
    if insight:
        with st.expander("Insight", expanded=False):
            st.json(insight)
        st.markdown(f"**Farmer asked:** {insight.get('query_summary')}  \n**FarmerChat advised:** {insight.get('advice_summary')}")
        lang = st.radio("Survey language", ["hi-IN", "en-IN"], horizontal=True,
                        index=0 if insight.get("conversation_language") == "hi-IN" else 1)
        key = f"result-{insight.get('insight_id')}-{lang}"
        if st.button("▶ Run agent", type="primary"):
            with st.spinner("Deciding, writing and checking the survey..."):
                st.session_state[key] = pipeline.process(insight, language=lang)
        if key in st.session_state:
            show_result(st.session_state[key], insight)

elif page == "Season simulation":
    st.subheader("Scheduler, broadcaster and simulated farmers, November to March")
    sources = {}
    full = config.OUT / "results.jsonl"
    if full.exists():
        sources["Full dataset run (out/results.jsonl)"] = full
    for p in sorted(config.REPORTS.glob("*.json"), reverse=True):
        sources[f"Golden-set run: {p.stem}"] = p
    if not sources:
        st.warning("No generated surveys yet. Run `python -m mel_agent.cli generate` or an evaluation first.")
        st.stop()
    src = st.selectbox("Surveys to schedule", list(sources))
    path = sources[src]
    if path.suffix == ".jsonl":
        results = data.read_jsonl(path)
        handoffs = [r["handoff"] for r in results if r.get("handoff")]
        rejected = sum(1 for r in results if r.get("status") in ("rejected", "error", "writer_skipped"))
    else:
        rep = json.loads(path.read_text(encoding="utf-8"))
        handoffs = []
        for c in rep["cases"]:
            if c.get("scheduled") and c.get("survey"):
                ins = data.insights_by_id().get(c["insight_id"]) or next(g["insight"] for g in data.golden() if g["insight_id"] == c["insight_id"])
                d = rules.decide(ins)
                handoffs.append(rules.build_handoff(c["survey"], d, ins))
        rejected = sum(1 for c in rep["cases"] if "scheduled" in c and not c["scheduled"])
    farmers_with = sorted({h["survey"]["farmer_id"] for h in handoffs})
    if "season" not in st.session_state or st.session_state.get("season_src") != src:
        st.session_state.season_src = src
        st.session_state.demo_farmer = farmers_with[0] if farmers_with else None
        st.session_state.season = season.Season(handoffs, interactive_farmers=[st.session_state.demo_farmer])
    S = st.session_state.season
    c1, c2, c3, c4, c5 = st.columns(5)
    if c1.button("+1 day"):
        S.advance(S.now + timedelta(days=1))
    if c2.button("+1 week"):
        S.advance(S.now + timedelta(days=7))
    if c3.button("+1 month"):
        S.advance(S.now + timedelta(days=30))
    if c4.button("To end of season"):
        S.advance(datetime(2027, 4, 10, tzinfo=IST))
    if c5.button("Restart"):
        st.session_state.pop("season")
        st.rerun()
    summ = S.summary()
    st.markdown(f"### 🕒 {S.now.strftime('%a %d %b %Y, %H:%M')} IST")
    m = st.columns(6)
    m[0].metric("Scheduled surveys", summ["surveys"])
    m[1].metric("Not scheduled (failed checks)", rejected)
    m[2].metric("Answer records", summ["responses"])
    m[3].metric("Follow-ups needed", summ["follow_ups"])
    m[4].metric("Farmers opted out", summ["opted_out"])
    m[5].metric("Weekly cap violations", len(S.cap_violations()))
    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Survey states**")
        if summ["states"]:
            st.bar_chart(pd.Series(summ["states"]).sort_values(ascending=False))
        st.markdown("**Recent events**")
        st.dataframe(pd.DataFrame(S.log[-200:][::-1], columns=["time", "survey", "event"]), height=260, hide_index=True)
    with right:
        st.markdown(f"**📱 Demo farmer's phone: {st.session_state.demo_farmer}** (you answer; everyone else is simulated)")
        inbox = S.inbox(st.session_state.demo_farmer)
        if not inbox:
            nxt = sorted((it["handoff"]["send_window"]["not_before"], sid) for sid, it in S.items.items()
                         if it["handoff"]["survey"]["farmer_id"] == st.session_state.demo_farmer and it["state"] == "pending")
            st.info("No survey waiting. " + (f"Next one opens {nxt[0][0][:16].replace('T', ' ')}." if nxt else "None left this season."))
        else:
            it = inbox[0]
            sv = it["handoff"]["survey"]
            st.caption(f"{sv['survey_id']} via {it['channel']} · about {', '.join(sv['source_insight_ids'])}")

            if it["channel"] not in ("app", "web"):
                st.caption(f"This survey went out on {it['channel']}. The phone below shows the app version of it; "
                           "the questions and answer choices are the same on every channel.")

            def done(ans, sid=sv["survey_id"]):
                if ans:
                    rec = S.answer(sid, ans, closed_early=len(ans) < len(sv["items"]))
                else:
                    rec = S.dismiss(sid)
                st.session_state["last_record"] = rec
            src_ins = data.insights_by_id().get(sv["source_insight_ids"][0], {})
            sheet(sv, key="season-" + sv["survey_id"], on_done=done, clock=rules.fmt_ts(S.now),
                  chat=(src_ins.get("query_summary"), src_ins.get("advice_summary")), channel=it["channel"])
        if st.session_state.get("last_record"):
            with st.expander("Last answer record (response.schema.json)"):
                rec = st.session_state["last_record"]
                errs = data.schema_errors("response", rec)
                st.markdown(pill("valid answer record") if not errs else pill(f"{len(errs)} schema errors", "bad"), unsafe_allow_html=True)
                st.json(rec)
        st.markdown("**Follow-up queue** (answers saying the advice failed or harm happened)")
        st.dataframe(pd.DataFrame(S.follow_up_queue[-100:][::-1]), height=200, hide_index=True)
    if S.responses:
        st.markdown("**Outcomes by channel**")
        st.dataframe(pd.crosstab(pd.Series([r["channel"] for r in S.responses], name="channel"),
                                 pd.Series([r["status"] for r in S.responses], name="status")))

elif page == "Evaluation":
    st.subheader("Scores against Digital Green's golden set")
    hist = config.REPORTS / "history.jsonl"
    if not hist.exists():
        st.warning("No evaluation runs yet. Run `python -m mel_agent.cli eval --name v1`.")
        st.stop()
    runs = data.read_jsonl(hist)
    rows = [{"run": r["name"], "policy": r["policy"], "language": r["language"], **r["scores"],
             "sec/survey": r.get("seconds_per_survey_avg")} for r in runs]
    tdf = pd.DataFrame(rows)
    st.dataframe(tdf, hide_index=True)
    metrics = [c for c in ["decision_accuracy", "rule_accuracy", "window_exact", "format_ok", "relevance",
                           "reference_intent", "safety"] if c in tdf]
    st.markdown("**Hill-climb across runs**")
    st.line_chart(tdf.set_index("run")[metrics])
    reports = sorted(config.REPORTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    rep = json.loads(st.selectbox("Report", reports, format_func=lambda p: p.stem).read_text(encoding="utf-8"))
    st.json({"scores": rep["scores"], "speed": rep["speed"], "status": rep.get("status_counts")}, expanded=False)
    cases = pd.DataFrame([{k: c.get(k) for k in ("golden_id", "expected_rule", "agent_rule", "window_exact",
                                                 "relevance", "intent", "safe", "status", "judge_notes")}
                          for c in rep["cases"]])
    st.dataframe(cases, hide_index=True, height=360)
    gid = st.selectbox("Inspect a case", [c["golden_id"] for c in rep["cases"] if c.get("survey")] or ["-"])
    case = next((c for c in rep["cases"] if c["golden_id"] == gid), None)
    if case and case.get("survey"):
        g = next(x for x in data.golden() if x["golden_id"] == gid)
        a, b = st.columns(2)
        a.markdown("**Digital Green reference**")
        a.json(g["expected"])
        b.markdown("**Agent**")
        b.json(case["survey"])

else:
    st.subheader("Practice dataset")
    df = insights_df()
    m = st.columns(4)
    m[0].metric("Insights", f"{len(df):,}")
    m[1].metric("Farmers", df.farmer_id.nunique())
    m[2].metric("Get a survey", f"{(df.decision == 'survey').sum():,}")
    m[3].metric("Golden cases", len(data.golden()))
    a, b = st.columns(2)
    a.markdown("**Decision rule**")
    a.bar_chart(df.rule.value_counts().sort_index())
    b.markdown("**Surveys by month**")
    b.bar_chart(df[df.decision == "survey"].date.str[:7].value_counts().sort_index())
    st.markdown("**Rule calibration (baseline → calibrated)**")
    for n in rules.CALIBRATION_NOTES:
        st.markdown(f"- {n}")
    st.dataframe(df, hide_index=True, height=400)
