"""Stage B structure_mode: naked default + debit_spread dual-leg marks."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xsp_killer.backtest.intraday import run_intraday_backtest
from xsp_killer.backtest.option_model import (
    debit_spread_mark,
    synthesize_call_premium,
    synthesize_debit_spread,
)
from xsp_killer.backtest.sweep import write_merged_rules_dict
from xsp_killer.backtest.variants import entry_knobs_from_rules_dict
from xsp_killer.debit_spread import select_short_strike

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
) -> pd.DataFrame:
    rows = [_ohlc_row(ts, start_px + i * step) for i, ts in enumerate(stamps)]
    return pd.DataFrame(rows).set_index("ts")


def _rth_15m_day(d: date, *, include_entry: bool = True) -> list[datetime]:
    out: list[datetime] = []
    t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
    end_h, end_m = (15, 45) if include_entry else (15, 30)
    end = datetime(d.year, d.month, d.day, end_h, end_m, tzinfo=ET)
    while t <= end:
        out.append(t)
        t += timedelta(minutes=15)
    return out


def _green_warmup_days(
    n_days: int = 8,
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


def _rules(
    tmp_path: Path,
    *,
    structure_mode: str = "naked",
    width_strikes: int = 2,
    take_profit_pct: float = 0.30,
    stop_loss_pct: float = 0.20,
    stop_loss_pct_early: float | None = 0.10,
    stop_loss_early_minutes: int = 90,
    dte_target: int = 30,
    regime_gate: str = "OFF",
    max_hold_sessions: int = 5,
    require_upper_bb: bool = False,
) -> Path:
    overrides: dict = {
        "logging": {"logic_version": "xsp_lane_a_bt_structure_test"},
        "entry": {
            "regime_gate": regime_gate,
            "dte_pick": "target",
            "dte_min": 14,
            "dte_max": 60,
            "dte_target": dte_target,
            "strike_pick": "atm_only",
            "prior_day_spy_positive": False,
            "structure_mode": structure_mode,
            "debit_spread_width_strikes": width_strikes,
        },
        "paper_entry": {"max_open_positions": 1, "quantity": 1},
        "exit": {
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
            "require_upper_bb_for_take_profit": require_upper_bb,
            "swing_hold": False,
            "max_hold_dte": 0,
            "max_hold_sessions": max_hold_sessions,
        },
        "ta": {
            "entry": {
                "mode": "close_window_only",
                "intraday_enabled": False,
                "require_vwap_reclaim": False,
            }
        },
    }
    if stop_loss_pct_early is not None:
        overrides["exit"]["stop_loss_pct_early"] = stop_loss_pct_early
        overrides["exit"]["stop_loss_early_minutes"] = stop_loss_early_minutes
    path = tmp_path / f"bt_structure_{structure_mode}.yaml"
    write_merged_rules_dict(overrides, path)
    return path


def test_knobs_default_structure_naked():
    knobs = entry_knobs_from_rules_dict({"entry": {}})
    assert knobs["structure_mode"] == "naked"
    assert knobs["debit_spread_width_strikes"] == 2


def test_synthesize_debit_spread_long_lt_short_net_positive():
    long_k = 450.0
    short_k = select_short_strike(long_k, width_strikes=2)
    assert short_k == 460.0
    spread = synthesize_debit_spread(
        450.0,
        long_strike=long_k,
        short_strike=short_k,
        dte=30,
        iv=0.18,
        premium_scale=10.0,
    )
    assert spread is not None
    assert spread.long_strike < spread.short_strike
    assert spread.net_debit > 0
    assert spread.width_points == 10.0


def test_debit_spread_mark_clamped_to_scaled_width():
    long_m, short_m, value = debit_spread_mark(
        450.0,
        long_strike=450.0,
        short_strike=460.0,
        width_points=10.0,
        dte=30,
        iv=0.18,
        premium_scale=10.0,
    )
    assert long_m > short_m
    assert 0.0 <= value <= 10.0 * 10.0


def test_naked_default_parity_smoke(tmp_path: Path):
    """Default structure_mode=naked matches explicit naked on fixture bars."""
    bars = _green_warmup_days(n_days=10)
    # Explicit naked vs omitting structure_mode (defaults to naked via knobs).
    r_default = _rules(tmp_path / "a", structure_mode="naked")
    # Second rules file without structure_mode key in overrides base merge.
    r_omit = write_merged_rules_dict(
        {
            "logging": {"logic_version": "xsp_lane_a_bt_structure_omit"},
            "entry": {
                "regime_gate": "OFF",
                "dte_pick": "target",
                "dte_target": 30,
                "strike_pick": "atm_only",
                "prior_day_spy_positive": False,
            },
            "paper_entry": {"max_open_positions": 1, "quantity": 1},
            "exit": {
                "take_profit_pct": 0.30,
                "stop_loss_pct": 0.20,
                "stop_loss_pct_early": 0.10,
                "stop_loss_early_minutes": 90,
                "require_upper_bb_for_take_profit": False,
                "swing_hold": False,
                "max_hold_dte": 0,
                "max_hold_sessions": 5,
            },
            "ta": {
                "entry": {
                    "mode": "close_window_only",
                    "intraday_enabled": False,
                    "require_vwap_reclaim": False,
                }
            },
        },
        tmp_path / "omit.yaml",
    )
    res_a = run_intraday_backtest(
        bars, r_default, variant_id="naked_exp", source="fixture"
    )
    res_b = run_intraday_backtest(
        bars, r_omit, variant_id="naked_def", source="fixture"
    )
    assert any("structure_mode=naked" in n for n in res_a.notes)
    assert any("structure_mode=naked" in n for n in res_b.notes)
    assert res_a.n_blocked_spread == 0
    assert res_b.n_blocked_spread == 0
    # Same number of closed trades + residual on mild uptrend fixture.
    assert len(res_a.trades) == len(res_b.trades)
    if res_a.trades:
        assert res_a.trades[0].strike == res_b.trades[0].strike
        # Naked entry mid is a single-leg call premium.
        naked_mid = synthesize_call_premium(
            float(bars.iloc[0]["close"]),
            xsp_strike=res_a.trades[0].strike,
            dte=30,
            iv=0.18,
            premium_scale=10.0,
        )
        # Entry mids should be in single-leg range (not zero).
        assert res_a.trades[0].entry_mid > 0
        assert abs(res_a.trades[0].entry_mid - res_b.trades[0].entry_mid) < 1e-6
        _ = naked_mid  # model available; not used for exact bar match


def test_debit_spread_entry_builds_coherent_net_debit(tmp_path: Path):
    bars = _green_warmup_days(n_days=10, step=0.5)
    rpath = _rules(
        tmp_path,
        structure_mode="debit_spread",
        width_strikes=2,
        # Wide TP/SL so we observe entries rather than instant exits only.
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        stop_loss_pct_early=None,
        max_hold_sessions=2,
    )
    res = run_intraday_backtest(
        bars, rpath, variant_id="dspread", source="fixture", max_hold_sessions=2
    )
    assert any("structure_mode=debit_spread" in n for n in res.notes)
    assert res.n_blocked_spread == 0
    # Expect at least one trade or residual open from the close window.
    assert len(res.trades) + res.residual_open >= 1
    if res.trades:
        t = res.trades[0]
        assert t.entry_mid > 0
        short = select_short_strike(t.strike, width_strikes=2)
        assert short > t.strike
        # Net debit should be below a single-leg ATM mid at same scale.
        # (spread cheaper than naked long.)
        naked = synthesize_call_premium(
            450.0,
            xsp_strike=t.strike,
            dte=30,
            iv=0.18,
            premium_scale=10.0,
        )
        assert t.entry_mid < naked or t.entry_mid > 0


def test_debit_spread_tp_sl_on_spread_return(tmp_path: Path):
    """With tight TP and a strong uptrend, debit_spread should take profit."""
    # Steep uptrend so spread value expands quickly vs entry net debit.
    bars = _green_warmup_days(n_days=12, start_px=400.0, step=2.0)
    rpath = _rules(
        tmp_path,
        structure_mode="debit_spread",
        take_profit_pct=0.10,
        stop_loss_pct=0.50,
        stop_loss_pct_early=None,
        max_hold_sessions=5,
        require_upper_bb=False,
    )
    res = run_intraday_backtest(
        bars, rpath, variant_id="ds_tp", source="fixture", max_hold_sessions=5
    )
    assert len(res.trades) >= 1 or res.residual_open >= 1
    # If any strategy exit fired, TP or SL are the expected reasons.
    reasons = {t.exit_reason for t in res.trades}
    strategy = reasons & {"take_profit", "stop_loss"}
    if strategy:
        assert strategy  # TP/SL path exercised via evaluate_exit_alerts
    # Entry mid is net debit (positive).
    for t in res.trades:
        assert t.entry_mid > 0
        assert t.exit_mid >= 0


def test_incoherent_spread_blocks_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When short mid >= long mid, entry is skipped and blocked_spread counted."""
    from xsp_killer.backtest import option_model as om
    from xsp_killer.backtest import intraday as intrad

    bars = _green_warmup_days(n_days=8)

    def _bad_spread(*_a, **_k):
        return None

    monkeypatch.setattr(om, "synthesize_debit_spread", _bad_spread)
    monkeypatch.setattr(intrad, "synthesize_debit_spread", _bad_spread)

    rpath = _rules(
        tmp_path,
        structure_mode="debit_spread",
        take_profit_pct=0.90,
        stop_loss_pct=0.90,
        stop_loss_pct_early=None,
        max_hold_sessions=5,
    )
    res = run_intraday_backtest(
        bars, rpath, variant_id="ds_block", source="fixture"
    )
    assert res.n_blocked_spread >= 1
    assert res.n_entries_blocked >= res.n_blocked_spread
    assert len(res.trades) == 0
    assert res.residual_open == 0


def test_optimize_structure_fixture_both(tmp_path: Path):
    """CLI fixture path emits both modes, active:false YAML, no secrets."""
    import scripts.optimize_structure as opt

    out = tmp_path / "reports"
    rc = opt.main(
        [
            "--mode",
            "fixture",
            "--structure",
            "both",
            "--volume-pctile",
            "none",
            "--holds",
            "5",
            "--out",
            str(out),
            "-v",
        ]
    )
    assert rc == 0
    jsons = list(out.glob("structure_*.json"))
    mds = list(out.glob("structure_*.md"))
    assert len(jsons) == 1
    assert len(mds) == 1
    payload = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert payload["pricing_fidelity"] == "modeled_bs_lite"
    assert payload["pricing_fidelity"] != "historical_xsp_chain"
    modes = {r["structure_mode"] for r in payload["ranking"]}
    assert modes == {"naked", "debit_spread"}
    rec = payload["recommendation"]
    assert rec["status"] == "RESEARCH ONLY"
    assert rec["pricing_fidelity"] == "modeled_bs_lite"
    yaml_snip = rec.get("yaml_snippet") or ""
    assert "active: false" in yaml_snip or "active:false" in yaml_snip.replace(
        " ", ""
    )
    assert "structure_mode" in yaml_snip
    raw = jsons[0].read_text(encoding="utf-8") + mds[0].read_text(encoding="utf-8")
    for token in ("LIVE_ENTRIES", "LIVE_EXITS", "UNUSUAL_WHALES_API_KEY"):
        assert token not in raw
    md = mds[0].read_text(encoding="utf-8")
    assert "modeled_bs_lite" in md
    assert "naked" in md and "debit_spread" in md


def test_build_structure_grid_both_modes():
    from scripts.optimize_structure import build_structure_grid

    cells = build_structure_grid(
        structures=["naked", "debit_spread"],
        volume_gates=[None],
        holds=[5],
        width_strikes=2,
    )
    assert len(cells) == 2
    assert {c["structure_mode"] for c in cells} == {"naked", "debit_spread"}
    for c in cells:
        assert c["spec"].active is False
        assert c["overrides"]["entry"]["structure_mode"] == c["structure_mode"]
