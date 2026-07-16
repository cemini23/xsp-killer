"""Calendar-backed XSP exchange-session hold semantics."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import xsp_killer.xsp_sessions as sessions
from xsp_killer.xsp_sessions import (
    exchange_session_key,
    session_keys_between,
    trading_sessions_held,
)

ET = ZoneInfo("America/New_York")


def et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def test_sunday_evening_and_monday_daytime_share_session_key():
    assert exchange_session_key(et(2024, 6, 16, 20, 15)) == date(2024, 6, 17)
    assert exchange_session_key(et(2024, 6, 17, 10, 0)) == date(2024, 6, 17)


def test_naive_strategy_timestamps_are_interpreted_as_et():
    naive_sunday_evening = datetime(2024, 6, 16, 20, 15)
    assert exchange_session_key(naive_sunday_evening) == date(2024, 6, 17)
    assert trading_sessions_held(
        naive_sunday_evening, et(2024, 6, 18, 10, 0)
    ) == 1


def test_exchange_session_eligibility_honors_holidays_and_gth_mapping():
    assert sessions.is_exchange_session(et(2024, 7, 4, 10, 0)) is False
    assert sessions.is_exchange_session(et(2024, 6, 16, 20, 15)) is True
    assert sessions.is_exchange_session(et(2024, 6, 17, 8, 0)) is True
    assert sessions.is_exchange_session(et(2024, 6, 14, 20, 15)) is False


def test_weekend_does_not_add_exchange_sessions():
    friday = et(2024, 6, 14, 15, 45)
    assert session_keys_between(friday, et(2024, 6, 16, 12, 0)) == [
        date(2024, 6, 14)
    ]
    assert trading_sessions_held(friday, et(2024, 6, 16, 12, 0)) == 0
    assert trading_sessions_held(friday, et(2024, 6, 16, 20, 15)) == 1


def test_july_four_closure_is_not_counted():
    july_third = et(2024, 7, 3, 12, 0)
    july_fifth = et(2024, 7, 5, 10, 0)
    assert session_keys_between(july_third, july_fifth) == [
        date(2024, 7, 3),
        date(2024, 7, 5),
    ]
    assert trading_sessions_held(july_third, july_fifth) == 1


def test_thanksgiving_closure_is_not_counted():
    wednesday = et(2024, 11, 27, 15, 45)
    friday = et(2024, 11, 29, 10, 0)
    assert session_keys_between(wednesday, friday) == [
        date(2024, 11, 27),
        date(2024, 11, 29),
    ]
    assert trading_sessions_held(wednesday, friday) == 1


def test_early_close_still_counts_as_exchange_session():
    july_second = et(2024, 7, 2, 15, 45)
    july_third_after_close = et(2024, 7, 3, 16, 0)
    assert session_keys_between(july_second, july_third_after_close) == [
        date(2024, 7, 2),
        date(2024, 7, 3),
    ]
    assert trading_sessions_held(july_second, july_third_after_close) == 1


def test_dst_transition_weeks_count_sessions_not_elapsed_hours():
    assert trading_sessions_held(
        et(2024, 3, 8, 15, 45), et(2024, 3, 11, 10, 0)
    ) == 1
    assert trading_sessions_held(
        et(2024, 11, 1, 15, 45), et(2024, 11, 4, 10, 0)
    ) == 1


def test_invalid_or_reversed_timestamps_fail_closed():
    valid = et(2024, 6, 17, 10, 0)
    assert session_keys_between("not-a-timestamp", valid) == []
    assert trading_sessions_held("not-a-timestamp", valid) == 0
    assert trading_sessions_held(valid, et(2024, 6, 14, 10, 0)) == 0


def test_calendar_backend_failures_raise_loudly(monkeypatch):
    class BrokenCalendar:
        def sessions_in_range(self, _start, _end):
            raise ValueError("calendar unavailable")

    monkeypatch.setattr(sessions, "_calendar", lambda: BrokenCalendar())
    with pytest.raises(RuntimeError, match="calendar"):
        trading_sessions_held(et(2024, 7, 2, 15, 45), et(2024, 7, 5, 10, 0))
