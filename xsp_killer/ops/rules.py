"""Rule-based classification of backtest ranking rows — no LLM calls."""

from __future__ import annotations

import os
from typing import Any

# Defaults; env-overridable (see plan table).
DEFAULT_MIN_TRADES = 20
DEFAULT_MIN_MEAN_PCT = 0.002
DEFAULT_TOP_K = 3


def min_trades() -> int:
    raw = os.environ.get("XSP_BT_MIN_TRADES", str(DEFAULT_MIN_TRADES))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MIN_TRADES


def min_mean_pct() -> float:
    raw = os.environ.get("XSP_BT_MIN_MEAN_PCT", str(DEFAULT_MIN_MEAN_PCT))
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_MIN_MEAN_PCT


def top_k() -> int:
    raw = os.environ.get("XSP_BT_TOP_K", str(DEFAULT_TOP_K))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_TOP_K


def classify_variant(
    row: dict[str, Any],
    rank: int,
    *,
    min_trades_n: int | None = None,
    min_mean: float | None = None,
    top_k_n: int | None = None,
) -> dict[str, Any]:
    """Classify one ranking row. rank is 1-based (1 = best mean net%).

    First matching rule wins (top → bottom):

    1. mcpt_pass_5pct True  → healthy / packet / high
    2. mcpt_pass_5pct False → noise / skip / low
    3. MCPT None + top-K + mean/trades thresholds → candidate / packet / med
    4. positive mean + enough trades → watch / watch / low
    5. else → noise / skip / low
    """
    thr_trades = min_trades() if min_trades_n is None else min_trades_n
    thr_mean = min_mean_pct() if min_mean is None else min_mean
    thr_k = top_k() if top_k_n is None else top_k_n

    n_trades = int(row.get("n_trades") or 0)
    mean_p = float(row.get("mean_net_pnl_pct") or 0.0)
    mcpt_pass = row.get("mcpt_pass_5pct")  # True | False | None
    mcpt_p = row.get("mcpt_p")

    # 1. MCPT pass
    if mcpt_pass is True:
        p_s = f"{mcpt_p:.4f}" if isinstance(mcpt_p, (int, float)) else "?"
        return {
            "status": "healthy",
            "priority": "high",
            "action": "packet",
            "reason": f"mcpt pass_5pct (p={p_s}); mean_net%>0",
        }

    # 2. Explicit MCPT failure vetoes even a good mean
    if mcpt_pass is False:
        return {
            "status": "noise",
            "priority": "low",
            "action": "skip",
            "reason": "mcpt fail; needs soak",
        }

    # 3. MCPT not run — top-K mean path
    if (
        mcpt_pass is None
        and rank <= thr_k
        and mean_p >= thr_mean
        and n_trades >= thr_trades
    ):
        return {
            "status": "candidate",
            "priority": "med",
            "action": "packet",
            "reason": (
                f"top-K mean net% (rank={rank}, n≥{thr_trades}, "
                f"mean≥{thr_mean})"
            ),
        }

    # 4. Positive but not top-K / no MCPT
    if mean_p > 0 and n_trades >= thr_trades:
        return {
            "status": "watch",
            "priority": "low",
            "action": "watch",
            "reason": "positive but not top-K / no MCPT",
        }

    # 5. Else noise
    return {
        "status": "noise",
        "priority": "low",
        "action": "skip",
        "reason": "below thresholds or non-positive mean",
    }
