"""Stage A regime/hold optimizer tests (fixture-only, offline)."""

from __future__ import annotations

import pytest

from xsp_killer.backtest.bars import load_fixture_daily
from xsp_killer.backtest.regime_hold import (
    GridBudgetError,
    StageASpec,
    build_stage_a_grid,
    edge_confirmed,
    recommended_regime_hold_yaml,
    refine_stage_a,
    run_sensitivity,
    run_stage_a,
    stable_windows,
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


def _candidate_cell() -> StageASpec:
    return build_stage_a_grid()[0]


def test_sensitivity_is_deterministic_and_complete():
    candidate = _candidate_cell()
    bars = load_fixture_daily()
    result = run_sensitivity(candidate, bars, source="fixture")
    assert result == run_sensitivity(candidate, bars, source="fixture")
    assert len(result["cells"]) == 12
    assert result["iv_seeds"] == [0.14, 0.18, 0.22, 0.28]
    assert result["slippage_mults"] == [1.0, 1.5, 2.0]
    for cell in result["cells"]:
        assert "iv_seed" in cell
        assert "slippage_mult" in cell
        assert "n_trades" in cell
        assert "mean_net_pnl_pct" in cell
        assert "median_net_pnl_pct" in cell
        assert "positive" in cell


def test_stable_windows_require_adjacent_parameter_settings():
    # Isolated positive is not stable
    isolated = [
        {
            "variant_id": "a",
            "holdout_mean_net_pnl_pct": 0.05,
            "max_hold_sessions": 1,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": None,
            "dte_target": 28,
            "take_profit_pct": 0.20,
            "stop_loss_pct": 0.30,
        },
        {
            "variant_id": "b",
            "holdout_mean_net_pnl_pct": -0.01,
            "max_hold_sessions": 10,
            "regime_gate": "GREEN_OR_YELLOW_BOUNCE",
            "prior_day_spy_positive": True,
            "regime_yellow_frac_min": 0.75,
            "dte_target": 21,
            "take_profit_pct": 0.10,
            "stop_loss_pct": 0.40,
        },
    ]
    assert stable_windows(isolated) == []

    # Two adjacent positive holds (same regime/prior/dte/tp/sl) are stable
    adjacent_holds = [
        {
            "variant_id": "h1",
            "holdout_mean_net_pnl_pct": 0.04,
            "max_hold_sessions": 1,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": None,
            "dte_target": 28,
            "take_profit_pct": 0.20,
            "stop_loss_pct": 0.30,
        },
        {
            "variant_id": "h2",
            "holdout_mean_net_pnl_pct": 0.03,
            "max_hold_sessions": 2,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": None,
            "dte_target": 28,
            "take_profit_pct": 0.20,
            "stop_loss_pct": 0.30,
        },
        {
            "variant_id": "h_neg",
            "holdout_mean_net_pnl_pct": -0.02,
            "max_hold_sessions": 3,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": None,
            "dte_target": 28,
            "take_profit_pct": 0.20,
            "stop_loss_pct": 0.30,
        },
    ]
    wins = stable_windows(adjacent_holds)
    assert wins
    member_ids = {m for w in wins for m in w.get("member_ids", [])}
    assert "h1" in member_ids and "h2" in member_ids
    assert "h_neg" not in member_ids

    # Ranking-adjacent but parameter-distant positives are NOT stable
    ranking_adjacent_only = [
        {
            "variant_id": "x",
            "holdout_mean_net_pnl_pct": 0.10,
            "max_hold_sessions": 1,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": None,
            "dte_target": 28,
            "take_profit_pct": 0.20,
            "stop_loss_pct": 0.30,
        },
        {
            "variant_id": "y",
            "holdout_mean_net_pnl_pct": 0.09,
            "max_hold_sessions": 10,
            "regime_gate": "GREEN_OR_YELLOW_BOUNCE",
            "prior_day_spy_positive": True,
            "regime_yellow_frac_min": 0.40,
            "dte_target": 35,
            "take_profit_pct": 0.10,
            "stop_loss_pct": 0.40,
        },
    ]
    assert stable_windows(ranking_adjacent_only) == []


def test_edge_confirmed_requires_all_gates():
    good_row = {
        "variant_id": "good",
        "holdout_mean_net_pnl_pct": 0.05,
        "n_holdout": 12,
        "mcpt_pass_5pct": True,
        "stable_window": True,
    }
    sens_ok = {
        "iv_positive_count": 3,
        "iv_seeds": [0.14, 0.18, 0.22, 0.28],
        "slippage_1_5x_positive": True,
        "cells": [],
    }
    intraday_ok = {"mean_net_pnl_pct": 0.01}

    ok, reason = edge_confirmed(good_row, sens_ok, intraday_ok, min_trades=8)
    assert ok is True
    assert "confirmed" in reason.lower() or reason == "edge_confirmed"

    # Fail: negative holdout
    bad = dict(good_row, holdout_mean_net_pnl_pct=-0.01)
    ok, _ = edge_confirmed(bad, sens_ok, intraday_ok, min_trades=8)
    assert ok is False

    # Fail: insufficient sample
    bad = dict(good_row, n_holdout=3)
    ok, _ = edge_confirmed(bad, sens_ok, intraday_ok, min_trades=8)
    assert ok is False

    # Fail: MCPT
    bad = dict(good_row, mcpt_pass_5pct=False)
    ok, _ = edge_confirmed(bad, sens_ok, intraday_ok, min_trades=8)
    assert ok is False

    # Fail: stable window
    bad = dict(good_row, stable_window=False)
    ok, _ = edge_confirmed(bad, sens_ok, intraday_ok, min_trades=8)
    assert ok is False

    # Fail: negative intraday
    ok, _ = edge_confirmed(
        good_row, sens_ok, {"mean_net_pnl_pct": -0.02}, min_trades=8
    )
    assert ok is False

    # Fail: fewer than 3 IV seeds positive
    sens_bad_iv = dict(sens_ok, iv_positive_count=2)
    ok, _ = edge_confirmed(good_row, sens_bad_iv, intraday_ok, min_trades=8)
    assert ok is False

    # Fail: 1.5x slippage not positive
    sens_bad_slip = dict(sens_ok, slippage_1_5x_positive=False)
    ok, _ = edge_confirmed(good_row, sens_bad_slip, intraday_ok, min_trades=8)
    assert ok is False


def test_recommended_yaml_always_inactive_no_live_text():
    row = {
        "variant_id": "rha_dte28_tp20_sl30_green_p0_h3",
        "n_holdout": 20,
        "holdout_mean_net_pnl_pct": 0.05,
        "mcpt_pass_5pct": True,
        "stable_window": True,
        "max_hold_sessions": 3,
    }
    ov = {
        "entry": {
            "dte_target": 28,
            "strike_pick": "atm_only",
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
        },
        "exit": {"take_profit_pct": 0.20, "stop_loss_pct": 0.30},
    }
    text = recommended_regime_hold_yaml(row, ov, edge_ok=True, min_trades=8)
    assert "active: false" in text.lower()
    assert "LIVE_" not in text
    assert "live_entries" not in text.lower()
    assert "live_exits" not in text.lower()
    # Even when edge fails, still inactive
    text2 = recommended_regime_hold_yaml(row, ov, edge_ok=False, min_trades=8)
    assert "active: false" in text2.lower()
    assert "LIVE_" not in text2
    # Hold is documented in description, not as unknown live key in overrides dump
    assert "max_hold_sessions" not in (ov.get("exit") or {})
