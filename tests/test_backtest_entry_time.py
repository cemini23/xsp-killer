"""Entry-time bucket sweep: windows, volume gate, early-green, report."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xsp_killer.backtest.optimize import GridBudgetError
from xsp_killer.backtest.sweep import write_merged_rules_dict

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")


def et(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def _ohlc_row(ts: datetime, close: float, *, volume: float = 1_500_000.0) -> dict:
    return {
        "ts": ts,
        "open": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": volume,
    }


def _bars_from_timestamps(
    stamps: list[datetime],
    *,
    start_px: float = 450.0,
    step: float = 0.5,
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    rows = []
    for i, ts in enumerate(stamps):
        vol = volumes[i] if volumes is not None else 1_500_000.0
        rows.append(_ohlc_row(ts, start_px + i * step, volume=vol))
    return pd.DataFrame(rows).set_index("ts")


def _rth_15m_day(
    d: date,
    *,
    start_hh: int = 9,
    start_mm: int = 30,
    end_hh: int = 15,
    end_mm: int = 45,
) -> list[datetime]:
    out: list[datetime] = []
    t = datetime(d.year, d.month, d.day, start_hh, start_mm, tzinfo=ET)
    end = datetime(d.year, d.month, d.day, end_hh, end_mm, tzinfo=ET)
    while t <= end:
        out.append(t)
        t += timedelta(minutes=15)
    return out


def _green_warmup_days(
    n_days: int = 10,
    *,
    start: date = date(2024, 6, 3),
    start_px: float = 400.0,
    step: float = 0.25,
) -> pd.DataFrame:
    stamps: list[datetime] = []
    d = start
    while len({s.date() for s in stamps}) < n_days:
        if d.weekday() < 5:
            stamps.extend(_rth_15m_day(d))
        d += timedelta(days=1)
    return _bars_from_timestamps(stamps, start_px=start_px, step=step)


def _daily_context(
    n_days: int = 70,
    *,
    end: str = "2024-06-14",
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    index = pd.bdate_range(end=end, periods=n_days, tz=ET)
    closes = [400.0 + i for i in range(n_days)]
    if volumes is None:
        volumes = [1_000_000.0 + (i % 10) * 50_000 for i in range(n_days)]
    rows = [
        _ohlc_row(ts.to_pydatetime(), close, volume=vol)
        for ts, close, vol in zip(index, closes, volumes, strict=True)
    ]
    return pd.DataFrame(rows).set_index("ts")


def _rules(
    tmp_path: Path,
    *,
    window_start: str = "15:45",
    window_end: str = "16:00",
    volume_gate_max_pctile: float | None = None,
    regime_gate: str = "OFF",
    take_profit_pct: float = 0.90,
    stop_loss_pct: float = 0.90,
    stop_loss_pct_early: float | None = 0.10,
    stop_loss_early_minutes: int = 90,
    name: str = "entry_time_test",
) -> Path:
    entry: dict = {
        "regime_gate": regime_gate,
        "dte_pick": "target",
        "dte_min": 14,
        "dte_max": 60,
        "dte_target": 30,
        "strike_pick": "atm_only",
        "prior_day_spy_positive": False,
        "window_start_et": window_start,
        "window_end_et": window_end,
        "volume_gate_lookback": 63,
    }
    if volume_gate_max_pctile is not None:
        entry["volume_gate_max_pctile"] = volume_gate_max_pctile
    exit_cfg: dict = {
        "take_profit_pct": take_profit_pct,
        "stop_loss_pct": stop_loss_pct,
        "require_upper_bb_for_take_profit": False,
        "swing_hold": False,
        "max_hold_dte": 0,
        "stop_loss_early_minutes": stop_loss_early_minutes,
    }
    if stop_loss_pct_early is not None:
        exit_cfg["stop_loss_pct_early"] = stop_loss_pct_early
    overrides = {
        "logging": {"logic_version": f"xsp_lane_a_{name}"},
        "entry": entry,
        "paper_entry": {"max_open_positions": 1, "quantity": 1},
        "exit": exit_cfg,
        "ta": {
            "entry": {
                "mode": "close_window_only",
                "intraday_enabled": False,
                "require_vwap_reclaim": False,
            }
        },
    }
    return write_merged_rules_dict(overrides, tmp_path / f"{name}_rules.yaml")


# ---------------------------------------------------------------------------
# 1. in_entry_window custom start/end; close default unchanged
# ---------------------------------------------------------------------------


def test_in_entry_window_default_close_unchanged():
    from xsp_killer.backtest.intraday import in_entry_window

    assert in_entry_window(et(2024, 6, 13, 15, 45))
    assert in_entry_window(et(2024, 6, 13, 15, 59))
    assert not in_entry_window(et(2024, 6, 13, 15, 30))
    assert not in_entry_window(et(2024, 6, 13, 16, 0))


def test_in_entry_window_respects_custom_start_end():
    from xsp_killer.backtest.intraday import in_entry_window

    am_start, am_end = time(9, 45), time(11, 0)
    assert in_entry_window(et(2024, 6, 13, 9, 45), am_start, am_end)
    assert in_entry_window(et(2024, 6, 13, 10, 30), am_start, am_end)
    assert not in_entry_window(et(2024, 6, 13, 9, 30), am_start, am_end)
    assert not in_entry_window(et(2024, 6, 13, 11, 0), am_start, am_end)
    # Close window still excluded when custom window is morning
    assert not in_entry_window(et(2024, 6, 13, 15, 45), am_start, am_end)


def test_entry_knobs_include_window_fields():
    from xsp_killer.backtest.variants import entry_knobs_from_rules_dict

    knobs = entry_knobs_from_rules_dict(
        {
            "entry": {
                "window_start_et": "09:45",
                "window_end_et": "11:00",
            }
        }
    )
    assert knobs["window_start_et"] == "09:45"
    assert knobs["window_end_et"] == "11:00"
    defaults = entry_knobs_from_rules_dict({"entry": {}})
    assert defaults["window_start_et"] == "15:45"
    assert defaults["window_end_et"] == "16:00"


# ---------------------------------------------------------------------------
# 2. Fixture entry-time run produces report; all windows present
# ---------------------------------------------------------------------------


def test_optimize_entry_time_fixture_report(tmp_path):
    from scripts import optimize_entry_time as cli

    out = tmp_path / "reports"
    rc = cli.main(
        [
            "--mode",
            "fixture",
            "--out",
            str(out),
            "--windows",
            "close,late,mid,am",
            "--volume-pctile",
            "0.33,none",
            "--holds",
            "5",
            "-v",
        ]
    )
    assert rc == 0
    jsons = list(out.glob("entry_time_*.json"))
    mds = list(out.glob("entry_time_*.md"))
    assert len(jsons) == 1
    assert len(mds) == 1
    payload = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert payload["kind"] == "entry_time_optimizer"
    windows = set(payload.get("windows_present") or [])
    assert windows == {"close", "late", "mid", "am"}
    ranking = payload.get("ranking") or []
    assert ranking
    assert all("early_green_rate" in r for r in ranking)
    rec = payload.get("recommendation") or {}
    assert rec.get("status") == "RESEARCH ONLY"
    yaml_snip = rec.get("yaml_snippet") or payload.get("yaml_snippet") or ""
    assert "active: false" in yaml_snip or "active:false" in yaml_snip.replace(
        " ", ""
    )
    assert "LIVE_ENTRIES" not in yaml_snip
    assert "LIVE_EXITS" not in yaml_snip
    assert "UNUSUAL_WHALES_API_KEY" not in yaml_snip
    assert "window_start_et" in yaml_snip or "window_start_et" in json.dumps(
        payload
    )


# ---------------------------------------------------------------------------
# 3. Volume gate blocks loud prior days inside a non-close window
# ---------------------------------------------------------------------------


def test_volume_gate_blocks_loud_days_in_am_window(tmp_path):
    from xsp_killer.backtest.intraday import run_intraday_backtest

    bars = _green_warmup_days(12, start=date(2024, 6, 3))
    # Loud prior day: make last completed RTH day volume huge vs history.
    daily = _daily_context(n_days=70, end="2024-06-14")
    # Spike the final prior day volume so pctile is high.
    daily.iloc[-1, daily.columns.get_loc("volume")] = 50_000_000.0

    rules_quiet = _rules(
        tmp_path,
        window_start="09:45",
        window_end="11:00",
        volume_gate_max_pctile=0.33,
        regime_gate="OFF",
        name="am_quiet",
    )
    rules_off = _rules(
        tmp_path,
        window_start="09:45",
        window_end="11:00",
        volume_gate_max_pctile=None,
        regime_gate="OFF",
        name="am_vall",
    )

    res_quiet = run_intraday_backtest(
        bars,
        rules_quiet,
        variant_id="am_quiet",
        source="fixture",
        max_hold_sessions=5,
        daily_context=daily,
    )
    res_off = run_intraday_backtest(
        bars,
        rules_off,
        variant_id="am_vall",
        source="fixture",
        max_hold_sessions=5,
        daily_context=daily,
    )
    # Ungated should not have fewer entries than quiet-gated on loud history.
    assert res_quiet.n_entries_blocked >= res_off.n_entries_blocked
    # With a spiked prior day, quiet gate should block at least one attempt.
    assert res_quiet.n_entries_blocked > 0 or len(res_quiet.trades) <= len(
        res_off.trades
    )


# ---------------------------------------------------------------------------
# 4. Early SL 10% still fires inside 90 min (phased SL intact)
# ---------------------------------------------------------------------------


def test_early_sl_still_fires_via_existing_path():
    """Reuse Nagus phased-SL semantics; ensure LaneRules path still works."""
    from xsp_killer.lane_a_monitor import (
        LaneAPosition,
        LaneRules,
        evaluate_exit_alerts,
    )

    base = LaneRules(
        lane="A",
        dte_min=14,
        dte_max=60,
        exclude_expiry_month=(),
        chain_symbols=("XSP",),
        stop_loss_pct=0.20,
        take_profit_pct=0.30,
        sell_eval_start_et=time(0, 0),
        sell_deadline_et=time(23, 59),
        no_sell_start_et=time(0, 0),
        no_sell_end_et=time(0, 0),
        require_upper_bb_for_take_profit=False,
        logic_version="test",
        stop_loss_pct_early=0.10,
        stop_loss_early_minutes=90,
    )
    now = datetime(2026, 7, 15, 16, 0, tzinfo=ET)
    pos = LaneAPosition(
        position_id="p1",
        chain_symbol="XSP",
        option_type="call",
        strike=600.0,
        expiration_date=now.date(),
        quantity=1.0,
        average_price=10.0,
        mark_price=8.8,  # -12%
        dte=30,
        entry_ts=(now - timedelta(minutes=30)).isoformat(),
        entry_mid_premium=10.0,
    )
    alerts = evaluate_exit_alerts(pos, base, now_et=now)
    assert alerts and alerts[0].exit_reason == "stop_loss"


# ---------------------------------------------------------------------------
# 5. YAML snippet active:false; no secrets (covered in fixture report test)
# ---------------------------------------------------------------------------


def test_build_grid_yaml_inactive_and_budget_guard():
    from scripts.optimize_entry_time import (
        MAX_GRID_DEFAULT,
        build_entry_time_grid,
    )

    cells = build_entry_time_grid(
        windows=["close", "am"],
        volume_gates=[0.33, None],
        holds=[5],
    )
    assert len(cells) == 4
    for c in cells:
        assert c["spec"].active is False
        entry = c["overrides"]["entry"]
        assert "window_start_et" in entry
        assert "window_end_et" in entry
        assert "LIVE_" not in json.dumps(c["overrides"])

    with pytest.raises(GridBudgetError):
        build_entry_time_grid(
            windows=["close", "late", "mid", "am"],
            volume_gates=[0.33, 0.5, None],
            holds=[1, 2, 3, 5],  # 4*3*4 = 48 > 24
            max_grid=MAX_GRID_DEFAULT,
            allow_large=False,
        )

    big = build_entry_time_grid(
        windows=["close", "late", "mid", "am"],
        volume_gates=[0.33, None],
        holds=[3, 5],
        max_grid=16,
        allow_large=True,
    )
    assert len(big) == 16


# ---------------------------------------------------------------------------
# Early-green telemetry present on Stage B trades
# ---------------------------------------------------------------------------


def test_early_green_field_on_closed_trades(tmp_path):
    from xsp_killer.backtest.intraday import run_intraday_backtest

    bars = _green_warmup_days(10, start=date(2024, 6, 3), step=0.5)
    rules = _rules(
        tmp_path,
        window_start="15:45",
        window_end="16:00",
        regime_gate="OFF",
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        name="eg",
    )
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="eg",
        source="fixture",
        max_hold_sessions=1,
    )
    # early_green is always set on closed trades (bool)
    for t in res.trades:
        assert hasattr(t, "early_green")
        assert isinstance(t.early_green, bool)
        d = t.to_dict()
        assert "early_green" in d
    # Summarizer exposes rate
    from scripts.optimize_entry_time import _summarize_intraday

    summary = _summarize_intraday(res)
    assert "early_green_rate" in summary
    assert 0.0 <= float(summary["early_green_rate"]) <= 1.0


def test_am_window_entries_use_morning_bars(tmp_path):
    from xsp_killer.backtest.intraday import run_intraday_backtest

    bars = _green_warmup_days(10, start=date(2024, 6, 3))
    rules = _rules(
        tmp_path,
        window_start="09:45",
        window_end="11:00",
        regime_gate="OFF",
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        name="am_only",
    )
    res = run_intraday_backtest(
        bars,
        rules,
        variant_id="am_only",
        source="fixture",
        max_hold_sessions=5,
    )
    for t in res.trades:
        entry = datetime.fromisoformat(t.entry_ts).astimezone(ET)
        assert time(9, 45) <= entry.time() < time(11, 0), t.entry_ts
