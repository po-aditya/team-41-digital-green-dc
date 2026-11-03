"""Timing/window math tests."""

from datetime import date

from farmerloop.timing import SEASON_END, compute_window, earliest_possible_start


def test_window_respects_documented_times_and_min_width():
    w = compute_window("2026-12-04T09:00:00+05:30", "two_to_five_days", 2)
    assert w is not None
    assert w.not_before_iso().endswith("T07:00:00+05:30")
    assert w.not_after_iso().endswith("T19:00:00+05:30")
    assert (w.end - w.start).days >= 2


def test_window_never_before_action_window_end():
    # action window 5 days pushes the start to at least advice+5.
    w = compute_window("2026-12-04T09:00:00+05:30", "two_to_five_days", 5)
    assert w is not None
    assert w.start >= date(2026, 12, 9)


def test_window_clamped_to_season_and_infeasible_returns_none():
    # Start before season end but end would spill past; still schedulable if
    # >= 2 days remain. Here start is 2027-03-30, 2 days to season end.
    w = compute_window("2027-03-28T09:00:00+05:30", "next_day", None)
    # start = advice+1 = 2027-03-29, end clamped to 2027-03-31 -> width 2 OK.
    assert w is not None
    assert w.end <= SEASON_END

    # A start at/after the cutoff is not schedulable.
    w2 = compute_window("2027-03-31T09:00:00+05:30", "next_day", None)
    assert w2 is None


def test_earliest_start_independent_of_end_clamp():
    es = earliest_possible_start("2027-03-30T09:00:00+05:30", "three_to_ten_days", 9)
    # advice + max(action_window=9, start_off=3) = advice+9 = 2027-04-08.
    assert es == date(2027, 4, 8)
    assert es > SEASON_END
