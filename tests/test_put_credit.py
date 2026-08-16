import pytest

from xsp_killer.put_credit import (
    build_put_credit,
    put_credit_return_on_risk,
    put_credit_value,
    select_long_put_strike,
    velocity_captured,
)


def test_select_long_put_strike_is_below_short():
    assert select_long_put_strike(750.0, width_strikes=1) == 745.0


def test_build_put_credit_happy_path():
    s = build_put_credit(
        short_strike=750.0,
        short_premium=12.0,
        long_strike=745.0,
        long_premium=9.0,
        premium_scale=1.0,
    )
    assert s is not None
    assert s.width_points == 5.0
    assert s.net_credit == 3.0
    assert s.max_risk_1x == 2.0
    assert s.breakeven_underlying == 747.0


def test_build_put_credit_rejects_inverted_strikes():
    assert (
        build_put_credit(
            short_strike=745.0,
            short_premium=12.0,
            long_strike=750.0,
            long_premium=9.0,
        )
        is None
    )


def test_put_credit_value_and_velocity():
    # Debit-like value of the short-minus-long put package.
    assert put_credit_value(short_mark=4.0, long_mark=2.0, width=5.0) == 2.0
    assert velocity_captured(entry_credit=3.0, current_value=0.72) == pytest.approx(0.76)


def test_return_on_max_risk():
    roc = put_credit_return_on_risk(
        entry_credit=3.0, exit_value=1.0, width=5.0
    )
    assert roc == (3.0 - 1.0) / (5.0 - 3.0)
