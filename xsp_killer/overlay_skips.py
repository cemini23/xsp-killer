"""Candidate overlay skips — log-only. Never veto paper or live.

Reasons are pre-registered: put_tide, neg_gex, king_below.
Promotion needs a longer join than the 23-day TipDrop tide journal.
"""

from __future__ import annotations

from typing import Any


def _f(val: Any) -> float | None:
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def evaluate_overlay_skips(overlays: dict[str, Any] | None) -> dict[str, Any]:
    reasons: list[str] = []
    data = overlays or {}

    tide = data.get("market_tide") or {}
    if str(tide.get("bias") or "").lower() == "put":
        reasons.append("put_tide")

    tickers = (data.get("tipseeker") or {}).get("tickers") or {}
    spy = tickers.get("SPY") or {}
    gex = _f(spy.get("total_gex"))
    if gex is not None and gex < 0:
        reasons.append("neg_gex")

    king = _f(spy.get("king_strike"))
    spot = _f(spy.get("spot"))
    if king is not None and spot is not None and king < spot:
        reasons.append("king_below")

    return {
        "would_skip": bool(reasons),
        "reasons": reasons,
        "veto": False,
        "shadow_only": True,
    }
