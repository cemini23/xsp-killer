"""Synthesize call premium path from underlying OHLC (BS-lite + fallback).

This is a **model**, not historical option fills. Used only for relative ranking.
"""

from __future__ import annotations

import math
from typing import Callable

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
