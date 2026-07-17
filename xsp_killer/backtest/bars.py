"""OHLC bar loaders: committed fixtures or UW (TipDrop) with local cache.

Regular loading remains fail-open. Strict callers can require fresh, metadata-
verified UW cache entries and never receive fixture-backed data.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
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
CACHE_CLOCK_SKEW = timedelta(minutes=5)
"""Maximum tolerated provider/cache clock lead for ``fetched_at``."""


def _safe_error(exc: Exception) -> str:
    message = str(exc)
    secret = os.getenv("UNUSUAL_WHALES_API_KEY", "").strip()
    return message.replace(secret, "REDACTED") if secret else message


class FixtureFallbackError(RuntimeError):
    """Raised by strict UW loading when fixture substitution would be required.

    Distinct from fail-open ``load_bars`` / ``load_uw_bars``, which return
    fixtures or None. Strict mode never returns fixture data.
    """


class InsufficientBarsError(ValueError):
    """Raised when true UW bars exist but fail coverage floors."""


def _to_datetime_index_like(values: Any) -> pd.DatetimeIndex | pd.Series:
    """Parse timestamps; handle mixed DST offsets without masking other errors.

    Naive strings stay wall-clock (utc=False) so fixtures localize as ET.
    Cache CSVs written with America/New_York may mix -04:00/-05:00 offsets;
    pandas 3 raises ValueError on mixed timezones — only then use utc=True
    so aware values normalize before the caller's tz_convert to ET.
    """
    try:
        parsed = pd.to_datetime(values, utc=False)
    except ValueError as exc:
        if "Mixed timezones" not in str(exc):
            raise
        return pd.to_datetime(values, utc=True)

    # pandas 2 currently warns and returns an object Index/Series for mixed
    # offsets instead of raising; pandas 3 raises the ValueError handled above.
    # Normalize both behaviors so callers always receive datetime-like values.
    if isinstance(parsed, pd.Series):
        if not pd.api.types.is_datetime64_any_dtype(parsed.dtype):
            return pd.to_datetime(values, utc=True)
    elif not isinstance(parsed, pd.DatetimeIndex):
        return pd.DatetimeIndex(pd.to_datetime(values, utc=True))
    return parsed


def _normalize_ohlc(
    df: pd.DataFrame,
    *,
    ts_col: str | None = None,
    interval: BarInterval | None = None,
) -> pd.DataFrame:
    """Standardize OHLCV while preserving daily provider session dates."""
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

    daily_dates: list[Any] | None = None
    if interval == "1d":
        date_values = out["ts"] if "ts" in out.columns else out.index
        daily_dates = [pd.Timestamp(value).date() for value in date_values]

    if not isinstance(out.index, pd.DatetimeIndex):
        if "ts" in out.columns:
            out["ts"] = _to_datetime_index_like(out["ts"])
            out = out.set_index("ts")
        else:
            out.index = _to_datetime_index_like(out.index)

    if daily_dates is not None:
        out.index = pd.DatetimeIndex(daily_dates).tz_localize("America/New_York")
    elif out.index.tz is None:
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
    return _normalize_ohlc(df, interval="1d")


def load_fixture_intraday(path: Path | None = None) -> pd.DataFrame:
    p = path or FIXTURE_INTRADAY
    df = pd.read_csv(p)
    return _normalize_ohlc(df, interval="15m")


def _cache_key(ticker: str, period: str, interval: str) -> str:
    safe = f"uw_hist_{ticker}_{period}_{interval}".replace("/", "_").replace(" ", "")
    return f"{safe}.csv"


def _cache_path(ticker: str, period: str, interval: str) -> Path:
    return CACHE_DIR / _cache_key(ticker, period, interval)


def _metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.meta.json")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        temp_path.replace(path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _write_cache(
    df: pd.DataFrame,
    path: Path,
    *,
    ticker: str | None = None,
    period: str | None = None,
    interval: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writes_metadata = ticker is not None and period is not None and interval is not None
    if writes_metadata:
        # Never let metadata for an older CSV authenticate a newly replaced CSV.
        _metadata_path(path).unlink(missing_ok=True)
    out = df.copy()
    out = out.reset_index()
    # first column is the index we reset
    ts_name = out.columns[0]
    out = out.rename(columns={ts_name: "ts"})
    csv_bytes = out.to_csv(index=False).encode("utf-8")
    _atomic_write_bytes(path, csv_bytes)
    logger.info("uw cache wrote %s (%d rows)", path, len(out))
    if not writes_metadata:
        return
    metadata = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "period": period,
        "interval": interval,
        "first_bar": df.index[0].isoformat(),
        "last_bar": df.index[-1].isoformat(),
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
    }
    try:
        _atomic_write_text(
            _metadata_path(path),
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        )
    except OSError as exc:
        logger.warning("uw cache metadata write failed %s: %s", path, exc)


def _read_cache(
    path: Path,
    *,
    interval: BarInterval | None = None,
    expected_sha256: str | None = None,
    expected_first_bar: str | None = None,
    expected_last_bar: str | None = None,
) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        csv_bytes = path.read_bytes()
        if expected_sha256 is not None:
            actual_sha256 = hashlib.sha256(csv_bytes).hexdigest()
            if actual_sha256 != expected_sha256:
                raise ValueError("cache CSV SHA-256 does not match metadata")
        df = pd.read_csv(io.BytesIO(csv_bytes))
        normalized = _normalize_ohlc(df, interval=interval)
        if expected_first_bar is not None:
            actual_first = normalized.index[0].isoformat()
            if actual_first != expected_first_bar:
                raise ValueError("cache first_bar does not match metadata")
        if expected_last_bar is not None:
            actual_last = normalized.index[-1].isoformat()
            if actual_last != expected_last_bar:
                raise ValueError("cache last_bar does not match metadata")
        return normalized
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("uw cache read failed %s: %s", path, exc)
        return None


def _max_age_delta(value: timedelta | float | int | None) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value
    return timedelta(hours=float(value))


def _cache_status(
    path: Path,
    *,
    ticker: str,
    period: str,
    interval: str,
    max_cache_age: timedelta | float | int | None,
    refresh: bool,
) -> dict[str, Any]:
    status: dict[str, Any] = {
        "cache_used": False,
        "cache_fresh": None,
        "cache_age_hours": None,
        "cache_metadata_present": False,
        "refresh_requested": bool(refresh),
    }
    if refresh:
        return status
    metadata_path = _metadata_path(path)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(str(metadata["fetched_at"]))
        if fetched_at.tzinfo is None:
            raise ValueError("fetched_at must include timezone")
        identity_matches = (
            metadata.get("ticker") == ticker
            and metadata.get("period") == period
            and metadata.get("interval") == interval
        )
        if not identity_matches:
            raise ValueError("cache metadata identity mismatch")
        now = datetime.now(timezone.utc)
        fetched_at_utc = fetched_at.astimezone(timezone.utc)
        if fetched_at_utc > now + CACHE_CLOCK_SKEW:
            raise ValueError("cache fetched_at exceeds tolerated 5-minute clock skew")
        age = max(timedelta(0), now - fetched_at_utc)
        if max_cache_age is not None:
            for field in ("csv_sha256", "first_bar", "last_bar"):
                if not metadata.get(field):
                    raise ValueError(f"cache metadata missing {field}")
            status["_expected_sha256"] = str(metadata["csv_sha256"])
            status["_expected_first_bar"] = str(metadata["first_bar"])
            status["_expected_last_bar"] = str(metadata["last_bar"])
        status["cache_metadata_present"] = True
        status["cache_age_hours"] = age.total_seconds() / 3600.0
        max_age = _max_age_delta(max_cache_age)
        status["cache_fresh"] = None if max_age is None else age <= max_age
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.info("uw cache metadata unavailable/stale %s: %s", metadata_path, exc)
        if max_cache_age is not None:
            status["cache_fresh"] = False
    return status


def _get_uw_provider() -> Any | None:
    """Mirror ``uw_shadow._get_provider`` — TipDrop UnusualWhalesProvider or None."""
    try:
        from xsp_killer.uw_shadow import _get_provider

        return _get_provider()
    except Exception as exc:  # noqa: BLE001
        logger.warning("uw provider import failed (fail-open): %s", _safe_error(exc))
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
        logger.warning("UW fetch failed %s %s: %s", ticker, interval, _safe_error(exc))
        return None

    if raw is None:
        return None
    if isinstance(raw, pd.DataFrame):
        if raw.empty:
            return None
        return _normalize_ohlc(raw, interval=interval)
    # Some providers return list-of-dicts
    try:
        df = pd.DataFrame(raw)
        if df.empty:
            return None
        return _normalize_ohlc(df, interval=interval)
    except Exception as exc:  # noqa: BLE001
        logger.warning("UW frame normalize failed: %s", _safe_error(exc))
        return None


def load_uw_bars(
    ticker: str = "SPY",
    *,
    period: str = "2y",
    interval: BarInterval = "1d",
    use_cache: bool = True,
    max_cache_age: timedelta | float | int | None = None,
    refresh: bool = False,
) -> pd.DataFrame | None:
    """Fetch UW OHLC, caching under ``.local/uw_cache/``. Returns None on failure.

    ``max_cache_age`` accepts a timedelta or hours. Its default preserves the
    historical behavior: cache CSVs are accepted even without metadata.
    """
    cache_p = _cache_path(ticker, period, interval)
    status = _cache_status(
        cache_p,
        ticker=ticker,
        period=period,
        interval=interval,
        max_cache_age=max_cache_age,
        refresh=refresh,
    )
    cache_allowed = max_cache_age is None or status["cache_fresh"] is True
    if use_cache and not refresh and cache_allowed:
        verify_identity = max_cache_age is not None
        cached = _read_cache(
            cache_p,
            interval=interval,
            expected_sha256=(
                status.get("_expected_sha256") if verify_identity else None
            ),
            expected_first_bar=(
                status.get("_expected_first_bar") if verify_identity else None
            ),
            expected_last_bar=(
                status.get("_expected_last_bar") if verify_identity else None
            ),
        )
        if cached is not None and not cached.empty:
            logger.info("uw cache hit %s (%d rows)", cache_p.name, len(cached))
            status["cache_used"] = True
            status["cache_identity_verified"] = bool(verify_identity)
            for key in (
                "_expected_sha256",
                "_expected_first_bar",
                "_expected_last_bar",
            ):
                status.pop(key, None)
            cached.attrs["uw_cache_status"] = status
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
    for key in ("_expected_sha256", "_expected_first_bar", "_expected_last_bar"):
        status.pop(key, None)
    if use_cache:
        try:
            _write_cache(
                df,
                cache_p,
                ticker=ticker,
                period=period,
                interval=interval,
            )
        except OSError as exc:
            logger.warning("uw cache write failed %s: %s", cache_p, exc)
    status.update(
        {
            "cache_used": False,
            "cache_fresh": True,
            "cache_age_hours": 0.0,
            "cache_metadata_present": _metadata_path(cache_p).is_file(),
        }
    )
    df.attrs["uw_cache_status"] = status
    return df


def load_uw_bars_strict(
    ticker: str = "SPY",
    *,
    period: str = "2y",
    interval: BarInterval = "1d",
    use_cache: bool = True,
    min_bars: int = 1,
    min_sessions: int = 0,
    max_cache_age: timedelta | float | int | None = timedelta(hours=24),
    refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load true UW OHLC only — never return fixtures.

    Raises:
        FixtureFallbackError: missing key/provider/empty/fetch failure (would
            have required fixture substitution).
        InsufficientBarsError: UW frame present but below min_bars/min_sessions.

    Returns:
        ``(frame, coverage)`` where *coverage* includes start/end/n_bars/
        n_sessions/interval/has_overnight_bars/session_phases_observed for
        15m bars, or a daily-oriented summary for 1d.
    """
    key = os.getenv("UNUSUAL_WHALES_API_KEY", "").strip()
    if not key:
        raise FixtureFallbackError(
            "strict UW load refused: UNUSUAL_WHALES_API_KEY unset/empty "
            "(would fall back to fixture)"
        )

    df = load_uw_bars(
        ticker,
        period=period,
        interval=interval,
        use_cache=use_cache,
        max_cache_age=max_cache_age,
        refresh=refresh,
    )
    if df is None or df.empty:
        raise FixtureFallbackError(
            f"strict UW load refused: no UW bars for {ticker} "
            f"period={period} interval={interval} (empty/provider/cache miss)"
        )

    if interval == "15m":
        # Lazy import avoids circular import with intraday session helpers.
        from xsp_killer.backtest.intraday import bar_coverage

        coverage = bar_coverage(df)
    else:
        start = df.index[0]
        end = df.index[-1]
        # Daily: sessions ≈ distinct calendar dates with bars
        n_sess = int(df.index.normalize().nunique())
        coverage = {
            "n_bars": int(len(df)),
            "n_sessions": n_sess,
            "has_overnight_bars": False,
            "session_phases_observed": ["daily"],
            "start": (start.isoformat() if hasattr(start, "isoformat") else str(start)),
            "end": end.isoformat() if hasattr(end, "isoformat") else str(end),
            "interval": "1d",
        }
    coverage.update(df.attrs.get("uw_cache_status") or {})

    n_bars = int(coverage.get("n_bars") or 0)
    n_sessions = int(coverage.get("n_sessions") or 0)
    if n_bars < int(min_bars):
        raise InsufficientBarsError(
            f"strict UW insufficient bars: {n_bars} < min_bars={min_bars} "
            f"(interval={interval}, period={period})"
        )
    if int(min_sessions) > 0 and n_sessions < int(min_sessions):
        raise InsufficientBarsError(
            f"strict UW insufficient sessions: {n_sessions} < "
            f"min_sessions={min_sessions} (interval={interval}, period={period})"
        )
    return df, coverage


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
    max_cache_age: timedelta | float | int | None = None,
    refresh: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Load OHLC bars.

    Returns ``(frame, source_label)`` where *source_label* is ``fixture``,
    ``uw``, or ``fixture_fallback`` when UW mode fell open to fixtures.
    """
    source = "fixture"
    if mode == "uw":
        df = load_uw_bars(
            ticker,
            period=period,
            interval=interval,
            max_cache_age=max_cache_age,
            refresh=refresh,
        )
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
