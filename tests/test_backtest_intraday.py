"""Stage B: session-aware 15-minute replay (fixture-only, no network)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
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
