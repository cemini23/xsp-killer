"""Volume quiet-day gate + time-phased early SL (Nagus guidance)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from xsp_killer.backtest.regime_hold import (
    COARSE_DTE,
    COARSE_SL,
    COARSE_SL_EARLY,
    COARSE_TP,
    VOLUME_GATES,
    build_stage_a_grid,
)
from xsp_killer.backtest.volume_gate import (
    prior_day_volume_percentile,
    volume_gate_allows,
)
from xsp_killer.lane_a_monitor import (
    LaneAPosition,
    LaneRules,
    evaluate_exit_alerts,
    regime_gate_allows,
)

ET = ZoneInfo("America/New_York")


def test_volume_percentile_ranks_prior_day():
    vols = pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], dtype=float)
    # bar_i=9 → prior=90; window=[10..90] (9 pts) → 8/9 <= 90
    pct = prior_day_volume_percentile(vols, 9, lookback=9)
    assert pct is not None
    assert 0.8 <= pct <= 1.0


def test_volume_gate_blocks_loud_days():
    ok, _ = volume_gate_allows(prior_vol_pctile=0.20, max_pctile=0.33)
    assert ok is True
    ok, reason = volume_gate_allows(prior_vol_pctile=0.80, max_pctile=0.33)
    assert ok is False
    assert reason and "not quiet" in reason
    ok, _ = volume_gate_allows(prior_vol_pctile=0.99, max_pctile=None)
    assert ok is True


def test_regime_gate_off_always_allows():
    ok, reason = regime_gate_allows(
        regime_gate="OFF",
        regime="RED",
        regime_ok=False,
        yellow_frac=None,
        ta_entry_ok=False,
    )
    assert ok is True
    assert reason is None


def test_early_stop_tighter_than_late():
    base = LaneRules(
        lane="A",
        dte_min=14,
        dte_max=60,
        exclude_expiry_month=(),
        chain_symbols=("XSP",),
        stop_loss_pct=0.20,
        take_profit_pct=0.30,
        sell_eval_start_et=__import__("datetime").time(0, 0),
        sell_deadline_et=__import__("datetime").time(23, 59),
        no_sell_start_et=__import__("datetime").time(0, 0),
        no_sell_end_et=__import__("datetime").time(0, 0),
        require_upper_bb_for_take_profit=False,
        logic_version="test",
        stop_loss_pct_early=0.10,
        stop_loss_early_minutes=90,
    )
    entry = datetime(2026, 7, 15, 15, 45, tzinfo=ET)
    pos = LaneAPosition(
        position_id="p1",
        chain_symbol="XSP",
        option_type="call",
        strike=600.0,
        expiration_date=entry.date(),
        quantity=1.0,
        average_price=10.0,
        mark_price=8.8,  # -12%
        dte=30,
        entry_ts=entry.isoformat(),
        entry_mid_premium=10.0,
    )
    # 30 min after entry → early 10% SL should fire on -12%
    early_now = entry + timedelta(minutes=30)
    # Force session open by monkeypatching would be heavy; call with a weekday
    # RTH timestamp and rely on xsp_session_open — Jul 15 2026 is Wednesday.
    # 16:15 is curb/RTH edge; use 16:00 next day... actually same evening 16:00.
    now = datetime(2026, 7, 15, 16, 0, tzinfo=ET)
    # Rebuild with entry 30 min before now
    pos.entry_ts = (now - timedelta(minutes=30)).isoformat()
    alerts = evaluate_exit_alerts(pos, base, now_et=now)
    assert alerts and alerts[0].exit_reason == "stop_loss"
    assert "10%" in alerts[0].message or "limit -10" in alerts[0].message

    # After early window: -12% should NOT trip 20% late SL
    pos.entry_ts = (now - timedelta(minutes=180)).isoformat()
    pos.mark_price = 8.8
    alerts_late = evaluate_exit_alerts(pos, base, now_et=now)
    assert not any(a.exit_reason == "stop_loss" for a in alerts_late)


def test_creator_volume_grid_shape():
    specs = build_stage_a_grid()
    # 2 regimes × 3 volume × 1 prior × 5 holds = 30
    assert len(specs) == 30
    assert {s.overrides["entry"]["dte_target"] for s in specs} == {COARSE_DTE}
    assert {s.overrides["exit"]["take_profit_pct"] for s in specs} == {COARSE_TP}
    assert {s.overrides["exit"]["stop_loss_pct"] for s in specs} == {COARSE_SL}
    assert {s.overrides["exit"]["stop_loss_pct_early"] for s in specs} == {
        COARSE_SL_EARLY
    }
    gates = {s.overrides["entry"]["regime_gate"] for s in specs}
    assert gates == {"OFF", "GREEN"}
    vol_labels = {vid.split("_")[4] for vid in (s.variant_id for s in specs)}
    # variant: rha_dte30_tp30_sl20_{regime}_{vol}_p0_hN
    assert "vq33" in {s.variant_id for s in specs} or any(
        "vq33" in s.variant_id for s in specs
    )
    assert len(VOLUME_GATES) == 3
