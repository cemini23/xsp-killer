"""Stage A regime/hold optimizer tests (fixture-only, offline)."""

from __future__ import annotations

import pytest

from xsp_killer.backtest.regime_hold import (
    GridBudgetError,
    StageASpec,
    build_stage_a_grid,
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
