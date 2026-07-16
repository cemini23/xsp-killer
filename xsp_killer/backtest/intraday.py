"""Stage B: session-aware 15-minute Lane A replay.

Entries only in the ET close window [15:45, 16:00). Exits and hold caps
delegate session truth to live ``xsp_session_open`` — no re-derived hours.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from xsp_killer.lane_a_monitor import xsp_session_open

ET = ZoneInfo("America/New_York")
ENTRY_WINDOW_START = time(15, 45)
ENTRY_WINDOW_END = time(16, 0)


def _to_et(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=ET)
    return ts.astimezone(ET)


def _bar_ts_et(idx: Any) -> datetime:
    ts = pd.Timestamp(idx)
    if ts.tzinfo is None:
        ts = ts.tz_localize(ET)
    else:
        ts = ts.tz_convert(ET)
    return ts.to_pydatetime()


def in_entry_window(ts: datetime) -> bool:
    """True for ET weekdays in [15:45, 16:00) when XSP session is open."""
    now = _to_et(ts)
    if now.weekday() >= 5:
        return False
    t = now.time()
    if not (ENTRY_WINDOW_START <= t < ENTRY_WINDOW_END):
        return False
    return xsp_session_open(now)


def session_date_order(bars: pd.DataFrame) -> list[date]:
    """Ordered distinct ET dates that have at least one session-open bar."""
    if bars is None or bars.empty:
        return []
    seen: list[date] = []
    seen_set: set[date] = set()
    for idx in bars.index:
        ts = _bar_ts_et(idx)
        if not xsp_session_open(ts):
            continue
        d = ts.date()
        if d not in seen_set:
            seen_set.add(d)
            seen.append(d)
    return seen


def trading_sessions_held(
    entry_ts: datetime,
    now_ts: datetime,
    session_dates: list[date],
) -> int:
    """Index distance on observed session dates (not calendar-day subtraction)."""
    if not session_dates:
        return 0
    entry_d = _to_et(entry_ts).date()
    now_d = _to_et(now_ts).date()
    try:
        i_entry = session_dates.index(entry_d)
        i_now = session_dates.index(now_d)
    except ValueError:
        return 0
    return max(0, i_now - i_entry)
