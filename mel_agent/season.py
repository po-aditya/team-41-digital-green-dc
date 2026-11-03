"""Simulated clock, scheduler, broadcaster stub and simulated farmers.

The scheduler only sends inside the survey's send window and the send hours,
in priority order, and keeps to 1 survey per farmer per 7 days (high priority
is exempt but still counts). The broadcaster tries channels in order and falls
back on failure. Farmers in `interactive_farmers` are not auto-answered: their
surveys wait in an inbox so a person can tap the answers in the app.
"""
import random
from datetime import datetime, time, timedelta

from . import data, responses
from .rules import IST, fmt_ts, parse_ts

PRIO_RANK = {"high": 0, "normal": 1, "low": 2}
SEASON_START = datetime(2026, 11, 1, 0, 0, tzinfo=IST)
MAX_SAME_CHANNEL_TRIES = 3


class Season:
    def __init__(self, handoffs=(), start=SEASON_START, interactive_farmers=(), seed=7):
        self.now = start
        self.seed = seed
        self.interactive = set(interactive_farmers)
        self.items = {}          # survey_id -> scheduler entry
        self.responses = []      # answer records
        self.follow_up_queue = []
        self.log = []            # (time, survey_id, event)
        self.opted_out = set()
        self.cap_log = {}        # farmer_id -> [times a survey counted toward the cap]
        rules = data.rules()
        self.cap = rules["frequency_cap"]
        self.send_from = time.fromisoformat(rules["send_hours"]["from"])
        self.send_to = time.fromisoformat(rules["send_hours"]["to"])
        for h in handoffs:
            self.submit(h)

    # ---------- scheduler ----------
    def submit(self, handoff):
        sid = handoff["survey"]["survey_id"]
        self.items[sid] = {"handoff": handoff, "state": "pending", "channel_idx": 0, "attempt": 1,
                           "next_try": parse_ts(handoff["send_window"]["not_before"]), "history": []}

    def _cap_count(self, farmer, at, exclude_sid=None):
        """Distinct surveys this farmer was actually asked in the last 7 days."""
        since = at - timedelta(days=self.cap["window_days"])
        return len({sid for t, sid, _ in self.cap_log.get(farmer, []) if t > since and sid != exclude_sid})

    def _in_send_hours(self, t):
        return self.send_from <= t.time() <= self.send_to

    def _event(self, sid, text):
        self.log.append((fmt_ts(self.now), sid, text))

    def advance(self, until, step=timedelta(hours=1)):
        """Moves the clock forward, sending and expiring surveys as it goes."""
        until = min(until, datetime(2027, 4, 15, tzinfo=IST))
        while self.now < until:
            self.now = min(self.now + step, until)
            self._tick()

    def _tick(self):
        now = self.now
        due = []
        for sid, it in self.items.items():
            h = it["handoff"]
            if it["state"] == "awaiting" and now >= it["answer_deadline"]:
                self._expire_awaiting(sid, it)
            if it["state"] in ("pending", "awaiting") and now >= parse_ts(h["expires_at"]):
                if it["state"] == "awaiting":
                    self._expire_awaiting(sid, it)
                else:
                    it["state"] = "dropped_" + ("capped" if it.get("capped") else "expired")
                    self._event(sid, f"dropped: {it['state'][8:]}")
                continue
            if it["state"] == "pending" and now >= it["next_try"]:
                due.append((PRIO_RANK[h["priority"]], h["send_window"]["not_before"], sid))
        for _, _, sid in sorted(due):
            self._try_send(sid, self.items[sid])

    def _try_send(self, sid, it):
        h, now = it["handoff"], self.now
        farmer = h["survey"]["farmer_id"]
        if now > parse_ts(h["send_window"]["not_after"]):
            it["state"] = "dropped_" + ("capped" if it.get("capped") else "expired")
            self._event(sid, "window closed before it could be sent")
            return
        if not self._in_send_hours(now):
            return
        if farmer in self.opted_out:
            it["state"] = "dropped_opted_out"
            self._event(sid, "farmer opted out earlier")
            return
        if not h["frequency_cap"]["exempt"] and self._cap_count(farmer, now, sid) >= self.cap["max_surveys"]:
            it["capped"] = True
            return  # wait; maybe the cap frees up before the window closes
        self._deliver(sid, it)

    # ---------- broadcaster ----------
    def _deliver(self, sid, it):
        h, now = it["handoff"], self.now
        survey = h["survey"]
        order = h["channel_order"]
        ch = order[it["channel_idx"]]
        channel = ch["channel"]
        rng = random.Random(f"{self.seed}-{sid}-{it['channel_idx']}-{it['attempt']}")
        it["history"].append({"at": fmt_ts(now), "channel": channel, "attempt": it["attempt"]})
        self._event(sid, f"sent on {channel} (try {it['attempt']})")

        if survey["farmer_id"] in self.interactive:
            # A person answers in the app, so the survey waits until it expires.
            it.update(state="awaiting", channel=channel, sent_at=now, answer_deadline=parse_ts(h["expires_at"]))
            self._count(survey["farmer_id"], now, sid, h["frequency_cap"]["exempt"])
            return

        roll = rng.random()
        if roll < 0.22:  # a delivery or answer failure
            codes = responses.SIM_FAILURES[channel]
            code = rng.choices(list(codes), weights=list(codes.values()))[0]
            self._record(responses.failure_record(survey, channel, it["attempt"], now, code), it)
            return
        answers = simulate_answers(survey, rng, partial=roll < 0.32)
        answered_at = now + timedelta(minutes=rng.randint(5, 180))
        self._record(responses.answered_record(survey, channel, it["attempt"], now, answered_at, answers,
                                               sheet_closed_early=True), it)

    def _count(self, farmer, at, sid, exempt):
        self.cap_log.setdefault(farmer, []).append((at, sid, exempt))

    def _record(self, rec, it):
        sid = rec["survey_id"]
        self.responses.append(rec)
        if rec["counts_toward_cap"]:
            self._count(rec["farmer_id"], parse_ts(rec["timestamps"]["sent"]), sid,
                        it["handoff"]["frequency_cap"]["exempt"])
        if rec["failure_code"] == "farmer_opted_out":
            self.opted_out.add(rec["farmer_id"])
        if rec["needs_follow_up"]:
            self.follow_up_queue.append({"survey_id": sid, "farmer_id": rec["farmer_id"],
                                         "source_insight_ids": rec["source_insight_ids"],
                                         "reasons": rec["follow_up_reasons"], "at": rec["recorded_at"]})
        decision = rec["retry_decision"]
        n_channels = len(it["handoff"]["channel_order"])
        if decision == "fall_back_to_next_channel" and it["channel_idx"] + 1 < n_channels:
            it.update(state="pending", channel_idx=it["channel_idx"] + 1, attempt=1,
                      next_try=self.now + timedelta(minutes=rec["retry_after_minutes"] or 0))
            self._event(sid, f"{rec['failure_code']}: falling back to next channel")
        elif decision == "retry_same_channel" and it["attempt"] < MAX_SAME_CHANNEL_TRIES:
            it.update(state="pending", attempt=it["attempt"] + 1,
                      next_try=self.now + timedelta(minutes=max(rec["retry_after_minutes"] or 0, 60)))
            self._event(sid, f"{rec['failure_code']}: retrying same channel")
        else:
            it["state"] = rec["status"]
            self._event(sid, f"done: {rec['status']}" + (f" ({rec['failure_code']})" if rec["failure_code"] else ""))

    def _expire_awaiting(self, sid, it):
        code = "push_not_opened" if it["channel"] == "app" else "window_expired"
        it["state"] = "pending"  # let _record decide the final state
        rec = responses.failure_record(it["handoff"]["survey"], it["channel"], it["attempt"], it["sent_at"], code)
        rec["counts_toward_cap"] = True
        self.responses.append(rec)
        it["state"] = "expired"
        self._event(sid, f"no answer: {code}")

    # ---------- interactive farmer ----------
    def inbox(self, farmer_id):
        return [it for it in self.items.values()
                if it["state"] == "awaiting" and it["handoff"]["survey"]["farmer_id"] == farmer_id]

    def answer(self, survey_id, answers, closed_early=False):
        it = self.items[survey_id]
        survey = it["handoff"]["survey"]
        rec = responses.answered_record(survey, it["channel"], it["attempt"], it["sent_at"], self.now, answers,
                                        sheet_closed_early=closed_early)
        it["state"] = "answering"
        self.responses.append(rec)
        if rec["needs_follow_up"]:
            self.follow_up_queue.append({"survey_id": survey_id, "farmer_id": rec["farmer_id"],
                                         "source_insight_ids": rec["source_insight_ids"],
                                         "reasons": rec["follow_up_reasons"], "at": rec["recorded_at"]})
        it["state"] = rec["status"]
        self._event(survey_id, f"answered in app: {rec['status']}")
        return rec

    def summary(self):
        states = {}
        for it in self.items.values():
            states[it["state"]] = states.get(it["state"], 0) + 1
        return {"now": fmt_ts(self.now), "surveys": len(self.items), "states": states,
                "responses": len(self.responses), "follow_ups": len(self.follow_up_queue),
                "opted_out": len(self.opted_out)}

    def cap_violations(self):
        """Non-exempt surveys asked while the farmer's weekly cap was already full. Should be empty."""
        bad = []
        window = timedelta(days=self.cap["window_days"])
        for farmer, log in self.cap_log.items():
            first = {}
            for t, sid, exempt in sorted(log):
                first.setdefault(sid, (t, exempt))
            for sid, (t, exempt) in first.items():
                if exempt:
                    continue
                earlier = {s for s, (t2, _) in first.items() if s != sid and t - window < t2 <= t}
                if len(earlier) >= self.cap["max_surveys"]:
                    bad.append((farmer, sid))
        return bad


def simulate_answers(survey, rng, partial=False):
    """Random but plausible answers. About 1 in 5 answer sets reports a bad outcome."""
    negative = rng.random() < 0.2
    answers = {}
    for n, it in enumerate(survey["items"]):
        if partial and n == len(survey["items"]) - 1 and len(survey["items"]) > 1:
            break
        if it["type"] == "survey-scale":
            lo, hi = it["scale_min"], it["scale_max"]
            answers[it["item_id"]] = rng.randint(lo, hi) if not negative else lo
        else:
            opts = it["options"]
            bad = [o for o in opts if o.get("follow_up")]
            good = [o for o in opts if not o.get("follow_up")] or opts
            answers[it["item_id"]] = (rng.choice(bad) if (negative and bad) else rng.choice(good))["value"]
    return answers
