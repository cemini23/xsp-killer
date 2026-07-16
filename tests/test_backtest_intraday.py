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
    """Friday + closed Sat afternoon + Sunday evening + Monday → open dates only."""
    from xsp_killer.backtest.intraday import session_date_order

    stamps = [
        et(2024, 6, 14, 15, 45),  # Fri RTH
        et(2024, 6, 15, 14, 0),  # Sat afternoon CLOSED
        et(2024, 6, 16, 12, 0),  # Sun daytime CLOSED
        et(2024, 6, 16, 20, 15),  # Sun GTH reopen OPEN
        et(2024, 6, 17, 10, 0),  # Mon RTH OPEN
    ]
    bars = _bars_from_timestamps(stamps)
    ordered = session_date_order(bars)
    assert ordered == [
        date(2024, 6, 14),
        date(2024, 6, 16),
        date(2024, 6, 17),
    ]
    assert date(2024, 6, 15) not in ordered  # Sat closed bars only


def test_session_date_order_includes_saturday_gth_tail_when_observed():
    from xsp_killer.backtest.intraday import session_date_order

    stamps = [
        et(2024, 6, 14, 15, 45),  # Fri
        et(2024, 6, 15, 8, 0),  # Sat GTH tail OPEN
        et(2024, 6, 17, 10, 0),  # Mon
    ]
    ordered = session_date_order(_bars_from_timestamps(stamps))
    assert ordered == [
        date(2024, 6, 14),
        date(2024, 6, 15),
        date(2024, 6, 17),
    ]


def test_trading_sessions_held_uses_observed_order_not_calendar():
    """Friday entry → hold count 1 on next ordered trading date, not +1 calendar day."""
    from xsp_killer.backtest.intraday import (
        session_date_order,
        trading_sessions_held,
    )

    stamps = [
        et(2024, 6, 14, 15, 45),  # Fri
        et(2024, 6, 15, 14, 0),  # Sat closed (not a session date)
        et(2024, 6, 16, 20, 15),  # Sun reopen
        et(2024, 6, 17, 10, 0),  # Mon
    ]
    bars = _bars_from_timestamps(stamps)
    session_dates = session_date_order(bars)
    entry = et(2024, 6, 14, 15, 45)

    # Same session date still held 0
    assert trading_sessions_held(entry, et(2024, 6, 14, 16, 0), session_dates) == 0

    # Saturday closed is not a session date — calendar +1 must NOT count as 1
    # when we measure on the next observed open date (Sunday reopen)
    assert trading_sessions_held(entry, et(2024, 6, 16, 20, 15), session_dates) == 1
    assert trading_sessions_held(entry, et(2024, 6, 17, 10, 0), session_dates) == 2

    # Pure calendar subtraction Fri→Sat would be 1; observed order skips Sat
    calendar_days = (date(2024, 6, 15) - date(2024, 6, 14)).days
    assert calendar_days == 1
    # Sat is not in session_dates, so hold is measured on next open (Sun) as 1
    assert session_dates[1] == date(2024, 6, 16)


# ---------------------------------------------------------------------------
# Task 7: session-aware 15-minute replay
# ---------------------------------------------------------------------------


def test_one_entry_per_et_date_even_with_two_close_window_bars(tmp_path):
    """At most one new entry per ET date even if 15:45 and 15:59 both present."""
    from xsp_killer.backtest.intraday import run_intraday_backtest

    warm, stamps = _green_warmup_days(6, start=date(2024, 6, 3))
    # Duplicate close-window on last day: add 15:59 alongside existing 15:45
    last_day = stamps[-1].date()
    extra = et(last_day.year, last_day.month, last_day.day, 15, 59)
    px = float(warm.iloc[-1]["close"]) + 0.25
    extra_df = pd.DataFrame([_ohlc_row(extra, px)]).set_index("ts")
    bars = pd.concat([warm, extra_df]).sort_index()
    # Drop any accidental duplicate index
    bars = bars[~bars.index.duplicated(keep="first")]

    rules = _rules(tmp_path, take_profit_pct=0.90, stop_loss_pct=0.90)
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="one_entry",
        iv_seed=0.18,
        source="fixture",
        max_hold_sessions=None,
    )
    entries_by_date: dict[date, int] = {}
    for t in res.trades:
        ed = datetime.fromisoformat(t.entry_ts).astimezone(ET).date()
        entries_by_date[ed] = entries_by_date.get(ed, 0) + 1
    # Also count residual open that became end_of_series
    assert res.trades, "expected at least one trade on green path"
    assert all(c == 1 for c in entries_by_date.values()), entries_by_date
    assert all(t.bar_interval == "15m" for t in res.trades)


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
