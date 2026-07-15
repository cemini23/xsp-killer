"""TipDrop UW Advanced shadow overlay — log/brief only.

Attaches SPY flow + local GEX fallback + net-prem ticks + iv-rank + UW
gex-levels (+ optional dark pool) to Lane A monitor reports.
Never places, never vetoes. Fail-open if TipDrop/UW unavailable.
Shares TipDrop's UW rate limiter / daily budget (no duplicate limiter).
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("xsp_killer.uw_shadow")

_DEFAULT_TIPDROP_ROOT = Path(r"C:\Users\Owner\institutional-shadow")
_TRUE = ("1", "true", "yes", "on")


def _uw_enabled() -> bool:
    return os.getenv("XSP_UW_SHADOW", "false").strip().lower() in _TRUE


def _darkpool_enabled() -> bool:
    return os.getenv("XSP_UW_SHADOW_DARKPOOL", "false").strip().lower() in _TRUE


def _tipdrop_root() -> Path:
    raw = os.getenv("XSP_UW_TIPDROP_ROOT", "").strip()
    return Path(raw) if raw else _DEFAULT_TIPDROP_ROOT


def _ensure_tipdrop_on_path() -> Path:
    root = _tipdrop_root()
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    return root


def _f(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _get_provider() -> Any | None:
    """Return TipDrop UnusualWhalesProvider, or None on any failure."""
    try:
        _ensure_tipdrop_on_path()
        from data.fetcher import UnusualWhalesProvider, get_provider
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.debug("uw_shadow TipDrop import failed (fail-open): %s", exc)
        return None

    try:
        provider = get_provider()
    except Exception as exc:  # noqa: BLE001
        logger.debug("uw_shadow get_provider failed (fail-open): %s", exc)
        return None

    if provider is None or not isinstance(provider, UnusualWhalesProvider):
        logger.debug(
            "uw_shadow provider unavailable or not UnusualWhales (%s)",
            type(provider).__name__ if provider is not None else None,
        )
        return None
    return provider


def build_flow_summary(provider: Any, ticker: str = "SPY") -> dict[str, Any] | None:
    """Summarize recent UW flow alerts for *ticker*. Returns None on failure."""
    try:
        alerts = provider.get_flow_alerts(ticker, limit=50) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug("uw_shadow flow fetch failed: %s", exc)
        return None

    if not isinstance(alerts, list):
        return None

    call_prem = 0.0
    put_prem = 0.0
    biggest: dict[str, Any] | None = None
    biggest_prem = -1.0

    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        kind = str(alert.get("type") or "").upper()
        prem = _f(alert.get("total_premium"))
        if kind == "CALL":
            call_prem += prem
        elif kind == "PUT":
            put_prem += prem
        if prem > biggest_prem:
            biggest_prem = prem
            biggest = {
                "type": kind or None,
                "premium": prem,
                "strike": _f(alert.get("strike")) or None,
                "expiry": alert.get("expiry"),
                "has_sweep": bool(alert.get("has_sweep")),
            }

    net = call_prem - put_prem
    if abs(net) < 1.0:
        bias = "neutral"
    elif net > 0:
        bias = "call"
    else:
        bias = "put"

    return {
        "ticker": ticker,
        "n_alerts": len(alerts),
        "call_prem": round(call_prem, 2),
        "put_prem": round(put_prem, 2),
        "net_prem_bias": bias,
        "net_prem": round(net, 2),
        "biggest_alert": biggest,
    }


def _top_wall_strike(by_strike: Any, spot: float, side: str) -> float | None:
    """Best-effort top call (above spot) or put (below spot) wall strike."""
    try:
        import pandas as pd

        if (
            by_strike is None
            or not isinstance(by_strike, pd.DataFrame)
            or by_strike.empty
        ):
            return None
        if side == "call":
            subset = by_strike[by_strike["strike"] >= spot].copy()
            if subset.empty or "gex_call" not in subset.columns:
                return None
            idx = subset["gex_call"].abs().idxmax()
            return float(subset.loc[idx, "strike"])
        subset = by_strike[by_strike["strike"] <= spot].copy()
        if subset.empty or "gex_put" not in subset.columns:
            return None
        idx = subset["gex_put"].abs().idxmax()
        return float(subset.loc[idx, "strike"])
    except Exception:  # noqa: BLE001
        return None


def build_gex_summary(provider: Any, ticker: str = "SPY") -> dict[str, Any] | None:
    """Compute GEX wall summary via TipDrop gamma_exposure. Skip if unavailable."""
    try:
        from scanner.gamma_exposure import compute_gex, dominant_wall_side
    except Exception as exc:  # noqa: BLE001
        logger.debug("uw_shadow GEX import skipped: %s", exc)
        return None

    try:
        profile = compute_gex(ticker, provider=provider, max_expiries=4)
        if profile is None:
            return None
        wall_side = dominant_wall_side(profile)
        spot = float(profile.spot)
        return {
            "ticker": ticker,
            "spot": spot,
            "wall_side": wall_side,
            "gamma_wall": float(profile.gamma_wall),
            "top_call_wall": _top_wall_strike(profile.by_strike, spot, "call"),
            "top_put_wall": _top_wall_strike(profile.by_strike, spot, "put"),
            "net_gex_dollars": float(profile.total_gex),
            "flip_point": float(profile.flip_point),
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("uw_shadow GEX compute failed: %s", exc)
        return None


def build_darkpool_summary(provider: Any, ticker: str = "SPY") -> dict[str, Any] | None:
    """Optional dark-pool summary; gated by XSP_UW_SHADOW_DARKPOOL."""
    if not _darkpool_enabled():
        return None
    try:
        prints = provider.get_darkpool_prints(ticker, limit=50) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug("uw_shadow darkpool fetch failed: %s", exc)
        return None

    if not isinstance(prints, list):
        return None

    total_notional = 0.0
    buy_n = 0
    sell_n = 0
    for row in prints:
        if not isinstance(row, dict):
            continue
        total_notional += _f(row.get("notional") or row.get("premium"))
        side = str(row.get("side") or "").upper()
        if side in ("BUY", "B", "ASK"):
            buy_n += 1
        elif side in ("SELL", "S", "BID"):
            sell_n += 1

    return {
        "ticker": ticker,
        "n_prints": len(prints),
        "total_notional": round(total_notional, 2),
        "buy_prints": buy_n,
        "sell_prints": sell_n,
    }


def build_net_prem_summary(provider: Any, ticker: str = "SPY") -> dict[str, Any] | None:
    """Sum UW net-prem-ticks for *ticker*. Returns None on failure."""
    if not hasattr(provider, "_request"):
        return None
    try:
        payload = provider._request(
            f"/stock/{ticker}/net-prem-ticks",
            cache_key=f"uw:npt:{ticker}",
            cache_ttl=60,
        )
        rows = (payload or {}).get("data")
        if not isinstance(rows, list) or not rows:
            return None

        call_sum = 0.0
        put_sum = 0.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            call_sum += _f(row.get("net_call_premium"))
            put_sum += _f(row.get("net_put_premium"))

        net = call_sum - put_sum
        if abs(net) < 1.0:
            bias = "neutral"
        elif net > 0:
            bias = "call"
        else:
            bias = "put"

        last = rows[-1] if isinstance(rows[-1], dict) else {}
        return {
            "ticker": ticker,
            "n_ticks": len(rows),
            "net_call_prem": round(call_sum, 2),
            "net_put_prem": round(put_sum, 2),
            "net_prem": round(net, 2),
            "net_prem_bias": bias,
            "last_tape_time": last.get("tape_time"),
        }
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.debug("uw_shadow net-prem fetch failed: %s", exc)
        return None


def build_iv_rank_summary(provider: Any, ticker: str = "SPY") -> dict[str, Any] | None:
    """UW IV rank for *ticker*. Returns None on failure."""
    if not hasattr(provider, "get_iv_rank_uw"):
        return None
    try:
        row = provider.get_iv_rank_uw(ticker)
        if row is None or not isinstance(row, dict):
            return None

        raw = row.get("iv_rank_1y")
        if raw is None or raw == "":
            raw = row.get("iv_rank")
        iv_rank_1y = _f(raw) if raw is not None and raw != "" else None

        return {
            "ticker": ticker,
            "iv_rank_1y": iv_rank_1y,
            "raw": row,
        }
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.debug("uw_shadow iv-rank fetch failed: %s", exc)
        return None


def build_gex_levels_summary(
    provider: Any, ticker: str = "SPY"
) -> dict[str, Any] | None:
    """UW gex-levels for *ticker*. Returns None on failure."""
    if not hasattr(provider, "_request"):
        return None
    try:
        payload = provider._request(
            f"/stock/{ticker}/gex-levels",
            cache_key=f"uw:gexlvl:{ticker}",
            cache_ttl=300,
        )
        rows = (payload or {}).get("data")
        if not isinstance(rows, list) or not rows:
            return None

        latest = rows[-1]
        if not isinstance(latest, dict):
            return None

        logger.debug("uw_shadow gex-levels keys: %s", list(latest.keys()))

        gw_raw = latest.get("gamma_wall")
        if gw_raw is None or gw_raw == "":
            gw_raw = latest.get("gex_level")
        cw_raw = latest.get("call_wall")
        pw_raw = latest.get("put_wall")

        return {
            "ticker": ticker,
            "n_rows": len(rows),
            "latest_raw": latest,
            "gamma_wall": _f(gw_raw) if gw_raw is not None and gw_raw != "" else None,
            "call_wall": _f(cw_raw) if cw_raw is not None and cw_raw != "" else None,
            "put_wall": _f(pw_raw) if pw_raw is not None and pw_raw != "" else None,
        }
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.debug("uw_shadow gex-levels fetch failed: %s", exc)
        return None


def build_monitor_uw_shadow(
    *,
    ticker: str = "SPY",
    now_et: datetime | None = None,
) -> dict[str, Any] | None:
    """Lane A monitor entry point. None when disabled or TipDrop/UW unavailable."""
    if not _uw_enabled():
        return None

    try:
        provider = _get_provider()
        if provider is None:
            return None

        fetched_at = datetime.now(timezone.utc).isoformat()
        if now_et is not None:
            fetched_at = now_et.astimezone(timezone.utc).isoformat()

        out: dict[str, Any] = {
            "shadow_only": True,
            "source": "uw_advanced",
            "fetched_at": fetched_at,
            "ticker": ticker,
            "flow": build_flow_summary(provider, ticker=ticker),
            "gex": build_gex_summary(provider, ticker=ticker),
            "net_prem": build_net_prem_summary(provider, ticker=ticker),
            "iv_rank": build_iv_rank_summary(provider, ticker=ticker),
            "gex_levels": build_gex_levels_summary(provider, ticker=ticker),
        }
        if _darkpool_enabled():
            out["darkpool"] = build_darkpool_summary(provider, ticker=ticker)
        return out
    except Exception as exc:  # noqa: BLE001 — fail-open; never block monitor
        logger.info("uw_shadow skipped (fail-open): %s", exc)
        return None
