"""OHLC bar loaders: committed fixtures or UW (TipDrop) with local cache.

Fail-open: UW mode without key / import / empty frame falls back to fixture.
Cache lives under ``.local/uw_cache/`` (gitignored via ``.local/``).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

import pandas as pd

logger = logging.getLogger("xsp_killer.backtest.bars")

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DAILY = ROOT / "tests" / "fixtures" / "backtest" / "spy_daily.csv"
FIXTURE_INTRADAY = ROOT / "tests" / "fixtures" / "backtest" / "spy_15m.csv"
CACHE_DIR = ROOT / ".local" / "uw_cache"

BarMode = Literal["fixture", "uw"]
BarInterval = Literal["1d", "15m"]


def _normalize_ohlc(df: pd.DataFrame, *, ts_col: str | None = None) -> pd.DataFrame:
    """Standardize columns to lower-case OHLCV with DatetimeIndex (tz-aware ET)."""
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    rename = {}
    for cand, canon in (
        ("datetime", "ts"),
        ("timestamp", "ts"),
        ("date", "ts"),
        ("adj close", "close"),
        ("adj_close", "close"),
    ):
        if cand in out.columns and canon not in out.columns:
            rename[cand] = canon
    if rename:
        out = out.rename(columns=rename)

    if ts_col and ts_col in out.columns and "ts" not in out.columns:
        out = out.rename(columns={ts_col: "ts"})

    if not isinstance(out.index, pd.DatetimeIndex):
        if "ts" in out.columns:
            out["ts"] = pd.to_datetime(out["ts"], utc=False)
            out = out.set_index("ts")
        else:
            out.index = pd.to_datetime(out.index, utc=False)

    if out.index.tz is None:
        out.index = out.index.tz_localize(
            "America/New_York", ambiguous="infer", nonexistent="shift_forward"
        )
    else:
        out.index = out.index.tz_convert("America/New_York")

    for col in ("open", "high", "low", "close"):
        if col not in out.columns:
            raise ValueError(f"OHLC frame missing required column: {col}")
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    else:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)

    out = out.dropna(subset=["open", "high", "low", "close"]).sort_index()
    # Drop pure-duplicate timestamps (keep last)
    out = out[~out.index.duplicated(keep="last")]
    return out[["open", "high", "low", "close", "volume"]]


def load_fixture_daily(path: Path | None = None) -> pd.DataFrame:
    p = path or FIXTURE_DAILY
    df = pd.read_csv(p)
    return _normalize_ohlc(df)


def load_fixture_intraday(path: Path | None = None) -> pd.DataFrame:
    p = path or FIXTURE_INTRADAY
    df = pd.read_csv(p)
    return _normalize_ohlc(df)


def _cache_key(ticker: str, period: str, interval: str) -> str:
    safe = f"uw_hist_{ticker}_{period}_{interval}".replace("/", "_").replace(" ", "")
    return f"{safe}.csv"


def _cache_path(ticker: str, period: str, interval: str) -> Path:
    return CACHE_DIR / _cache_key(ticker, period, interval)


def _write_cache(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out = out.reset_index()
    # first column is the index we reset
    ts_name = out.columns[0]
    out = out.rename(columns={ts_name: "ts"})
    out.to_csv(path, index=False)
    logger.info("uw cache wrote %s (%d rows)", path, len(out))


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
        return _normalize_ohlc(df)
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("uw cache read failed %s: %s", path, exc)
        return None


def _get_uw_provider() -> Any | None:
    """Mirror ``uw_shadow._get_provider`` — TipDrop UnusualWhalesProvider or None."""
    try:
        from xsp_killer.uw_shadow import _get_provider

        return _get_provider()
    except Exception as exc:  # noqa: BLE001
        logger.warning("uw provider import failed (fail-open): %s", exc)
        return None


def _fetch_uw_history(
    ticker: str,
    *,
    period: str,
    interval: BarInterval,
) -> pd.DataFrame | None:
    provider = _get_uw_provider()
    if provider is None:
        logger.warning(
            "UW mode: no UnusualWhales provider (missing key/import) — will fall back"
        )
        return None
    try:
        if interval == "1d":
            raw = provider.get_history(ticker, period, "1d")
        else:
            raw = provider.get_intraday(ticker, "15m", period)
    except Exception as exc:  # noqa: BLE001
        logger.warning("UW fetch failed %s %s: %s", ticker, interval, exc)
        return None

    if raw is None:
        return None
    if isinstance(raw, pd.DataFrame):
        if raw.empty:
            return None
        return _normalize_ohlc(raw)
    # Some providers return list-of-dicts
    try:
        df = pd.DataFrame(raw)
        if df.empty:
            return None
        return _normalize_ohlc(df)
    except Exception as exc:  # noqa: BLE001
        logger.warning("UW frame normalize failed: %s", exc)
        return None


def load_uw_bars(
    ticker: str = "SPY",
    *,
    period: str = "2y",
    interval: BarInterval = "1d",
    use_cache: bool = True,
) -> pd.DataFrame | None:
    """Fetch UW OHLC, caching under ``.local/uw_cache/``. Returns None on failure."""
    cache_p = _cache_path(ticker, period, interval)
    if use_cache:
        cached = _read_cache(cache_p)
        if cached is not None and not cached.empty:
            logger.info("uw cache hit %s (%d rows)", cache_p.name, len(cached))
            return cached

    # Honor explicit empty key as fail-open without network
    key = os.getenv("UNUSUAL_WHALES_API_KEY", "").strip()
    if not key:
        logger.warning(
            "UW mode: UNUSUAL_WHALES_API_KEY unset — skip network, cache only"
        )
        return None

    df = _fetch_uw_history(ticker, period=period, interval=interval)
    if df is None or df.empty:
        return None
    if use_cache:
        _write_cache(df, cache_p)
    return df


def load_bars(
    mode: BarMode = "fixture",
    *,
    interval: BarInterval = "1d",
    ticker: str = "SPY",
    period: str = "2y",
    start: str | None = None,
    end: str | None = None,
    fixture_daily: Path | None = None,
    fixture_intraday: Path | None = None,
) -> tuple[pd.DataFrame, str]:
    """Load OHLC bars.

    Returns ``(frame, source_label)`` where *source_label* is ``fixture``,
    ``uw``, or ``fixture_fallback`` when UW mode fell open to fixtures.
    """
    source = "fixture"
    if mode == "uw":
        df = load_uw_bars(ticker, period=period, interval=interval)
        if df is not None and not df.empty:
            source = "uw"
        else:
            logger.warning(
                "UW mode fell back to committed fixtures (fail-open). "
                "Install UNUSUAL_WHALES_API_KEY + XSP_UW_TIPDROP_ROOT for live OHLC."
            )
            source = "fixture_fallback"
            df = (
                load_fixture_daily(fixture_daily)
                if interval == "1d"
                else load_fixture_intraday(fixture_intraday)
            )
    else:
        df = (
            load_fixture_daily(fixture_daily)
            if interval == "1d"
            else load_fixture_intraday(fixture_intraday)
        )

    if start:
        df = df[df.index >= pd.Timestamp(start, tz="America/New_York")]
    if end:
        df = df[df.index <= pd.Timestamp(end, tz="America/New_York")]

    if df.empty:
        raise ValueError(f"no bars after filters (mode={mode}, interval={interval})")
    return df, source
