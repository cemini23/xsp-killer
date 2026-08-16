"""Put credit spread economics — paper/research only, never places.

Short a higher-strike put, long a lower-strike put, same expiry.
Defined risk = width − credit. This module is the sell-side counterpart
to ``debit_spread.py`` and does not touch LIVE order paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from xsp_killer.debit_spread import XSP_STRIKE_STEP


def select_long_put_strike(
    short_strike: float,
    *,
    width_strikes: int = 1,
    strike_step: float = XSP_STRIKE_STEP,
) -> float:
    """Lower put strike that defines the long wing."""
    return short_strike - max(1, int(width_strikes)) * strike_step


@dataclass
class PutCredit:
    short_strike: float
    long_strike: float
    width_points: float
    short_premium: float
    long_premium: float
    net_credit: float
    premium_scale: float
    net_credit_1x: float
    max_risk_1x: float
    breakeven_underlying: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_put_credit(
    *,
    short_strike: float,
    short_premium: float,
    long_strike: float,
    long_premium: float,
    premium_scale: float = 1.0,
) -> PutCredit | None:
    if short_premium is None or long_premium is None:
        return None
    if short_premium <= 0 or long_premium < 0:
        return None
    width = round(short_strike - long_strike, 4)
    if width <= 0:
        return None
    net_credit = round(short_premium - long_premium, 4)
    if net_credit <= 0:
        return None
    scale = premium_scale if premium_scale and premium_scale > 0 else 1.0
    net_credit_1x = round(min(net_credit / scale, width), 4)
    max_risk_1x = round(max(width - net_credit_1x, 0.0), 4)
    breakeven = round(short_strike - net_credit_1x, 4)
    return PutCredit(
        short_strike=round(short_strike, 4),
        long_strike=round(long_strike, 4),
        width_points=width,
        short_premium=round(short_premium, 4),
        long_premium=round(long_premium, 4),
        net_credit=net_credit,
        premium_scale=round(scale, 4),
        net_credit_1x=net_credit_1x,
        max_risk_1x=max_risk_1x,
        breakeven_underlying=breakeven,
    )


def put_credit_value(*, short_mark: float, long_mark: float, width: float) -> float:
    """Cost to close (debit value of the package), clamped to [0, width]."""
    raw = float(short_mark) - float(long_mark)
    return min(max(raw, 0.0), max(width, 0.0))


def velocity_captured(*, entry_credit: float, current_value: float) -> float:
    if entry_credit <= 0:
        return 0.0
    return (entry_credit - current_value) / entry_credit


def put_credit_return_on_risk(
    *,
    entry_credit: float,
    exit_value: float,
    width: float,
) -> float | None:
    max_risk = width - entry_credit
    if max_risk <= 0:
        return None
    return (entry_credit - exit_value) / max_risk
