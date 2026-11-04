"""Streamlit UI: a thin layer over CallSession.   streamlit run jaak_voice/app.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from jaak_voice.config import Settings  # noqa: E402
from jaak_voice.factory import build  # noqa: E402
from jaak_voice.orchestrator import CallSession  # noqa: E402

st.set_page_config(page_title="JAAK voice", page_icon="🌾", layout="wide")


@st.cache_resource
def components():
    return build(Settings.from_env())


comps = components()
ss = st.session_state
ss.setdefault("call", None)
ss.setdefault("play", None)
ss.setdefault("mic_n", 0)


def pull_turns(call: CallSession) -> None:
    """Take every pending JAAK turn; the newest one is auto-played once."""
    while True:
        t = call.next_turn()
        if t is None:
            break
        ss.play = t.audio


# ---- sidebar ----------------------------------------------------------------
with st.sidebar:
    st.title("🌾 JAAK voice")
    scenarios = comps.agent.list_scenarios()
    pick = st.selectbox("Scenario", scenarios, format_func=lambda s: s["scenario"])
    langs = [l for l in ("hi-IN", "en-IN") if l in pick["languages"]]
    lang = st.selectbox("Language", langs)
    c1, c2 = st.columns(2)
    if c1.button("Start", type="primary", use_container_width=True):
        call = CallSession(comps.engine, comps.agent, comps.stt, comps.tts)
        try:
            call.start(pick["survey_id"], pick["farmer_id"], lang)
            ss.call, ss.mic_n = call, ss.mic_n + 1
            pull_turns(call)
        except Exception as exc:  # noqa: BLE001
            ss.call = None
            st.error(f"Could not start: {type(exc).__name__}: {exc}")
    if c2.button("Stop", use_container_width=True) and ss.call and not ss.call.ended:
        ss.call.hang_up()
    st.markdown(f"**Backend:** {'🟢' if comps.backend == 'Real AWS' else '🟡'} {comps.backend}")

for b in comps.banners:
    st.warning(b)

call: CallSession | None = ss.call
main, side = st.columns([2, 1])

# ---- main panel -------------------------------------------------------------
with main:
    if call is None:
        st.info("Pick a scenario and language, then press Start.")
    else:
        for who, text in call.transcript:
            with st.chat_message("assistant" if who == "jaak" else "user"):
                st.write(text)
        cur = call.current
        if cur and cur.kind != "closing" and cur.prompt:
            st.subheader("Current question")
            st.write(cur.prompt)
            if cur.options:
                st.write(" · ".join(cur.options))
        if ss.play:
            st.audio(ss.play, format="audio/wav", autoplay=True)
            ss.play = None
        for n in call.notices[-3:]:
            st.caption(f"ℹ️ {n}")

        if call.awaiting_reply:
            rec = st.audio_input("Hold to speak", key=f"mic_{ss.mic_n}")
            if rec is not None:
                call.handle_farmer_audio(rec.getvalue())
                ss.mic_n += 1
                pull_turns(call)
                st.rerun()
            with st.form("typed", clear_on_submit=True):
                typed = st.text_input("…or type your answer")
                if st.form_submit_button("Send") and typed.strip():
                    call.handle_farmer_text(typed)
                    pull_turns(call)
                    st.rerun()
            if st.button("Send silence (timeout)"):
                call.signal_silence()
                pull_turns(call)
                st.rerun()
        elif call.ended:
            st.success("Call ended.")

# ---- side panel -------------------------------------------------------------
with side:
    st.subheader("Guardrails")
    if call:
        c = call.counters
        st.metric("Advice declined", c["advice_declined"])
        st.metric("Unclear answers (re-asks)", c["unclear_answers"])
        lat = call.last_latency_ms
        st.metric("Latency (speech end → reply ready)", "–" if lat is None else f"{lat:.0f} ms")
        record = call.result() if call.ended else None
        if record is not None:
            errs = call.validation_errors()
            (st.success if not errs else st.error)(
                "✅ Valid against response.schema.json" if not errs else f"Invalid: {errs[:3]}")
            st.json(record)
            if st.button("Save record to outputs/"):
                st.caption(call.save_result())
        elif call.ended:
            st.caption("No Response_Record (the engine does not support this ending yet).")
    else:
        st.caption("No call yet.")
