"""Synthesize call premium path from underlying OHLC (BS-lite + fallback).

This is a **model**, not historical option fills. Used only for relative ranking.
Never claim historical_xsp_chain fidelity — always modeled_bs_lite.
"""

from __future__ import annotations

import math
from typing import Callable

from xsp_killer.debit_spread import DebitSpread, build_debit_spread
from xsp_killer.lane_a_entry import estimate_fallback_premium
from xsp_killer.paper_economics import scale_spy_premium


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(
    spot: float,
    strike: float,
    t_years: float,
    iv: float,
    *,
    r: float = 0.05,
) -> float:
    """Black-Scholes European call (per-share)."""
    if spot <= 0 or strike <= 0:
        return 0.0
    if t_years <= 1e-8:
        return max(0.0, spot - strike)
    sigma = max(iv, 1e-4)
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (
        sigma * sqrt_t
    )
    d2 = d1 - sigma * sqrt_t
    return spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)


def synthesize_call_premium(
    spy_price: float,
    *,
    xsp_strike: float,
    dte: int,
    iv: float = 0.18,
    premium_scale: float | None = None,
    use_bs: bool = True,
) -> float:
    """XSP-notional call mid from SPY spot + strike + remaining DTE.

    XSP level ≈ SPY; ATM XSP strike ≈ SPY price. BS prices the unit-share call
    then applies the active paper premium scale (default 10×).
    """
    dte_i = max(0, int(dte))
    if use_bs and dte_i > 0:
        t = dte_i / 365.0
        # SPY option on same numerical strike level (XSP ≈ SPY).
        spy_prem = bs_call(spy_price, xsp_strike, t, iv)
        # Floor so SL/TP percent gates remain meaningful on deep OTM.
        spy_prem = max(spy_prem, 0.05)
        return round(scale_spy_premium(spy_prem, premium_scale), 4)

    return estimate_fallback_premium(
        spy_price,
        dte_i,
        xsp_strike=xsp_strike,
        spx_level=spy_price,
        scale_to_xsp=True,
        premium_scale=premium_scale,
    )


def synthesize_debit_spread(
    spy_price: float,
    *,
    long_strike: float,
    short_strike: float,
    dte: int,
    iv: float = 0.18,
    premium_scale: float | None = None,
    use_bs: bool = True,
) -> DebitSpread | None:
    """Dual-leg BS-lite mids → ``build_debit_spread`` (or None if incoherent).

    Long and short premiums share the same scale. Returns None when the short
    mid is not strictly cheaper than the long mid (or other build rejects).
    """
    long_prem = synthesize_call_premium(
        spy_price,
        xsp_strike=long_strike,
        dte=dte,
        iv=iv,
        premium_scale=premium_scale,
        use_bs=use_bs,
    )
    short_prem = synthesize_call_premium(
        spy_price,
        xsp_strike=short_strike,
        dte=dte,
        iv=iv,
        premium_scale=premium_scale,
        use_bs=use_bs,
    )
    scale = premium_scale if premium_scale is not None else 1.0
    return build_debit_spread(
        long_strike=long_strike,
        long_premium=long_prem,
        short_strike=short_strike,
        short_premium=short_prem,
        premium_scale=scale if scale and scale > 0 else 1.0,
    )


def debit_spread_mark(
    spy_price: float,
    *,
    long_strike: float,
    short_strike: float,
    width_points: float,
    dte: int,
    iv: float = 0.18,
    premium_scale: float | None = None,
    use_bs: bool = True,
) -> tuple[float, float, float]:
    """Return ``(long_mid, short_mid, spread_value_scaled)`` for exit marking.

    Spread value is ``long - short`` clamped to ``[0, width * scale]`` so it
    lives in the same notional scale as naked ``synthesize_call_premium`` mids.
    """
    long_mid = synthesize_call_premium(
        spy_price,
        xsp_strike=long_strike,
        dte=dte,
        iv=iv,
        premium_scale=premium_scale,
        use_bs=use_bs,
    )
    short_mid = synthesize_call_premium(
        spy_price,
        xsp_strike=short_strike,
        dte=dte,
        iv=iv,
        premium_scale=premium_scale,
        use_bs=use_bs,
    )
    scale = premium_scale if premium_scale is not None and premium_scale > 0 else 1.0
    width_scaled = max(0.0, float(width_points) * scale)
    raw = float(long_mid) - float(short_mid)
    value = min(max(raw, 0.0), width_scaled)
    return float(long_mid), float(short_mid), round(value, 4)


def premium_path_fn(
    *,
    xsp_strike: float,
    expiry_dte_at_entry: int,
    iv: float = 0.18,
    premium_scale: float | None = None,
    use_bs: bool = True,
) -> Callable[[float, int], float]:
    """Return ``(spy_price, remaining_dte) -> premium`` for a fixed contract."""

    def _fn(spy_price: float, dte: int) -> float:
        # Cap remaining DTE by original so model doesn't invent longer tenors.
        rem = max(0, min(int(dte), int(expiry_dte_at_entry)))
        return synthesize_call_premium(
            spy_price,
            xsp_strike=xsp_strike,
            dte=rem,
            iv=iv,
            premium_scale=premium_scale,
            use_bs=use_bs,
        )

    return _fn
