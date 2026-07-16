"""Shared XSP exchange-session keys and calendar-backed hold counts.

XNYS is used as a holiday-session proxy for Cboe index options. XSP's GTH
evening belongs to the following session date, so Sunday evening and Monday
daytime intentionally share one key.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

ET = ZoneInfo("America/New_York")
GTH_EVENING_START = time(20, 15)


def _to_et(ts: datetime) -> datetime:
    if not isinstance(ts, datetime):
        raise TypeError("timestamp must be a datetime")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=ET)
    return ts.astimezone(ET)


def exchange_session_key(ts: datetime) -> date:
    """Map an XSP timestamp to its GTH-aware exchange session date."""
    value = _to_et(ts)
    if value.time() >= GTH_EVENING_START:
        return (value + timedelta(days=1)).date()
    return value.date()


@lru_cache(maxsize=1)
def _calendar():
    return xcals.get_calendar("XNYS")


def session_keys_between(start: datetime, end: datetime) -> list[date]:
    """Return XNYS session dates in the inclusive mapped-key interval.

    Invalid or reversed timestamps return an empty list.
    """
    try:
        start_key = exchange_session_key(start)
        end_key = exchange_session_key(end)
    except (TypeError, ValueError, OverflowError):
        return []
    if end_key < start_key:
        return []
    try:
        sessions = _calendar().sessions_in_range(
            start_key.isoformat(), end_key.isoformat()
        )
    except (TypeError, ValueError, OverflowError):
        return []
    return [session.date() for session in sessions]


def trading_sessions_held(start: datetime, end: datetime) -> int:
    """Count completed exchange-session transitions since entry.

    The entry key must itself be a valid calendar session. Invalid entry
    timestamps and non-session entry keys fail closed with zero held sessions.
    """
    try:
        start_key = exchange_session_key(start)
    except (TypeError, ValueError, OverflowError):
        return 0
    sessions = session_keys_between(start, end)
    if not sessions or sessions[0] != start_key:
        return 0
    return max(0, len(sessions) - 1)
