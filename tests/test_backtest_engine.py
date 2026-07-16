"""Offline tests for Lane A backtest engine (fixture-only, no network)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from xsp_killer.backtest.bars import (
    _read_cache,
    _write_cache,
    load_bars,
    load_fixture_daily,
)
from xsp_killer.backtest.engine import run_backtest
from xsp_killer.backtest.option_model import bs_call, synthesize_call_premium
from xsp_killer.backtest.report import build_report, mcpt, write_report
from xsp_killer.backtest.sweep import run_variant_sweep, write_merged_rules_dict
from xsp_killer.lane_a_monitor import evaluate_exit_alerts
from xsp_killer.paper_economics import entry_fill_premium, exit_fill_premium

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
FIXTURE_DAILY = ROOT / "tests" / "fixtures" / "backtest" / "spy_daily.csv"


def _ohlc_frame(
    closes: list[float],
    *,
    start: date = date(2024, 1, 2),
) -> pd.DataFrame:
    """Build Mon–Fri OHLCV from a close series (open≈prior close)."""
    rows = []
    d = start
    prev = closes[0]
    for c in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        o = prev
        h = max(o, c) * 1.002
        low_px = min(o, c) * 0.998
        ts = datetime(d.year, d.month, d.day, 15, 45, tzinfo=ET)
        rows.append(
            {
                "ts": ts,
                "open": o,
                "high": h,
                "low": low_px,
                "close": c,
                "volume": 80_000_000,
            }
        )
        prev = c
        d += timedelta(days=1)
    df = pd.DataFrame(rows).set_index("ts")
    return df


def _green_uptrend(
    n: int = 80, start_px: float = 400.0, step: float = 1.5
) -> pd.DataFrame:
    """Strong uptrend so EMA21 rising and price > EMA → GREEN after SMA warmup."""
    closes = [start_px + i * step for i in range(n)]
    return _ohlc_frame(closes)


def _crash_after_green(n_warm: int = 60, crash_bars: int = 15) -> pd.DataFrame:
    up = [400.0 + i * 1.2 for i in range(n_warm)]
    peak = up[-1]
    crash = [peak * (1.0 - 0.03 * (k + 1)) for k in range(crash_bars)]
    return _ohlc_frame(up + crash)


def _flat_series(n: int = 80, px: float = 450.0) -> pd.DataFrame:
    # mild noise so BB exists; essentially flat
    closes = [px + (0.05 if i % 2 == 0 else -0.05) for i in range(n)]
    return _ohlc_frame(closes)


def _rules(
    tmp_path: Path,
    *,
    take_profit_pct: float = 0.10,
    stop_loss_pct: float = 0.20,
    swing_hold: bool = False,
    max_hold_dte: int = 0,
    require_upper_bb: bool = False,
    dte_min: int = 14,
    dte_target: int | None = 14,
    dte_pick: str = "target",
    regime_gate: str = "GREEN",
    max_open: int = 1,
) -> Path:
    overrides = {
        "logging": {"logic_version": "xsp_lane_a_bt_test"},
        "entry": {
            "regime_gate": regime_gate,
            "dte_pick": dte_pick,
            "dte_min": dte_min,
            "dte_max": 60,
            "strike_pick": "atm_only",
            "prior_day_spy_positive": False,
        },
        "paper_entry": {"max_open_positions": max_open, "quantity": 1},
        "exit": {
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
            "require_upper_bb_for_take_profit": require_upper_bb,
            "swing_hold": swing_hold,
            "max_hold_dte": max_hold_dte,
        },
        "ta": {
            "entry": {
                "mode": "close_window_only",
                "intraday_enabled": False,
                "require_vwap_reclaim": False,
            }
        },
    }
    if dte_target is not None:
        overrides["entry"]["dte_target"] = dte_target
    path = tmp_path / "bt_rules.yaml"
    write_merged_rules_dict(overrides, path)
    return path


def test_fixture_daily_loads():
    df = load_fixture_daily()
    assert len(df) >= 50
    for col in ("open", "high", "low", "close"):
        assert col in df.columns
    # Naive fixture dates must localize as America/New_York, not UTC.
    assert str(df.index.tz) == "America/New_York"
    first = df.index[0]
    assert first.year == 2024 and first.month == 1 and first.day == 2
    assert first.hour == 0 and first.minute == 0
    # Wall clock is ET midnight (not shifted as if UTC→ET).
    assert first.utcoffset() is not None


def test_uw_cache_roundtrip_across_dst_offsets(tmp_path):
    """Aware ET index with mixed -05:00/-04:00 must survive write→read.

    _write_cache serializes America/New_York timestamps with DST offsets;
    pandas 3 raises Mixed timezones on naive to_datetime — cache must not
    return None.
    """
    idx = pd.DatetimeIndex(
        [
            datetime(2024, 1, 15, 15, 45, tzinfo=ET),  # EST -05:00
            datetime(2024, 6, 15, 15, 45, tzinfo=ET),  # EDT -04:00
        ]
    )
    df = pd.DataFrame(
        {
            "open": [100.0, 110.0],
            "high": [101.0, 111.0],
            "low": [99.0, 109.0],
            "close": [100.5, 110.5],
            "volume": [1_000_000.0, 2_000_000.0],
        },
        index=idx,
    )
    path = tmp_path / "uw_hist_SPY_dst.csv"
    _write_cache(df, path)
    loaded = _read_cache(path)

    assert loaded is not None, "cache read must not fail-open on mixed DST offsets"
    assert len(loaded) == 2
    assert str(loaded.index.tz) == "America/New_York"
    assert list(loaded["close"]) == [100.5, 110.5]
    assert list(loaded["open"]) == [100.0, 110.0]
    # Wall times preserved in ET (not UTC-shifted).
    assert loaded.index[0].hour == 15 and loaded.index[0].month == 1
    assert loaded.index[1].hour == 15 and loaded.index[1].month == 6


def test_bs_call_atm_positive():
    prem = bs_call(500.0, 500.0, 30 / 365.0, 0.18)
    assert prem > 1.0
    synth = synthesize_call_premium(
        500.0, xsp_strike=500.0, dte=30, iv=0.18, premium_scale=10.0
    )
    assert synth > prem  # scaled


def test_uptrend_yields_take_profit(tmp_path):
    bars = _green_uptrend(90, step=2.0)
    rules = _rules(tmp_path, take_profit_pct=0.10, stop_loss_pct=0.50)
    res = run_backtest(bars, rules, variant_id="tp_test", iv_seed=0.20)
    assert res.trades, "expected at least one closed trade on uptrend"
    reasons = {t.exit_reason for t in res.trades}
    assert "take_profit" in reasons, f"expected take_profit, got {reasons}"


def test_crash_yields_stop_loss(tmp_path):
    bars = _crash_after_green()
    rules = _rules(
        tmp_path,
        take_profit_pct=0.80,  # hard to hit on crash
        stop_loss_pct=0.15,
        dte_target=28,
    )
    res = run_backtest(bars, rules, variant_id="sl_test", iv_seed=0.20)
    assert res.trades, "expected trades on crash path"
    reasons = {t.exit_reason for t in res.trades}
    assert "stop_loss" in reasons, f"expected stop_loss, got {reasons}"


def test_swing_hold_near_expiry_time_stop(tmp_path):
    # Short DTE + swing hold: force time_stop when dte <= max_hold_dte
    bars = _flat_series(70)
    rules = _rules(
        tmp_path,
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        swing_hold=True,
        max_hold_dte=2,
        dte_min=5,
        dte_target=5,
        dte_pick="target",
    )
    res = run_backtest(bars, rules, variant_id="hold_test", iv_seed=0.15)
    assert res.trades, "expected trades"
    reasons = {t.exit_reason for t in res.trades}
    assert "time_stop" in reasons or any(
        t.exit_reason == "time_stop" for t in res.trades
    ), f"expected time_stop, got {reasons}"


def test_max_hold_sessions_forces_exit(tmp_path):
    bars = _flat_series(60)
    rules = _rules(
        tmp_path,
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        dte_target=28,
    )
    result = run_backtest(
        bars,
        rules,
        variant_id="hold3",
        max_hold_sessions=3,
    )
    capped = [t for t in result.trades if t.exit_reason == "hold_cap"]
    assert capped
    assert all(t.bars_held == 3 for t in capped)
    assert all(t.sessions_held == 3 for t in capped)
    assert all(t.bar_interval == "1d" for t in capped)


def _dte_at_exit(trade) -> int:
    """Calendar DTE remaining on the exit bar (engine force-expiry axis)."""
    entry = datetime.fromisoformat(trade.entry_ts)
    exit_ = datetime.fromisoformat(trade.exit_ts)
    exp = entry.date() + timedelta(days=int(trade.dte_at_entry))
    return max(0, (exp - exit_.date()).days)


def test_take_profit_precedes_expiry_time_stop(tmp_path):
    """Strategy take_profit wins when dte<=0 would also force time_stop."""
    bars = _green_uptrend(75, step=2.0)
    rules = _rules(
        tmp_path,
        take_profit_pct=0.15,
        stop_loss_pct=0.90,
        dte_min=1,
        dte_target=1,
    )
    res = run_backtest(bars, rules, variant_id="tp_vs_expiry", iv_seed=0.20)
    winners = [
        t for t in res.trades if t.exit_reason == "take_profit" and _dte_at_exit(t) == 0
    ]
    assert winners, (
        f"expected take_profit on expiry bar (dte=0); got "
        f"{[(t.exit_reason, _dte_at_exit(t), t.net_pnl_pct) for t in res.trades[:8]]}"
    )
    assert all(t.exit_reason == "take_profit" for t in winners)
    assert not any(t.exit_reason == "time_stop" for t in winners)


def test_stop_loss_precedes_expiry_time_stop(tmp_path):
    """Strategy stop_loss wins when dte<=0 would also force time_stop."""
    n_warm = 58
    up = [400.0 + i * 1.5 for i in range(n_warm)]
    peak = up[-1]
    # Entry while still GREEN, then a sharp next-session crash into expiry.
    series = up + [peak + 1.0, peak * 0.90, peak * 0.88, peak * 0.87, peak * 0.86]
    bars = _ohlc_frame(series)
    rules = _rules(
        tmp_path,
        take_profit_pct=0.99,
        stop_loss_pct=0.10,
        dte_min=1,
        dte_target=1,
    )
    res = run_backtest(bars, rules, variant_id="sl_vs_expiry", iv_seed=0.20)
    winners = [
        t for t in res.trades if t.exit_reason == "stop_loss" and _dte_at_exit(t) == 0
    ]
    assert winners, (
        f"expected stop_loss on expiry bar (dte=0); got "
        f"{[(t.exit_reason, _dte_at_exit(t), t.net_pnl_pct) for t in res.trades]}"
    )
    assert all(t.exit_reason == "stop_loss" for t in winners)
    assert not any(t.exit_reason == "time_stop" for t in winners)


def test_expiry_time_stop_precedes_hold_cap(tmp_path):
    """Engine expiry force (dte<=0 time_stop) wins over max_hold_sessions hold_cap."""
    n_warm = 55
    up = [400.0 + i * 1.2 for i in range(n_warm)]
    peak = up[-1]
    flat = [peak + (0.02 if i % 2 == 0 else -0.02) for i in range(25)]
    bars = _ohlc_frame(up + flat)
    # Extreme TP/SL so strategy alerts stay quiet; dte=1 and hold=1 collide.
    rules = _rules(
        tmp_path,
        take_profit_pct=5.0,
        stop_loss_pct=5.0,
        dte_min=1,
        dte_target=1,
    )
    res = run_backtest(
        bars,
        rules,
        variant_id="expiry_vs_hold",
        iv_seed=0.18,
        max_hold_sessions=1,
    )
    collided = [
        t
        for t in res.trades
        if t.exit_reason != "end_of_series"
        and _dte_at_exit(t) == 0
        and t.bars_held >= 1
    ]
    assert collided, "expected closed trades at dte=0 with hold_cap also eligible"
    assert all(t.exit_reason == "time_stop" for t in collided), (
        f"expected time_stop over hold_cap, got "
        f"{sorted({t.exit_reason for t in collided})}"
    )
    assert not any(t.exit_reason == "hold_cap" for t in res.trades)


def test_determinism_same_fixture(tmp_path):
    bars = load_fixture_daily()
    rules = _rules(tmp_path, take_profit_pct=0.15, stop_loss_pct=0.25)
    a = run_backtest(bars, rules, variant_id="det", iv_seed=0.18)
    b = run_backtest(bars, rules, variant_id="det", iv_seed=0.18)
    assert [t.to_dict() for t in a.trades] == [t.to_dict() for t in b.trades]


def test_reuses_real_evaluate_exit_alerts_and_economics(tmp_path, monkeypatch):
    """Reuse-contract: engine must call real evaluate_exit_alerts / paper_economics."""
    calls = {"exit": 0, "entry_fill": 0}

    real_eval = evaluate_exit_alerts
    real_entry_fill = entry_fill_premium

    def spy_eval(*args, **kwargs):
        calls["exit"] += 1
        return real_eval(*args, **kwargs)

    def spy_fill(*args, **kwargs):
        calls["entry_fill"] += 1
        return real_entry_fill(*args, **kwargs)

    monkeypatch.setattr("xsp_killer.backtest.engine.evaluate_exit_alerts", spy_eval)
    monkeypatch.setattr("xsp_killer.backtest.engine.entry_fill_premium", spy_fill)

    bars = _green_uptrend(70, step=1.5)
    rules = _rules(tmp_path, take_profit_pct=0.12)
    res = run_backtest(bars, rules, variant_id="reuse")
    assert calls["exit"] > 0, "evaluate_exit_alerts never called"
    assert calls["entry_fill"] > 0, "entry_fill_premium never called"
    assert res.trades or res.n_entries_blocked >= 0


def test_mcpt_too_few_trades():
    out = mcpt([0.1, -0.05, 0.02], n_perm=50)
    assert out["pass_5pct"] is False
    assert out.get("note") == "too few trades"
    assert out["p_value"] == 1.0


def test_mcpt_positive_edge_can_pass():
    # Strong positive edge should pass at 5% with enough trades
    pnls = [0.15] * 30
    out = mcpt(pnls, n_perm=200, seed=1)
    assert out["n_trades"] == 30
    assert out["observed_mean_pct"] > 0
    assert out["pass_5pct"] is True


def test_uw_mode_fail_open_to_fixture(monkeypatch):
    monkeypatch.delenv("UNUSUAL_WHALES_API_KEY", raising=False)
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "")
    bars, source = load_bars(mode="uw", interval="1d")
    assert source == "fixture_fallback"
    assert len(bars) >= 50


def test_cli_fixture_mode_offline(tmp_path):
    out = tmp_path / "reports"
    env = {**os.environ, "UNUSUAL_WHALES_API_KEY": ""}
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "backtest_lane_a.py"),
            "--mode",
            "fixture",
            "--variants",
            "v2_14dte_atm,v2_28dte_atm",
            "--no-baseline",
            "--out",
            str(out),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    jsons = list(out.glob("lane_a_bt_*.json"))
    mds = list(out.glob("lane_a_bt_*.md"))
    assert jsons, "expected json report"
    assert mds, "expected markdown report"
    assert (
        "Ranked table" in mds[0].read_text(encoding="utf-8")
        or "mean" in mds[0].read_text(encoding="utf-8").lower()
    )


def test_cli_uw_mode_no_key_exit_zero(tmp_path):
    out = tmp_path / "reports_uw"
    env = {**os.environ}
    env["UNUSUAL_WHALES_API_KEY"] = ""
    env.pop("UNUSUAL_WHALES_API_KEY", None)
    # force empty
    env["UNUSUAL_WHALES_API_KEY"] = ""
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "backtest_lane_a.py"),
            "--mode",
            "uw",
            "--variants",
            "v2_14dte_atm",
            "--no-baseline",
            "--out",
            str(out),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "fell back" in (proc.stderr + proc.stdout).lower() or list(
        out.glob("*.json")
    )


def test_report_with_mcpt(tmp_path):
    bars = load_fixture_daily()
    results = run_variant_sweep(
        bars,
        variants="v2_14dte_atm",
        include_baseline=False,
        source="fixture",
    )
    payload = build_report(results, run_mcpt=True, n_perm=50, mode="fixture")
    assert payload["ranking"]
    assert "mcpt" in payload["ranking"][0] or "mcpt_p" in payload["ranking"][0]
    j, m = write_report(payload, tmp_path, stem="unit_bt")
    assert j.is_file() and m.is_file()


def test_exit_fill_premium_used_in_ranking_math():
    """Sanity: paper_economics helpers are the ranking building blocks."""
    from xsp_killer.paper_economics import PaperEconomics

    econ = PaperEconomics(
        commission_usd_per_contract=0.65,
        slippage_pct_of_premium=0.005,
        slippage_usd_per_share=0.12,
        slippage_max_pct_of_premium=0.015,
        premium_scale=10.0,
    )
    entry = entry_fill_premium(5.0, econ)
    exit_ = exit_fill_premium(6.0, econ)
    assert exit_ < 6.0
    assert entry > 5.0
    assert exit_ > entry  # still profitable after costs
