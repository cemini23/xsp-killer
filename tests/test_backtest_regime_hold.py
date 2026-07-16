"""Stage A regime/hold optimizer tests (fixture-only, offline)."""

from __future__ import annotations

import pytest

from xsp_killer.backtest.bars import load_fixture_daily
from xsp_killer.backtest.regime_hold import (
    GridBudgetError,
    StageASpec,
    build_stage_a_grid,
    refine_stage_a,
    run_stage_a,
)


def test_stage_a_coarse_grid_is_bounded_and_unique():
    specs = build_stage_a_grid()
    ids = [s.variant_id for s in specs]
    assert 1 <= len(specs) <= 240
    assert len(ids) == len(set(ids))
    assert {
        int(s.description.split("hold=")[1].split()[0]) for s in specs
    } == {1, 2, 3, 5, 10}
    assert all(s.overrides["entry"]["strike_pick"] == "atm_only" for s in specs)
    # StageASpec wraps hold outside live YAML overrides
    assert all(isinstance(s, StageASpec) for s in specs)
    assert all(s.max_hold_sessions in (1, 2, 3, 5, 10) for s in specs)
    assert all(
        "max_hold_sessions" not in (s.overrides.get("exit") or {})
        and "max_hold_sessions" not in (s.overrides.get("entry") or {})
        for s in specs
    )
    # Explicit unique regime cells: GREEN once; GYB fracs x bounce
    assert len(specs) == 90  # 9 regimes × 2 prior × 5 holds
    dtes = {s.overrides["entry"]["dte_target"] for s in specs}
    tps = {s.overrides["exit"]["take_profit_pct"] for s in specs}
    sls = {s.overrides["exit"]["stop_loss_pct"] for s in specs}
    assert dtes == {28}
    assert tps == {0.20}
    assert sls == {0.30}


def test_stage_a_grid_budget_fails_before_execution():
    with pytest.raises(GridBudgetError):
        build_stage_a_grid(max_grid=10)


def test_stage_a_ranks_holdout_and_labels_fidelity():
    payload = run_stage_a(
        load_fixture_daily(),
        min_trades=1,
        coarse_to_fine=False,
        source="fixture",
    )
    assert payload["fidelity"] == "daily_close_proxy"
    assert "exits checked once per daily bar" in payload["disclaimer"]
    means = [r["holdout_mean_net_pnl_pct"] for r in payload["ranking"]]
    assert means == sorted(means, reverse=True)
    assert len(payload["ranking"]) == 90
    # max_hold_sessions used (not unknown YAML key)
    assert any(
        r.get("max_hold_sessions") in (1, 2, 3, 5, 10) for r in payload["ranking"]
    )


def test_refine_stage_a_preserves_regime_hold_and_budget():
    seed_rows = [
        {
            "variant_id": "rha_dte28_tp20_sl30_green_p0_h3",
            "regime_gate": "GREEN",
            "regime_yellow_frac_min": None,
            "regime_yellow_require_bounce": None,
            "prior_day_spy_positive": False,
            "max_hold_sessions": 3,
            "dte_target": 28,
            "take_profit_pct": 0.20,
            "stop_loss_pct": 0.30,
        },
        {
            "variant_id": "rha_dte28_tp20_sl30_gyb50b0_p1_h5",
            "regime_gate": "GREEN_OR_YELLOW_BOUNCE",
            "regime_yellow_frac_min": 0.50,
            "regime_yellow_require_bounce": False,
            "prior_day_spy_positive": True,
            "max_hold_sessions": 5,
            "dte_target": 28,
            "take_profit_pct": 0.20,
            "stop_loss_pct": 0.30,
        },
    ]
    existing = {r["variant_id"] for r in seed_rows}
    refined = refine_stage_a(
        seed_rows, existing_ids=set(existing), budget_remaining=40
    )
    assert refined
    assert len(refined) <= 40
    ids = [s.variant_id for s in refined]
    assert len(ids) == len(set(ids))
    assert not (set(ids) & existing)

    dtes = {s.overrides["entry"]["dte_target"] for s in refined}
    tps = {s.overrides["exit"]["take_profit_pct"] for s in refined}
    sls = {s.overrides["exit"]["stop_loss_pct"] for s in refined}
    assert dtes <= {21, 28, 35}
    assert tps <= {0.10, 0.15, 0.20, 0.25}
    assert sls <= {0.20, 0.30, 0.40}

    # Preserve each survivor's regime/prior/hold; only vary DTE/TP/SL
    for s in refined:
        assert isinstance(s, StageASpec)
        entry = s.overrides["entry"]
        if s.max_hold_sessions == 3:
            assert entry["regime_gate"] == "GREEN"
            assert entry["prior_day_spy_positive"] is False
        elif s.max_hold_sessions == 5:
            assert entry["regime_gate"] == "GREEN_OR_YELLOW_BOUNCE"
            assert entry["regime_yellow_frac_min"] == 0.50
            assert entry["regime_yellow_require_bounce"] is False
            assert entry["prior_day_spy_positive"] is True
        else:
            raise AssertionError(f"unexpected hold {s.max_hold_sessions}")

    # Budget hard stop
    tiny = refine_stage_a(seed_rows, existing_ids=set(existing), budget_remaining=2)
    assert len(tiny) <= 2

    # Over-budget combined reject when allow_large is false via max on refine size
    with pytest.raises(GridBudgetError):
        refine_stage_a(
            seed_rows,
            existing_ids=set(),
            budget_remaining=500,
            max_grid=10,
            allow_large=False,
        )
