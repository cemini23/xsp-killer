"""Spread × window search: grid, Friday Stage B, fixture smoke."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xsp_killer.backtest.optimize import GridBudgetError
from xsp_killer.backtest.sweep import write_merged_rules_dict
from xsp_killer.backtest.intraday import run_intraday_backtest
from xsp_killer.lane_a_monitor import evaluate_exit_alerts, LaneAPosition, LaneRules

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


def _rth_15m_day(
    d: date,
    *,
    end_hh: int = 15,
    end_mm: int = 45,
) -> list[datetime]:
    out: list[datetime] = []
    t = datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
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


def _rules(
    tmp_path: Path,
    *,
    structure_mode: str = "debit_spread",
    width_strikes: int = 2,
    window_start: str = "15:45",
    window_end: str = "16:00",
    friday_flatten_enabled: bool = True,
    take_profit_pct: float = 0.90,
    stop_loss_pct: float = 0.90,
    max_hold_sessions: int = 5,
) -> Path:
    overrides: dict = {
        "logging": {"logic_version": "xsp_lane_a_bt_spread_search_test"},
        "entry": {
            "regime_gate": "OFF",
            "dte_pick": "target",
            "dte_min": 14,
            "dte_max": 60,
            "dte_target": 30,
            "strike_pick": "atm_only",
            "prior_day_spy_positive": False,
            "structure_mode": structure_mode,
            "debit_spread_width_strikes": width_strikes,
            "window_start_et": window_start,
            "window_end_et": window_end,
        },
        "paper_entry": {"max_open_positions": 1, "quantity": 1},
        "exit": {
            "take_profit_pct": take_profit_pct,
            "stop_loss_pct": stop_loss_pct,
            "require_upper_bb_for_take_profit": False,
            "swing_hold": False,
            "max_hold_dte": 0,
            "max_hold_sessions": max_hold_sessions,
            "friday_flatten_enabled": friday_flatten_enabled,
            "friday_flatten_et": "15:45",
        },
        "ta": {
            "entry": {
                "mode": "close_window_only",
                "intraday_enabled": False,
                "require_vwap_reclaim": False,
            }
        },
    }
    path = tmp_path / f"bt_ss_{structure_mode}_{window_start.replace(':', '')}.yaml"
    write_merged_rules_dict(overrides, path)
    return path


def test_default_grid_size_within_budget():
    from scripts.optimize_spread_search import (
        MAX_GRID_DEFAULT,
        build_spread_search_grid,
    )

    cells = build_spread_search_grid()
    # 3 widths × 2 windows × 2 vol + 1 naked control = 13
    assert len(cells) == 13
    assert len(cells) <= MAX_GRID_DEFAULT
    assert sum(1 for c in cells if c["is_naked_control"]) == 1
    assert all(
        c["structure_mode"] == "debit_spread" or c["is_naked_control"] for c in cells
    )
    widths = {c["debit_spread_width_strikes"] for c in cells if not c["is_naked_control"]}
    assert widths == {1, 2, 3}
    windows = {c["window_id"] for c in cells if not c["is_naked_control"]}
    assert windows == {"am", "close"}
    assert all(c["spec"].active is False for c in cells)


def test_grid_rejects_over_budget():
    from scripts.optimize_spread_search import build_spread_search_grid

    with pytest.raises(GridBudgetError):
        build_spread_search_grid(max_grid=4, allow_large=False)


def test_friday_no_entry_blocks_close_window(tmp_path: Path):
    """Friday close bars increment n_blocked_friday; no silent open."""
    # 2024-06-07 is Friday; include a few prior sessions for warmup.
    stamps: list[datetime] = []
    for d in (date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5), date(2024, 6, 6), date(2024, 6, 7)):
        stamps.extend(_rth_15m_day(d))
    bars = _bars_from_timestamps(stamps, start_px=400.0, step=0.1)
    rpath = _rules(tmp_path, window_start="15:45", window_end="16:00")
    res = run_intraday_backtest(
        bars, rpath, variant_id="fri_block", source="fixture", max_hold_sessions=5
    )
    assert res.n_blocked_friday >= 1
    friday_entries = [
        t
        for t in res.trades
        if datetime.fromisoformat(t.entry_ts).weekday() == 4
    ]
    assert friday_entries == []
    assert any("friday_no_entry" in n for n in res.notes)


def test_friday_flatten_exit_on_open_position(tmp_path: Path):
    """Thursday entry → Friday ≥15:45 exits via friday_flatten."""
    # Thu 2024-06-06 + Fri 2024-06-07
    stamps: list[datetime] = []
    for d in (
        date(2024, 6, 3),
        date(2024, 6, 4),
        date(2024, 6, 5),
        date(2024, 6, 6),
        date(2024, 6, 7),
    ):
        stamps.extend(_rth_15m_day(d))
    bars = _bars_from_timestamps(stamps, start_px=400.0, step=0.05)
    # AM window so Thursday can enter (not Friday-blocked); hold open into Fri.
    rpath = _rules(
        tmp_path,
        structure_mode="naked",
        window_start="09:45",
        window_end="11:00",
        take_profit_pct=0.99,
        stop_loss_pct=0.99,
        max_hold_sessions=10,
    )
    res = run_intraday_backtest(
        bars, rpath, variant_id="fri_flat", source="fixture", max_hold_sessions=10
    )
    flat = [t for t in res.trades if t.exit_reason == "friday_flatten"]
    assert flat, f"expected friday_flatten exits; got {[t.exit_reason for t in res.trades]}"
    assert any("friday_flatten_et" in n for n in res.notes)


def test_evaluate_exit_alerts_friday_still_shared():
    """Stage B and prod share evaluate_exit_alerts friday_flatten."""
    rules = LaneRules(
        lane="A",
        dte_min=14,
        dte_max=60,
        exclude_expiry_month=("01",),
        chain_symbols=("SPX", "XSP"),
        stop_loss_pct=0.99,
        take_profit_pct=0.99,
        sell_eval_start_et=time(8, 0),
        sell_deadline_et=time(9, 30),
        no_sell_start_et=time(0, 0),
        no_sell_end_et=time(8, 0),
        require_upper_bb_for_take_profit=False,
        logic_version="xsp_lane_a_bt_ss_test",
        friday_flatten_enabled=True,
        friday_flatten_et=time(15, 45),
    )
    pos = LaneAPosition(
        position_id="t",
        chain_symbol="XSP",
        option_type="call",
        strike=450.0,
        expiration_date=date(2024, 7, 19),
        quantity=1.0,
        average_price=10.0,
        mark_price=10.0,
        dte=30,
        lane="A",
        entry_ts=et(2024, 6, 6, 15, 45).isoformat(),
        entry_mid_premium=10.0,
    )
    fri = et(2024, 6, 7, 15, 45)
    alerts = evaluate_exit_alerts(pos, rules, now_et=fri)
    assert alerts and alerts[0].exit_reason == "friday_flatten"


def test_fixture_cli_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts import optimize_spread_search as oss

    out = tmp_path / "reports"
    # Tiny grid for speed: one width × one window × one vol + naked.
    monkeypatch.setattr(oss, "DEFAULT_WIDTHS", (2,))
    monkeypatch.setattr(oss, "DEFAULT_WINDOWS", ("close",))
    monkeypatch.setattr(oss, "DEFAULT_VOLUME_GATES", (None,))
    rc = oss.main(
        [
            "--mode",
            "fixture",
            "--widths",
            "2",
            "--windows",
            "close",
            "--volume-pctile",
            "none",
            "--out",
            str(out),
            "-v",
        ]
    )
    assert rc == 0
    jsons = list(out.glob("spread_search_*.json"))
    mds = list(out.glob("spread_search_*.md"))
    assert len(jsons) == 1 and len(mds) == 1
    payload = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert payload["pricing_fidelity"] == "modeled_bs_lite"
    assert payload["pricing_fidelity"] != "historical_xsp_chain"
    assert payload["recommendation"]["status"] == "RESEARCH ONLY"
    assert payload["recommendation"]["promotion_eligible"] is False
    yaml_snip = payload.get("yaml_snippet") or ""
    assert "active: false" in yaml_snip or "active:false" in yaml_snip.replace(" ", "")
    raw = jsons[0].read_text(encoding="utf-8")
    assert "LIVE_ENTRIES" not in raw
    assert "LIVE_EXITS" not in raw
    assert "UNUSUAL_WHALES_API_KEY" not in raw
    assert len(payload["ranking"]) == 2  # dspread + naked control
    md = mds[0].read_text(encoding="utf-8")
    assert "modeled_bs_lite" in md
    assert "RESEARCH ONLY" in md


def test_report_scrub_forbidden():
    from scripts.optimize_spread_search import _scrub_forbidden

    text = "keep LIVE_ENTRIES secret UNUSUAL_WHALES_API_KEY out"
    scrubbed = _scrub_forbidden(text)
    assert "LIVE_ENTRIES" not in scrubbed
    assert "UNUSUAL_WHALES_API_KEY" not in scrubbed
    assert "REDACTED" in scrubbed
