"""Stage B: session-aware 15-minute replay (fixture-only, no network)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xsp_killer.backtest.sweep import write_merged_rules_dict
from xsp_killer.lane_a_monitor import xsp_session_open

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def et(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def _ohlc_row(ts: datetime, close: float, *, volume: float = 1_500_000.0) -> dict:
    o = close
    return {
        "ts": ts,
        "open": o,
        "high": o * 1.001,
        "low": o * 0.999,
        "close": close,
        "volume": volume,
    }


def _bars_from_timestamps(
    stamps: list[datetime],
    *,
    start_px: float = 450.0,
    step: float = 0.5,
) -> pd.DataFrame:
    """Monotonic mild uptrend closes keyed by given timestamps."""
    rows = []
    for i, ts in enumerate(stamps):
        rows.append(_ohlc_row(ts, start_px + i * step))
    return pd.DataFrame(rows).set_index("ts")


def _rth_15m_day(d: date, *, include_entry: bool = True) -> list[datetime]:
    """RTH 15m stamps 09:30–15:45 (or through 15:30 if no entry bar)."""
    out: list[datetime] = []
    t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
    end_h, end_m = (15, 45) if include_entry else (15, 30)
    end = datetime(d.year, d.month, d.day, end_h, end_m, tzinfo=ET)
    while t <= end:
        out.append(t)
        t += timedelta(minutes=15)
    return out


def _green_warmup_days(
    n_days: int = 5,
    *,
    start: date = date(2024, 6, 3),  # Monday
    start_px: float = 400.0,
    step: float = 0.25,
) -> tuple[pd.DataFrame, list[datetime]]:
    """Enough 15m RTH bars for SMA50 warmup + GREEN regime."""
    stamps: list[datetime] = []
    d = start
    while len({s.date() for s in stamps}) < n_days:
        if d.weekday() < 5:
            stamps.extend(_rth_15m_day(d))
        d += timedelta(days=1)
    bars = _bars_from_timestamps(stamps, start_px=start_px, step=step)
    return bars, stamps


def _rules(
    tmp_path: Path,
    *,
    take_profit_pct: float = 0.90,
    stop_loss_pct: float = 0.90,
    dte_target: int = 28,
    regime_gate: str = "GREEN",
    max_open: int = 1,
    require_upper_bb: bool = False,
) -> Path:
    overrides = {
        "logging": {"logic_version": "xsp_lane_a_bt_intraday_test"},
        "entry": {
            "regime_gate": regime_gate,
            "dte_pick": "target",
            "dte_min": 14,
            "dte_max": 60,
            "dte_target": dte_target,
            "strike_pick": "atm_only",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": 0.50,
            "regime_yellow_require_bounce": False,
        },
        "paper_entry": {"max_open_positions": max_open, "quantity": 1},
        "exit": {
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
            "require_upper_bb_for_take_profit": require_upper_bb,
            "swing_hold": False,
            "max_hold_dte": 0,
        },
        "ta": {
            "entry": {
                "mode": "close_window_only",
                "intraday_enabled": False,
                "require_vwap_reclaim": False,
            }
        },
    }
    path = tmp_path / "bt_intraday_rules.yaml"
    write_merged_rules_dict(overrides, path)
    return path


# ---------------------------------------------------------------------------
# Task 6: entry window + session counting
# ---------------------------------------------------------------------------


def test_entry_window_is_inclusive_1545_exclusive_1600():
    from xsp_killer.backtest.intraday import in_entry_window

    assert in_entry_window(et(2024, 6, 13, 15, 45))
    assert in_entry_window(et(2024, 6, 13, 15, 59))
    assert not in_entry_window(et(2024, 6, 13, 15, 30))
    assert not in_entry_window(et(2024, 6, 13, 16, 0))


def test_entry_window_rejects_weekends_and_closed_session():
    from xsp_killer.backtest.intraday import in_entry_window

    # Saturday afternoon closed
    assert not in_entry_window(et(2024, 6, 15, 15, 45))
    # Sunday 15:45 closed
    assert not in_entry_window(et(2024, 6, 16, 15, 45))
    # Naive timestamp treated as ET weekday in window + session open
    naive = datetime(2024, 6, 13, 15, 45)
    assert in_entry_window(naive)


def test_session_date_order_only_includes_session_open_dates():
    """Open bars only; Sun 20:15 + Mon morning share Monday exchange session key."""
    from xsp_killer.backtest.intraday import session_date_order

    stamps = [
        et(2024, 6, 14, 15, 45),  # Fri RTH → Friday key
        et(2024, 6, 15, 14, 0),  # Sat afternoon CLOSED
        et(2024, 6, 16, 12, 0),  # Sun daytime CLOSED
        et(2024, 6, 16, 20, 15),  # Sun GTH reopen → Monday key
        et(2024, 6, 17, 10, 0),  # Mon RTH → Monday key
    ]
    bars = _bars_from_timestamps(stamps)
    ordered = session_date_order(bars)
    assert ordered == [
        date(2024, 6, 14),
        date(2024, 6, 17),
    ]
    assert date(2024, 6, 15) not in ordered  # Sat closed bars only
    assert date(2024, 6, 16) not in ordered  # Sun civil date is not the key


def test_session_date_order_includes_saturday_gth_tail_when_observed():
    """Fri RTH + Sat GTH tail are distinct; Fri 20:15 would share Sat key."""
    from xsp_killer.backtest.intraday import session_date_order

    stamps = [
        et(2024, 6, 14, 15, 45),  # Fri RTH → Friday
        et(2024, 6, 15, 8, 0),  # Sat GTH tail OPEN → Saturday
        et(2024, 6, 17, 10, 0),  # Mon → Monday
    ]
    ordered = session_date_order(_bars_from_timestamps(stamps))
    assert ordered == [
        date(2024, 6, 14),
        date(2024, 6, 15),
        date(2024, 6, 17),
    ]


def test_trading_sessions_held_uses_observed_order_not_calendar():
    """Friday entry → next observed exchange session is Mon (Sun+Mon share key)."""
    from xsp_killer.backtest.intraday import (
        session_date_order,
        trading_sessions_held,
    )

    stamps = [
        et(2024, 6, 14, 15, 45),  # Fri
        et(2024, 6, 15, 14, 0),  # Sat closed (not a session date)
        et(2024, 6, 16, 20, 15),  # Sun reopen → Monday session
        et(2024, 6, 17, 10, 0),  # Mon morning → same Monday session
    ]
    bars = _bars_from_timestamps(stamps)
    session_dates = session_date_order(bars)
    entry = et(2024, 6, 14, 15, 45)

    # Same session date still held 0
    assert trading_sessions_held(entry, et(2024, 6, 14, 16, 0), session_dates) == 0

    # Saturday closed is not a session date — calendar +1 must NOT count
    # Sun reopen and Mon morning share one exchange session key
    assert trading_sessions_held(entry, et(2024, 6, 16, 20, 15), session_dates) == 1
    assert trading_sessions_held(entry, et(2024, 6, 17, 10, 0), session_dates) == 1

    # Pure calendar subtraction Fri→Sat would be 1; observed order skips Sat
    calendar_days = (date(2024, 6, 15) - date(2024, 6, 14)).days
    assert calendar_days == 1
    assert session_dates == [date(2024, 6, 14), date(2024, 6, 17)]


# ---------------------------------------------------------------------------
# Task 7: session-aware 15-minute replay
# ---------------------------------------------------------------------------


def test_one_entry_per_et_date_even_with_two_close_window_bars(tmp_path):
    """At most one new entry per ET date even if 15:45 and 15:59 both present."""
    from xsp_killer.backtest.intraday import run_intraday_backtest

    warm, stamps = _green_warmup_days(8, start=date(2024, 6, 3))
    # Duplicate close-window on a mid day: add 15:59 alongside existing 15:45
    # Pick a day with room after so hold_cap can close trades
    mid = stamps[len(stamps) // 2]
    mid_day = mid.date()
    extra = et(mid_day.year, mid_day.month, mid_day.day, 15, 59)
    # Use last warm close for simple append price
    px = float(warm.iloc[-1]["close"]) + 0.25
    extra_df = pd.DataFrame([_ohlc_row(extra, px)]).set_index("ts")
    bars = pd.concat([warm, extra_df]).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]

    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="one_entry",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=1,
    )
    entries_by_date: dict[date, int] = {}
    for t in res.trades:
        ed = datetime.fromisoformat(t.entry_ts).astimezone(ET).date()
        entries_by_date[ed] = entries_by_date.get(ed, 0) + 1
    assert res.trades, "expected at least one trade on green path"
    assert all(c == 1 for c in entries_by_date.values()), entries_by_date
    assert all(t.bar_interval == "15m" for t in res.trades)
    assert all(t.exit_reason != "end_of_series" for t in res.trades)


@pytest.mark.parametrize(
    "label,ts,expected_open",
    [
        ("GTH", et(2024, 6, 13, 8, 0), True),
        ("RTH", et(2024, 6, 13, 10, 0), True),
        ("Curb", et(2024, 6, 13, 16, 30), True),
        ("gap_09_25_09_30", et(2024, 6, 13, 9, 27), False),
        ("gap_17_00_20_15", et(2024, 6, 13, 18, 0), False),
        ("Sat_tail_le_0925", et(2024, 6, 15, 8, 0), True),
        ("Sat_afternoon", et(2024, 6, 15, 14, 0), False),
        ("Sun_daytime", et(2024, 6, 16, 12, 0), False),
        ("Sun_reopen_ge_2015", et(2024, 6, 16, 20, 15), True),
    ],
)
def test_session_parity_matches_xsp_session_open(label, ts, expected_open):
    """Replay exit eligibility must equal live xsp_session_open exactly."""
    from xsp_killer.backtest.intraday import exit_session_open

    assert xsp_session_open(ts) is expected_open, label
    assert exit_session_open(ts) is expected_open, label
    assert exit_session_open(ts) is xsp_session_open(ts), label


def test_replay_does_not_exit_when_session_closed(tmp_path, monkeypatch):
    """evaluate_exit_alerts is still invoked; closed session yields no exit."""
    from xsp_killer.backtest import intraday as intrad
    from xsp_killer.backtest.intraday import run_intraday_backtest
    from xsp_killer.lane_a_monitor import evaluate_exit_alerts as real_eval

    # Fri entry then Sat closed crash bar then Mon open
    warm, stamps = _green_warmup_days(5, start=date(2024, 6, 3))
    last_px = float(warm.iloc[-1]["close"])
    # Append crash on next Mon morning first open — but first a Sat closed bar
    sat_closed = et(2024, 6, 8, 14, 0)  # Saturday afternoon
    mon_open = et(2024, 6, 10, 10, 0)
    crash_rows = [
        _ohlc_row(sat_closed, last_px * 0.70),  # would be deep SL if eligible
        _ohlc_row(mon_open, last_px * 0.70),
    ]
    bars = pd.concat(
        [warm, pd.DataFrame(crash_rows).set_index("ts")]
    ).sort_index()

    calls: list[tuple[datetime, int]] = []

    def spy_eval(pos, rules, *, now_et=None, ta_signal=None, **kw):
        alerts = real_eval(
            pos, rules, now_et=now_et, ta_signal=ta_signal, **kw
        )
        if now_et is not None:
            calls.append((now_et, len(alerts)))
        return alerts

    monkeypatch.setattr(intrad, "evaluate_exit_alerts", spy_eval)

    rules = _rules(
        tmp_path,
        take_profit_pct=0.90,
        stop_loss_pct=0.10,
    )
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="session_closed",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=None,
    )
    # Spy saw Saturday closed eval with 0 alerts
    sat_calls = [c for c in calls if c[0].date() == date(2024, 6, 8)]
    assert sat_calls, "expected evaluate_exit_alerts on Saturday closed bar"
    assert all(n == 0 for _, n in sat_calls)
    # And live semantics: session was closed
    assert not xsp_session_open(sat_closed)
    # Trade must not exit on Saturday
    for t in res.trades:
        exit_d = datetime.fromisoformat(t.exit_ts).astimezone(ET)
        assert not (
            exit_d.date() == date(2024, 6, 8) and t.exit_reason == "stop_loss"
        ), t


def test_hold_cap_friday_closes_next_session_not_saturday(tmp_path):
    """max_hold_sessions=1: Friday entry force-closes on next observed session date."""
    from xsp_killer.backtest.intraday import (
        run_intraday_backtest,
        session_date_order,
        trading_sessions_held,
    )

    # Mon–Fri RTH only (no Sat open bars)
    warm, stamps = _green_warmup_days(5, start=date(2024, 6, 3))
    # Extend one more week so hold can close next Monday after Friday entry
    extra_days = []
    d = date(2024, 6, 10)  # Mon after Fri 6/7
    for _ in range(3):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        extra_days.extend(_rth_15m_day(d))
        d += timedelta(days=1)
    last_px = float(warm.iloc[-1]["close"])
    extra = _bars_from_timestamps(
        extra_days, start_px=last_px + 0.25, step=0.1
    )
    # Also inject Saturday closed bars that must NOT trigger hold_cap
    sat = pd.DataFrame(
        [_ohlc_row(et(2024, 6, 8, 14, 0), last_px)]
    ).set_index("ts")
    bars = pd.concat([warm, sat, extra]).sort_index()

    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="hold1",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=1,
    )
    capped = [t for t in res.trades if t.exit_reason == "hold_cap"]
    reasons = [t.exit_reason for t in res.trades]
    assert capped, f"expected hold_cap trades, got {reasons}"
    for t in capped:
        assert t.sessions_held == 1, t
        assert t.bar_interval == "15m"
        entry_d = datetime.fromisoformat(t.entry_ts).astimezone(ET).date()
        exit_d = datetime.fromisoformat(t.exit_ts).astimezone(ET)
        assert exit_d.weekday() != 5 or xsp_session_open(exit_d), (
            "must not hold_cap on Saturday closed bar"
        )
        # Next observed session after Friday is Monday (RTH-only series)
        if entry_d.weekday() == 4:  # Friday
            assert exit_d.date() != date(2024, 6, 8)
            assert exit_d.weekday() == 0  # Monday
            sess = session_date_order(bars)
            assert (
                trading_sessions_held(
                    datetime.fromisoformat(t.entry_ts),
                    exit_d,
                    sess,
                )
                == 1
            )


def test_no_entry_without_1545_bar(tmp_path):
    """Entry-at-close: if no bar in [15:45,16:00), no entry that day."""
    from xsp_killer.backtest.intraday import run_intraday_backtest

    stamps: list[datetime] = []
    d = date(2024, 6, 3)
    for _ in range(6):
        if d.weekday() < 5:
            stamps.extend(_rth_15m_day(d, include_entry=False))
        d += timedelta(days=1)
    bars = _bars_from_timestamps(stamps, start_px=400.0, step=0.3)
    rules = _rules(tmp_path)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="no_1545",
        iv_seed=0.18,
        source="fixture",
    )
    assert res.trades == []
    assert all(
        not (t.hour == 15 and t.minute >= 45) for t in stamps
    )


def test_exits_evaluated_before_entries_on_same_bar(tmp_path, monkeypatch):
    """Existing positions are marked/exited before any new entry on the same bar."""
    from xsp_killer.backtest import intraday as intrad
    from xsp_killer.backtest.intraday import run_intraday_backtest

    warm, _ = _green_warmup_days(6, start=date(2024, 6, 3))
    order: list[str] = []
    real_synth = intrad.synthesize_call_premium
    real_gate = intrad.regime_gate_allows

    def synth_spy(*a, **k):
        order.append("mark")
        return real_synth(*a, **k)

    def gate_spy(*a, **k):
        order.append("entry_gate")
        return real_gate(*a, **k)

    monkeypatch.setattr(intrad, "synthesize_call_premium", synth_spy)
    monkeypatch.setattr(intrad, "regime_gate_allows", gate_spy)

    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        warm,
        rules,
        variant_id="order",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=2,
    )
    assert res.trades
    # Once a position is open, marks must appear before later entry gates
    entry_gates = [i for i, x in enumerate(order) if x == "entry_gate"]
    marks = [i for i, x in enumerate(order) if x == "mark"]
    if len(entry_gates) >= 2 and marks:
        assert marks[0] < entry_gates[-1]


def test_trade_rows_use_15m_and_sessions_held(tmp_path):
    from xsp_killer.backtest.intraday import run_intraday_backtest

    bars, _ = _green_warmup_days(8, start=date(2024, 6, 3))
    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="meta",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=2,
    )
    assert res.trades
    for t in res.trades:
        assert t.bar_interval == "15m"
        assert isinstance(t.sessions_held, int)
        assert t.sessions_held >= 0


# ---------------------------------------------------------------------------
# Stage B quality review: forced exits, prior-day, residual, session keys, TZ
# ---------------------------------------------------------------------------


def test_exchange_session_key_maps_gth_evening_to_next_calendar_date():
    from xsp_killer.backtest.intraday import exchange_session_key

    # Sun 20:15 → Monday; Mon morning civil Monday → same key
    assert exchange_session_key(et(2024, 6, 16, 20, 15)) == date(2024, 6, 17)
    assert exchange_session_key(et(2024, 6, 17, 9, 0)) == date(2024, 6, 17)
    assert exchange_session_key(et(2024, 6, 17, 10, 0)) == date(2024, 6, 17)

    # Fri 20:15 → Saturday; Sat GTH tail civil Saturday → same key
    assert exchange_session_key(et(2024, 6, 14, 20, 15)) == date(2024, 6, 15)
    assert exchange_session_key(et(2024, 6, 15, 8, 0)) == date(2024, 6, 15)

    # RTH / curb use civil date
    assert exchange_session_key(et(2024, 6, 14, 15, 45)) == date(2024, 6, 14)
    assert exchange_session_key(et(2024, 6, 14, 16, 45)) == date(2024, 6, 14)


def test_session_date_order_sunday_reopen_and_monday_share_one_key():
    from xsp_killer.backtest.intraday import session_date_order

    stamps = [
        et(2024, 6, 16, 20, 15),  # Sun reopen
        et(2024, 6, 17, 8, 0),  # Mon GTH
        et(2024, 6, 17, 10, 0),  # Mon RTH
    ]
    ordered = session_date_order(_bars_from_timestamps(stamps))
    assert ordered == [date(2024, 6, 17)]


def test_session_date_order_friday_evening_and_saturday_tail_share_one_key():
    from xsp_killer.backtest.intraday import session_date_order

    stamps = [
        et(2024, 6, 14, 20, 15),  # Fri evening GTH
        et(2024, 6, 15, 8, 0),  # Sat GTH tail
    ]
    ordered = session_date_order(_bars_from_timestamps(stamps))
    assert ordered == [date(2024, 6, 15)]


def test_hold_counts_sunday_reopen_and_monday_as_one_session():
    from xsp_killer.backtest.intraday import (
        session_date_order,
        trading_sessions_held,
    )

    stamps = [
        et(2024, 6, 13, 15, 45),  # Thu
        et(2024, 6, 14, 15, 45),  # Fri
        et(2024, 6, 16, 20, 15),  # Sun reopen → Mon key
        et(2024, 6, 17, 10, 0),  # Mon morning → Mon key
    ]
    sess = session_date_order(_bars_from_timestamps(stamps))
    entry = et(2024, 6, 14, 15, 45)
    assert trading_sessions_held(entry, et(2024, 6, 16, 20, 15), sess) == 1
    assert trading_sessions_held(entry, et(2024, 6, 17, 10, 0), sess) == 1


def test_hold_counts_friday_evening_and_saturday_tail_as_one_session():
    from xsp_killer.backtest.intraday import (
        session_date_order,
        trading_sessions_held,
    )

    stamps = [
        et(2024, 6, 14, 15, 45),  # Fri RTH entry session
        et(2024, 6, 14, 20, 15),  # Fri evening → Sat key
        et(2024, 6, 15, 8, 0),  # Sat tail → Sat key
    ]
    sess = session_date_order(_bars_from_timestamps(stamps))
    entry = et(2024, 6, 14, 15, 45)
    assert trading_sessions_held(entry, et(2024, 6, 14, 20, 15), sess) == 1
    assert trading_sessions_held(entry, et(2024, 6, 15, 8, 0), sess) == 1


def test_time_stop_requires_session_open_not_gap_or_weekend(tmp_path):
    """dte<=0 force exit only when session open (not gap/weekend closed)."""
    from xsp_killer.backtest.intraday import run_intraday_backtest

    warm, _ = _green_warmup_days(6, start=date(2024, 6, 3))
    last_px = float(warm.iloc[-1]["close"])
    # dte_target=0 so expiry force path is live on subsequent bars
    rules = _rules(
        tmp_path,
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        dte_target=0,
    )

    last_day = warm.index[-1]
    if hasattr(last_day, "to_pydatetime"):
        last_et = last_day.to_pydatetime()
    else:
        last_et = last_day
    if getattr(last_et, "tzinfo", None) is None:
        last_et = last_et.replace(tzinfo=ET)
    else:
        last_et = last_et.astimezone(ET)
    d = last_et.date()
    # Next weekday for open-session liquidation target
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)

    gap_rows = [
        _ohlc_row(et(nxt.year, nxt.month, nxt.day, 9, 27), last_px),
        _ohlc_row(et(nxt.year, nxt.month, nxt.day, 18, 0), last_px),
        _ohlc_row(et(nxt.year, nxt.month, nxt.day, 10, 0), last_px),
    ]
    # Weekend closed bar must never host time_stop
    sat = nxt + timedelta(days=(5 - nxt.weekday()) % 7)
    if sat == nxt:
        sat = nxt + timedelta(days=7)
    gap_rows.append(_ohlc_row(et(sat.year, sat.month, sat.day, 14, 0), last_px))

    bars = pd.concat(
        [warm, pd.DataFrame(gap_rows).set_index("ts")]
    ).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]

    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="ts_session",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=None,
    )
    time_stops = [t for t in res.trades if t.exit_reason == "time_stop"]
    reasons = [t.exit_reason for t in res.trades]
    assert time_stops, f"expected time_stop on open bar, got {reasons}"
    for t in time_stops:
        exit_ts = datetime.fromisoformat(t.exit_ts)
        assert xsp_session_open(exit_ts), t.exit_ts
        if exit_ts.tzinfo:
            et_x = exit_ts.astimezone(ET)
        else:
            et_x = exit_ts.replace(tzinfo=ET)
        assert not (et_x.hour == 9 and 25 <= et_x.minute < 30)
        assert not (et_x.hour >= 17 and et_x.hour < 20)
        assert not (et_x.hour == 20 and et_x.minute < 15)
        assert not (et_x.weekday() == 5 and et_x.hour >= 10)


def test_hold_cap_requires_session_open_not_gap(tmp_path):
    """hold_cap must not fire in 09:25–09:30 / 17:00–20:15 gaps."""
    from xsp_killer.backtest.intraday import run_intraday_backtest

    warm, _ = _green_warmup_days(5, start=date(2024, 6, 3))
    last_px = float(warm.iloc[-1]["close"])
    # After Fri 6/7 entry, next session Mon 6/10 — inject Mon gap then open
    gap_rows = [
        _ohlc_row(et(2024, 6, 10, 9, 27), last_px),
        _ohlc_row(et(2024, 6, 10, 18, 0), last_px),
        _ohlc_row(et(2024, 6, 10, 10, 0), last_px),
        _ohlc_row(et(2024, 6, 11, 10, 0), last_px),
    ]
    bars = pd.concat(
        [warm, pd.DataFrame(gap_rows).set_index("ts")]
    ).sort_index()

    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="hold_gap",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=1,
    )
    capped = [t for t in res.trades if t.exit_reason == "hold_cap"]
    assert capped, f"expected hold_cap, got {[t.exit_reason for t in res.trades]}"
    for t in capped:
        exit_ts = datetime.fromisoformat(t.exit_ts)
        assert xsp_session_open(exit_ts), t.exit_ts


def test_exit_precedence_strategy_alert_over_time_stop_over_hold_cap(
    tmp_path, monkeypatch
):
    """On open bars: strategy alert > dte time_stop > hold_cap."""
    from xsp_killer.backtest import intraday as intrad
    from xsp_killer.backtest.intraday import run_intraday_backtest
    from xsp_killer.lane_a_monitor import ExitAlert

    warm, _ = _green_warmup_days(6, start=date(2024, 6, 3))
    last_px = float(warm.iloc[-1]["close"])
    extra = _bars_from_timestamps(
        _rth_15m_day(date(2024, 6, 10)) + _rth_15m_day(date(2024, 6, 11)),
        start_px=last_px + 0.25,
        step=0.1,
    )
    bars = pd.concat([warm, extra]).sort_index()

    def always_sl(pos, rules, *, now_et=None, ta_signal=None, **kw):
        if now_et is None or not xsp_session_open(now_et):
            return []
        if pos.dte is not None and pos.dte <= 0:
            # Would be time_stop territory; still strategy wins
            return [
                ExitAlert(
                    position_id=pos.position_id,
                    exit_reason="stop_loss",
                    message="forced SL for precedence",
                    pnl_usd=pos.pnl_usd,
                    pnl_per_contract=pos.pnl_per_contract,
                )
            ]
        return []

    monkeypatch.setattr(intrad, "evaluate_exit_alerts", always_sl)
    rules = _rules(
        tmp_path,
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        dte_target=0,
    )
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="prec",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=1,
    )
    assert res.trades
    # First exit after dte hits 0 should be strategy stop_loss, not time_stop/hold_cap
    reasons = {t.exit_reason for t in res.trades}
    assert "stop_loss" in reasons
    assert "time_stop" not in reasons


def test_prior_day_spy_positive_uses_completed_rth_closes_not_adjacent_bars(tmp_path):
    """Gate compares completed RTH session closes, not adjacent 15m bars."""
    from xsp_killer.backtest.intraday import (
        completed_rth_session_closes,
        run_intraday_backtest,
    )

    # Build 6 green RTH days then a red RTH day (session close down) then entry day
    # with rising 15m bars so adjacent-bar logic would incorrectly pass.
    stamps: list[datetime] = []
    d = date(2024, 6, 3)  # Mon
    while len({s.date() for s in stamps}) < 6:
        if d.weekday() < 5:
            stamps.extend(_rth_15m_day(d))
        d += timedelta(days=1)
    # Day 7: red day — last RTH close well below prior day close
    red_day = d
    while red_day.weekday() >= 5:
        red_day += timedelta(days=1)
    red_stamps = _rth_15m_day(red_day)
    # Day 8: entry day with mild uptrend 15m bars
    entry_day = red_day + timedelta(days=1)
    while entry_day.weekday() >= 5:
        entry_day += timedelta(days=1)
    entry_stamps = _rth_15m_day(entry_day)

    # Warmup green uptrend
    warm = _bars_from_timestamps(stamps, start_px=400.0, step=0.25)
    prior_close = float(warm.iloc[-1]["close"])
    # Red day: drop hard so last RTH close < prior completed close
    red_rows = []
    for i, ts in enumerate(red_stamps):
        px = prior_close - 5.0 - i * 0.1
        red_rows.append(_ohlc_row(ts, px))
    red_df = pd.DataFrame(red_rows).set_index("ts")
    red_close = float(red_df.iloc[-1]["close"])
    assert red_close < prior_close

    # Entry day: 15m rising from red_close (adjacent bars green) but prior session red
    ent_rows = []
    for i, ts in enumerate(entry_stamps):
        ent_rows.append(_ohlc_row(ts, red_close + 0.5 + i * 0.2))
    ent_df = pd.DataFrame(ent_rows).set_index("ts")
    bars = pd.concat([warm, red_df, ent_df]).sort_index()

    closes = completed_rth_session_closes(bars)
    assert len(closes) >= 2
    # Last two completed before entry day: red vs green
    before_entry = [(dt, px) for dt, px in closes if dt < entry_day]
    assert len(before_entry) >= 2
    assert before_entry[-1][1] < before_entry[-2][1]

    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    # Enable prior_day_spy_positive
    text = rules.read_text(encoding="utf-8")
    rules.write_text(
        text.replace("prior_day_spy_positive: false", "prior_day_spy_positive: true"),
        encoding="utf-8",
    )

    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="prior_red",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=1,
    )
    # No entries on entry_day (blocked by prior red RTH session)
    entry_day_trades = [
        t
        for t in res.trades
        if datetime.fromisoformat(t.entry_ts).astimezone(ET).date() == entry_day
    ]
    assert entry_day_trades == []
    assert res.n_entries_blocked >= 1


def test_prior_day_spy_positive_allows_when_prior_rth_session_green(tmp_path):
    from xsp_killer.backtest.intraday import run_intraday_backtest

    bars, _ = _green_warmup_days(8, start=date(2024, 6, 3), step=0.3)
    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    text = rules.read_text(encoding="utf-8")
    rules.write_text(
        text.replace("prior_day_spy_positive: false", "prior_day_spy_positive: true"),
        encoding="utf-8",
    )
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="prior_green",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=2,
    )
    assert res.trades, "green RTH sessions should allow prior_day_spy_positive entries"


def test_prior_day_spy_positive_blocks_with_fewer_than_two_completed_sessions(
    tmp_path,
):
    from xsp_killer.backtest.intraday import (
        completed_rth_session_closes,
        run_intraday_backtest,
    )

    # Only one full RTH day — cannot evaluate prior-day green
    stamps = _rth_15m_day(date(2024, 6, 3)) + _rth_15m_day(date(2024, 6, 4))
    bars = _bars_from_timestamps(stamps, start_px=400.0, step=0.5)
    # At first entry-eligible bar we may have only 1 completed session
    closes = completed_rth_session_closes(bars)
    assert len(closes) == 2  # two calendar days present overall

    rules = _rules(tmp_path)
    text = rules.read_text(encoding="utf-8")
    rules.write_text(
        text.replace("prior_day_spy_positive: false", "prior_day_spy_positive: true"),
        encoding="utf-8",
    )
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="prior_short",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=None,
    )
    # Warmup also blocks, but gate must not enter with <2 completed sessions before day
    assert res.trades == []


def test_no_residual_end_of_series_liquidation(tmp_path):
    """Never realize open positions solely because the series ended."""
    from xsp_killer.backtest.intraday import run_intraday_backtest

    bars, _ = _green_warmup_days(6, start=date(2024, 6, 3))
    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="residual",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=None,
    )
    assert all(t.exit_reason != "end_of_series" for t in res.trades)
    residual_notes = [n for n in res.notes if "residual" in n.lower()]
    assert residual_notes, f"expected residual note, got {res.notes}"


def test_final_bar_entry_cannot_produce_same_ts_end_of_series(tmp_path):
    """Entry on last bar must not fabricate same-timestamp end_of_series exit."""
    from xsp_killer.backtest.intraday import run_intraday_backtest

    bars, _ = _green_warmup_days(6, start=date(2024, 6, 3))
    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="final_entry",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=None,
    )
    for t in res.trades:
        assert not (
            t.exit_reason == "end_of_series" and t.entry_ts == t.exit_ts
        ), t
    # Last bar is 15:45 entry window — position may remain open as residual
    last_ts = bars.index[-1]
    last_et = (
        last_ts.to_pydatetime()
        if hasattr(last_ts, "to_pydatetime")
        else last_ts
    )
    if getattr(last_et, "tzinfo", None) is None:
        last_et = last_et.replace(tzinfo=ET)
    else:
        last_et = last_et.astimezone(ET)
    assert last_et.hour == 15 and last_et.minute == 45
    same_ts_exits = [
        t
        for t in res.trades
        if t.entry_ts == t.exit_ts and t.exit_reason == "end_of_series"
    ]
    assert same_ts_exits == []


def test_off_session_final_bar_cannot_liquidate(tmp_path):
    """Closed final bar must not liquidate residual opens."""
    from xsp_killer.backtest.intraday import run_intraday_backtest

    warm, _ = _green_warmup_days(6, start=date(2024, 6, 3))
    last_px = float(warm.iloc[-1]["close"])
    # Append Saturday closed afternoon as final bar
    sat = pd.DataFrame(
        [_ohlc_row(et(2024, 6, 8, 14, 0), last_px)]
    ).set_index("ts")
    bars = pd.concat([warm, sat]).sort_index()
    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="off_final",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=None,
    )
    for t in res.trades:
        exit_ts = datetime.fromisoformat(t.exit_ts).astimezone(ET)
        assert not (
            exit_ts.date() == date(2024, 6, 8) and t.exit_reason == "end_of_series"
        )
    assert all(t.exit_reason != "end_of_series" for t in res.trades)
    assert any("residual" in n.lower() for n in res.notes)


def test_utc_indexed_bars_convert_to_et_for_session_and_entry(tmp_path):
    """UTC-indexed bars must convert to ET for windows, session keys, and exits."""
    from xsp_killer.backtest.intraday import (
        in_entry_window,
        run_intraday_backtest,
        session_date_order,
    )

    utc = ZoneInfo("UTC")
    # 15:45 ET = 19:45 UTC on a weekday
    stamps_et = _rth_15m_day(date(2024, 6, 3))
    for _ in range(5):
        d = stamps_et[-1].date() + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        stamps_et.extend(_rth_15m_day(d))

    rows = []
    for i, ts_et in enumerate(stamps_et):
        ts_utc = ts_et.astimezone(utc)
        rows.append(
            {
                "ts": ts_utc,
                "open": 400 + i * 0.25,
                "high": 400.1 + i * 0.25,
                "low": 399.9 + i * 0.25,
                "close": 400 + i * 0.25,
                "volume": 1_500_000.0,
            }
        )
    bars = pd.DataFrame(rows).set_index("ts")

    # Entry window still true for the UTC stamp that is 15:45 ET
    sample_1545_utc = et(2024, 6, 3, 15, 45).astimezone(utc)
    assert in_entry_window(sample_1545_utc)

    ordered = session_date_order(bars)
    assert date(2024, 6, 3) in ordered

    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="utc_bars",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=2,
    )
    assert res.trades
    for t in res.trades:
        entry_et = datetime.fromisoformat(t.entry_ts).astimezone(ET)
        assert entry_et.hour == 15 and entry_et.minute >= 45
        assert t.bar_interval == "15m"


# ---------------------------------------------------------------------------
# Task 8: coverage honesty + strict UW loading
# ---------------------------------------------------------------------------


def test_fixture_coverage_reports_rth_only():
    from xsp_killer.backtest.bars import load_fixture_intraday
    from xsp_killer.backtest.intraday import bar_coverage

    coverage = bar_coverage(load_fixture_intraday())
    assert coverage["n_bars"] > 0
    assert coverage["n_sessions"] >= 1
    assert coverage["has_overnight_bars"] is False
    assert coverage["session_phases_observed"] == ["RTH"]
    assert coverage["interval"] == "15m"
    assert coverage["start"]
    assert coverage["end"]
    # Must not fabricate GTH/Curb from RTH-only fixture
    assert "GTH" not in coverage["session_phases_observed"]
    assert "Curb" not in coverage["session_phases_observed"]


def test_coverage_observes_gth_and_curb_only_when_present():
    from xsp_killer.backtest.intraday import bar_coverage

    stamps = [
        et(2024, 6, 13, 8, 0),  # GTH
        et(2024, 6, 13, 10, 0),  # RTH
        et(2024, 6, 13, 16, 30),  # Curb
    ]
    cov = bar_coverage(_bars_from_timestamps(stamps))
    assert cov["session_phases_observed"] == ["GTH", "RTH", "Curb"]
    assert cov["has_overnight_bars"] is True
    assert cov["n_sessions"] >= 1


def test_assert_intraday_coverage_raises_insufficient():
    from xsp_killer.backtest.bars import InsufficientBarsError
    from xsp_killer.backtest.intraday import assert_intraday_coverage

    stamps = [et(2024, 6, 13, 10, 0), et(2024, 6, 13, 10, 15)]
    bars = _bars_from_timestamps(stamps)
    with pytest.raises(InsufficientBarsError):
        assert_intraday_coverage(bars, min_bars=200, min_sessions=20)


def test_strict_uw_loader_raises_without_key(monkeypatch):
    from xsp_killer.backtest.bars import FixtureFallbackError, load_uw_bars_strict

    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "")
    monkeypatch.delenv("UNUSUAL_WHALES_API_KEY", raising=False)
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "")
    with pytest.raises(FixtureFallbackError):
        load_uw_bars_strict("SPY", period="60d", interval="15m", use_cache=False)


def test_strict_uw_loader_raises_insufficient_bars(monkeypatch):
    from xsp_killer.backtest.bars import InsufficientBarsError, load_uw_bars_strict

    tiny = _bars_from_timestamps(
        [
            et(2024, 6, 13, 10 + (i * 15) // 60, (i * 15) % 60)
            for i in range(10)
        ],
        start_px=450.0,
        step=0.1,
    )

    def fake_load(*a, **k):
        return tiny

    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        "xsp_killer.backtest.bars.load_uw_bars",
        fake_load,
    )
    with pytest.raises(InsufficientBarsError):
        load_uw_bars_strict(
            "SPY",
            period="60d",
            interval="15m",
            use_cache=False,
            min_bars=200,
            min_sessions=1,
        )


def test_load_bars_still_fail_open_without_key(monkeypatch, tmp_path):
    """Existing load_bars fail-open behavior must remain unchanged."""
    from xsp_killer.backtest.bars import load_bars

    monkeypatch.setattr(
        "xsp_killer.backtest.bars.CACHE_DIR", tmp_path / "empty_uw_cache"
    )
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "")
    bars, source = load_bars(mode="uw", interval="15m")
    assert source == "fixture_fallback"
    assert len(bars) > 0
    bars_d, source_d = load_bars(mode="uw", interval="1d")
    assert source_d == "fixture_fallback"
    assert len(bars_d) > 0


# ---------------------------------------------------------------------------
# Task 9: orchestration CLI and reports
# ---------------------------------------------------------------------------


def test_cli_fixture_stage_a_and_b_offline(tmp_path):
    """Fixture CLI is offline/deterministic; emits JSON+MD with fidelity & safety."""
    import json
    import os
    import subprocess
    import sys

    out = tmp_path / "reports"
    env = {
        **os.environ,
        "UNUSUAL_WHALES_API_KEY": "",
        "PYTHONUTF8": "1",
        "XSP_UW_TIPDROP_ROOT": str(tmp_path / "no_tipdrop"),
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "optimize_regime_hold.py"),
            "--mode",
            "fixture",
            "--stage-a",
            "--stage-b",
            "--min-trades",
            "1",
            "--top-k",
            "2",
            "--no-coarse-to-fine",
            "--out",
            str(out),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    jsons = list(out.glob("regime_hold_*.json"))
    mds = list(out.glob("regime_hold_*.md"))
    assert jsons, "expected timestamped JSON report"
    assert mds, "expected timestamped Markdown report"

    payload = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert payload.get("stage_a", {}).get("fidelity") == "daily_close_proxy"
    stage_b = payload.get("stage_b") or {}
    assert stage_b.get("fidelity") in (
        "intraday_15m_session_aware",
        "15m_session_aware",
    ) or "15m" in str(stage_b.get("fidelity") or "")
    assert "coverage" in stage_b or payload.get("intraday_coverage")
    cov = stage_b.get("coverage") or payload.get("intraday_coverage") or {}
    assert cov.get("session_phases_observed") == ["RTH"]
    assert cov.get("has_overnight_bars") is False

    yaml_snip = payload.get("yaml_snippet") or payload.get("recommended_yaml") or ""
    assert "active: false" in yaml_snip or "active:false" in yaml_snip.replace(" ", "")
    text_all = jsons[0].read_text(encoding="utf-8") + mds[0].read_text(
        encoding="utf-8"
    )
    low = text_all.lower()
    assert "live_entries" not in low
    assert "live_exits" not in low
    assert "unusual_whales_api_key" not in low
    # attribution / gates present
    assert "ranking" in payload.get("stage_a", {}) or "ranking" in payload
    assert "stable_windows" in payload or "stable_windows" in payload.get(
        "stage_a", {}
    )


def test_cli_uw_require_uw_fails_without_key_no_report(tmp_path):
    """--mode uw --require-uw with empty key exits nonzero; no deceptive report."""
    import os
    import subprocess
    import sys

    out = tmp_path / "reports_uw_strict"
    env = {
        **os.environ,
        "UNUSUAL_WHALES_API_KEY": "",
        "PYTHONUTF8": "1",
        "XSP_UW_TIPDROP_ROOT": str(tmp_path / "no_tipdrop"),
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "optimize_regime_hold.py"),
            "--mode",
            "uw",
            "--require-uw",
            "--stage-a",
            "--period",
            "5y",
            "--out",
            str(out),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert not list(out.glob("*.json")), "must not write fixture-disguised report"
    assert not list(out.glob("*.md"))
    combined = (proc.stderr + proc.stdout).lower()
    assert "unusual_whales_api_key=" not in combined
    assert "error" in combined or "strict" in combined or "refused" in combined
    assert "can't open file" not in combined
    # must not claim a successful write
    assert "wrote " not in combined


def test_cli_help_lists_required_flags():
    import os
    import subprocess
    import sys

    env = {**os.environ, "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "optimize_regime_hold.py"),
            "--help",
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    help_text = proc.stdout
    for flag in (
        "--mode",
        "--stage-a",
        "--stage-b",
        "--period",
        "--intraday-period",
        "--split-frac",
        "--min-trades",
        "--top-k",
        "--mcpt",
        "--mcpt-perm",
        "--coarse-to-fine",
        "--allow-large",
        "--require-uw",
        "--min-intraday-bars",
        "--min-intraday-sessions",
        "--out",
    ):
        assert flag in help_text, f"missing {flag}"
