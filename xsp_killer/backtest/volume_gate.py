"""SPY daily volume quiet-day gate (Nagus: slow days best, high volume worst).

Prior completed day's volume is ranked vs a trailing lookback. Entries are
allowed only when that percentile is at or below ``max_pctile`` (e.g. 0.33 =
quietest third). Regime is intentionally secondary — volume is the primary
liquidity/chaos filter.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def prior_day_volume_percentile(
    volumes: pd.Series | Any,
    bar_i: int,
    *,
    lookback: int = 63,
) -> float | None:
    """Percentile of prior-day volume within ``[bar_i-lookback, bar_i)``.

    Uses the completed prior bar only (no same-day lookahead at the close).
    Returns None when history is too short or volume is missing/non-positive.
    """
    if bar_i < 1 or lookback < 2:
        return None
    try:
        series = volumes if isinstance(volumes, pd.Series) else pd.Series(volumes)
    except (TypeError, ValueError):
        return None
    if bar_i >= len(series):
        return None
    prior = float(series.iloc[bar_i - 1])
    if prior <= 0 or prior != prior:  # NaN guard
        return None
    start = max(0, bar_i - int(lookback))
    window = series.iloc[start:bar_i].astype(float)
    window = window[window > 0]
    if len(window) < 5:
        return None
    # Fraction of lookback days with volume <= prior (empirical CDF).
    return float((window <= prior).sum()) / float(len(window))


def volume_gate_allows(
    *,
    prior_vol_pctile: float | None,
    max_pctile: float | None,
) -> tuple[bool, str | None]:
    """Return (allowed, block_reason). ``max_pctile=None`` disables the gate."""
    if max_pctile is None:
        return True, None
    cap = float(max_pctile)
    if cap <= 0 or cap > 1:
        return False, f"invalid volume_gate_max_pctile={cap}"
    if prior_vol_pctile is None:
        # Missing volume: fail-open so fixture/UW gaps don't zero the book.
        return True, None
    if prior_vol_pctile <= cap:
        return True, None
    return (
        False,
        f"volume not quiet: prior_day pctile {prior_vol_pctile:.2f} > {cap:.2f}",
    )
