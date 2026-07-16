"""UW bar-cache freshness and metadata behavior."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from xsp_killer.backtest import bars as bars_module
from xsp_killer.backtest.bars import (
    FixtureFallbackError,
    _cache_path,
    _write_cache,
    load_uw_bars,
    load_uw_bars_strict,
)


def _daily_bars(close: float = 500.0) -> pd.DataFrame:
    index = pd.date_range("2026-07-13", periods=3, freq="B", tz="America/New_York")
    return pd.DataFrame(
        {
            "open": [close] * 3,
            "high": [close + 1.0] * 3,
            "low": [close - 1.0] * 3,
            "close": [close] * 3,
            "volume": [1_000_000.0] * 3,
        },
        index=index,
    )


def _write_metadata(
    cache_path,
    *,
    fetched_at: datetime,
    ticker: str = "SPY",
    period: str = "5y",
    interval: str = "1d",
) -> None:
    metadata = {
        "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
        "ticker": ticker,
        "period": period,
        "interval": interval,
        "first_bar": "2026-07-13T00:00:00-04:00",
        "last_bar": "2026-07-15T00:00:00-04:00",
    }
    cache_path.with_name(f"{cache_path.name}.meta.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )


def test_write_cache_adds_secret_free_sidecar_metadata(monkeypatch, tmp_path):
    cache_path = tmp_path / "uw_hist_SPY_5y_1d.csv"
    secret = "uw-test-secret-never-write"
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", secret)

    _write_cache(
        _daily_bars(),
        cache_path,
        ticker="SPY",
        period="5y",
        interval="1d",
    )

    metadata_path = tmp_path / "uw_hist_SPY_5y_1d.csv.meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert set(metadata) == {
        "fetched_at",
        "ticker",
        "period",
        "interval",
        "first_bar",
        "last_bar",
    }
    assert metadata["ticker"] == "SPY"
    assert metadata["period"] == "5y"
    assert metadata["interval"] == "1d"
    assert metadata["first_bar"].startswith("2026-07-13")
    assert metadata["last_bar"].startswith("2026-07-15")
    datetime.fromisoformat(metadata["fetched_at"])
    assert secret not in metadata_path.read_text(encoding="utf-8")


def test_provider_error_output_redacts_api_key(monkeypatch, caplog):
    secret = "uw-test-secret-never-log"
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", secret)

    class FailingProvider:
        def get_history(self, *args):
            raise RuntimeError(f"request rejected for key {secret}")

    monkeypatch.setattr(bars_module, "_get_uw_provider", lambda: FailingProvider())
    loaded = load_uw_bars(
        "SPY_TEST_NO_CACHE",
        period="5y",
        interval="1d",
        use_cache=False,
    )

    assert loaded is None
    assert secret not in caplog.text
    assert "REDACTED" in caplog.text


def test_metadata_write_failure_cannot_leave_old_metadata(monkeypatch, tmp_path):
    cache_path = tmp_path / "uw_hist_SPY_5y_1d.csv"
    metadata_path = tmp_path / "uw_hist_SPY_5y_1d.csv.meta.json"
    metadata_path.write_text('{"fetched_at": "future"}', encoding="utf-8")
    atomic_write = bars_module._atomic_write_text

    def fail_metadata(path, text):
        if path == metadata_path:
            raise OSError("simulated metadata failure")
        atomic_write(path, text)

    monkeypatch.setattr(bars_module, "_atomic_write_text", fail_metadata)
    _write_cache(
        _daily_bars(),
        cache_path,
        ticker="SPY",
        period="5y",
        interval="1d",
    )

    assert cache_path.is_file()
    assert not metadata_path.exists()


def test_strict_stale_cache_fetch_failure_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(bars_module, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "uw-test-secret-never-log")
    cache_path = _cache_path("SPY", "5y", "1d")
    _write_cache(_daily_bars(), cache_path)
    _write_metadata(
        cache_path,
        fetched_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    fetched = []

    def fail_fetch(*args, **kwargs):
        fetched.append((args, kwargs))
        return None

    monkeypatch.setattr(bars_module, "_fetch_uw_history", fail_fetch)

    with pytest.raises(FixtureFallbackError):
        load_uw_bars_strict(
            "SPY",
            period="5y",
            interval="1d",
            max_cache_age=timedelta(hours=24),
        )
    assert len(fetched) == 1


def test_strict_fresh_cache_is_used(monkeypatch, tmp_path):
    monkeypatch.setattr(bars_module, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "test-key")
    cache_path = _cache_path("SPY", "5y", "1d")
    _write_cache(_daily_bars(501.0), cache_path)
    _write_metadata(cache_path, fetched_at=datetime.now(timezone.utc))

    def unexpected_fetch(*args, **kwargs):
        raise AssertionError("fresh cache must not fetch")

    monkeypatch.setattr(bars_module, "_fetch_uw_history", unexpected_fetch)
    loaded, coverage = load_uw_bars_strict(
        "SPY",
        period="5y",
        interval="1d",
        max_cache_age=timedelta(hours=24),
    )

    assert loaded["close"].iloc[-1] == 501.0
    assert coverage["cache_fresh"] is True
    assert coverage["cache_used"] is True
    assert coverage["refresh_requested"] is False


def test_refresh_bypasses_fresh_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(bars_module, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "test-key")
    cache_path = _cache_path("SPY", "5y", "1d")
    _write_cache(_daily_bars(501.0), cache_path)
    _write_metadata(cache_path, fetched_at=datetime.now(timezone.utc))
    fetched = []

    def fetch(*args, **kwargs):
        fetched.append((args, kwargs))
        return _daily_bars(509.0)

    monkeypatch.setattr(bars_module, "_fetch_uw_history", fetch)
    loaded, coverage = load_uw_bars_strict(
        "SPY",
        period="5y",
        interval="1d",
        max_cache_age=timedelta(hours=24),
        refresh=True,
    )

    assert len(fetched) == 1
    assert loaded["close"].iloc[-1] == 509.0
    assert coverage["cache_used"] is False
    assert coverage["refresh_requested"] is True


def test_old_cache_without_metadata_is_stale_only_for_strict(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(bars_module, "CACHE_DIR", tmp_path)
    cache_path = _cache_path("SPY", "5y", "1d")
    _write_cache(_daily_bars(503.0), cache_path)

    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "")
    regular = load_uw_bars("SPY", period="5y", interval="1d")
    assert regular is not None
    assert regular["close"].iloc[-1] == 503.0

    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "test-key")
    monkeypatch.setattr(bars_module, "_fetch_uw_history", lambda *a, **k: None)
    with pytest.raises(FixtureFallbackError):
        load_uw_bars_strict(
            "SPY",
            period="5y",
            interval="1d",
            max_cache_age=timedelta(hours=24),
        )
