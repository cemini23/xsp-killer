"""Stage A regime/hold optimizer tests (fixture-only, offline)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from xsp_killer.backtest.bars import load_fixture_daily
from xsp_killer.backtest.regime_hold import (
    GridBudgetError,
    StageASpec,
    _base_paper_economics,
    _rank_key,
    _select_stage_a_finalists,
    annotate_behavior_duplicates,
    build_stage_a_grid,
    edge_confirmed,
    promotion_eligible,
    recommended_regime_hold_yaml,
    refine_stage_a,
    run_sensitivity,
    run_stage_a,
    stable_windows,
)
from xsp_killer.lane_a_variants import load_base_rules


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
    assert len(specs) == 30  # 2 regimes × 3 volume × 1 prior × 5 holds
    dtes = {s.overrides["entry"]["dte_target"] for s in specs}
    tps = {s.overrides["exit"]["take_profit_pct"] for s in specs}
    sls = {s.overrides["exit"]["stop_loss_pct"] for s in specs}
    assert dtes == {30}
    assert tps == {0.30}
    assert sls == {0.20}


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
    ranking = payload["ranking"]
    # Sample-aware rank key is non-increasing
    keys = [_rank_key(r, min_trades=1) for r in ranking]
    assert keys == sorted(keys, reverse=True)
    assert all("low_sample" in r for r in ranking)
    assert len(ranking) == 30
    # max_hold_sessions used (not unknown YAML key)
    assert any(
        r.get("max_hold_sessions") in (1, 2, 3, 5, 10) for r in ranking
    )


def test_refine_stage_a_preserves_regime_hold_and_budget():
    seed_rows = [
        {
            "variant_id": "rha_dte30_tp30_sl20_off_vq33_p0_h3",
            "regime_gate": "OFF",
            "volume_gate_max_pctile": 0.33,
            "regime_yellow_frac_min": None,
            "regime_yellow_require_bounce": None,
            "prior_day_spy_positive": False,
            "max_hold_sessions": 3,
            "dte_target": 30,
            "take_profit_pct": 0.30,
            "stop_loss_pct": 0.20,
        },
        {
            "variant_id": "rha_dte30_tp30_sl20_green_vall_p0_h5",
            "regime_gate": "GREEN",
            "volume_gate_max_pctile": None,
            "regime_yellow_frac_min": None,
            "regime_yellow_require_bounce": None,
            "prior_day_spy_positive": False,
            "max_hold_sessions": 5,
            "dte_target": 30,
            "take_profit_pct": 0.30,
            "stop_loss_pct": 0.20,
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
    assert dtes <= {25, 28, 30}
    assert tps <= {0.20, 0.30, 0.40, 0.50}
    assert sls <= {0.15, 0.20, 0.30}

    # Preserve each survivor's regime/volume/hold; only vary DTE/TP/SL
    for s in refined:
        assert isinstance(s, StageASpec)
        entry = s.overrides["entry"]
        if s.max_hold_sessions == 3:
            assert entry["regime_gate"] == "OFF"
            assert entry.get("volume_gate_max_pctile") == 0.33
            assert entry["prior_day_spy_positive"] is False
        elif s.max_hold_sessions == 5:
            assert entry["regime_gate"] == "GREEN"
            assert entry.get("volume_gate_max_pctile") is None
            assert entry["prior_day_spy_positive"] is False
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
            max_grid=5,
            allow_large=False,
        )


def _twelve_distinct_seeds() -> list[dict]:
    """12 unique regime/volume/hold seeds (coarse DTE/TP/SL)."""
    grid = build_stage_a_grid()
    seeds: list[dict] = []
    seen_keys: set[tuple] = set()
    for cell in grid:
        entry = cell.overrides["entry"]
        key = (
            entry.get("regime_gate"),
            entry.get("volume_gate_max_pctile"),
            entry.get("regime_yellow_frac_min"),
            entry.get("regime_yellow_require_bounce"),
            entry.get("prior_day_spy_positive"),
            cell.max_hold_sessions,
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        seeds.append(
            {
                "variant_id": cell.variant_id,
                "regime_gate": entry.get("regime_gate"),
                "volume_gate_max_pctile": entry.get("volume_gate_max_pctile"),
                "regime_yellow_frac_min": entry.get("regime_yellow_frac_min"),
                "regime_yellow_require_bounce": entry.get(
                    "regime_yellow_require_bounce"
                ),
                "prior_day_spy_positive": entry.get("prior_day_spy_positive"),
                "max_hold_sessions": cell.max_hold_sessions,
                "dte_target": entry.get("dte_target", 30),
                "take_profit_pct": cell.overrides["exit"]["take_profit_pct"],
                "stop_loss_pct": cell.overrides["exit"]["stop_loss_pct"],
            }
        )
        if len(seeds) >= 12:
            break
    assert len(seeds) == 12
    return seeds


def _seed_key_from_row(row: dict) -> tuple:
    return (
        str(row.get("regime_gate") or "").upper(),
        (
            None
            if row.get("volume_gate_max_pctile") is None
            else round(float(row["volume_gate_max_pctile"]), 4)
        ),
        (
            None
            if row.get("regime_yellow_frac_min") is None
            else round(float(row["regime_yellow_frac_min"]), 4)
        ),
        (
            None
            if row.get("regime_yellow_require_bounce") is None
            else bool(row.get("regime_yellow_require_bounce"))
        ),
        bool(row.get("prior_day_spy_positive", False)),
        int(row.get("max_hold_sessions") or 0),
    )


def _seed_key_from_cell(cell: StageASpec) -> tuple:
    entry = cell.overrides["entry"]
    return (
        str(entry.get("regime_gate") or "").upper(),
        (
            None
            if entry.get("volume_gate_max_pctile") is None
            else round(float(entry["volume_gate_max_pctile"]), 4)
        ),
        (
            None
            if entry.get("regime_yellow_frac_min") is None
            else round(float(entry["regime_yellow_frac_min"]), 4)
        ),
        (
            None
            if entry.get("regime_yellow_require_bounce") is None
            else bool(entry.get("regime_yellow_require_bounce"))
        ),
        bool(entry.get("prior_day_spy_positive", False)),
        int(cell.max_hold_sessions),
    )


def test_refine_stage_a_round_robin_fairness_twelve_seeds():
    """Default budget must not exhaust Cartesian neighbors seed-by-seed.

    With 12 seeds and budget >= 12, every seed gets at least one one-axis
    neighbor before any seed receives a second neighbor.
    """
    seeds = _twelve_distinct_seeds()
    existing = {s["variant_id"] for s in seeds}
    budget = 120  # default refine budget
    refined = refine_stage_a(
        seeds, existing_ids=set(existing), budget_remaining=budget
    )
    assert refined
    assert len(refined) <= budget

    seed_keys = {_seed_key_from_row(s) for s in seeds}
    counts: dict[tuple, int] = {k: 0 for k in seed_keys}
    for cell in refined:
        key = _seed_key_from_cell(cell)
        assert key in counts, f"neighbor not tied to a seed: {key}"
        counts[key] += 1
        # One-axis only: exactly one of dte/tp/sl differs from coarse seed
        entry = cell.overrides["entry"]
        exit_cfg = cell.overrides["exit"]
        diffs = 0
        if int(entry["dte_target"]) != 30:
            diffs += 1
        if float(exit_cfg["take_profit_pct"]) != 0.30:
            diffs += 1
        if float(exit_cfg["stop_loss_pct"]) != 0.20:
            diffs += 1
        assert diffs == 1, (
            f"expected one-axis neighbor, got multi-axis {cell.variant_id}"
        )

    # Every seed covered at least once under default budget
    assert all(c >= 1 for c in counts.values()), counts

    # Fair order: no seed receives a second neighbor before all seeds have one
    running: dict[tuple, int] = {k: 0 for k in seed_keys}
    for cell in refined:
        key = _seed_key_from_cell(cell)
        if running[key] >= 1:
            assert all(v >= 1 for v in running.values()), (
                "second neighbor allocated before every seed got a first"
            )
        running[key] += 1

    # Tight budget == n_seeds: each seed gets exactly one (unique) neighbor
    one_each = refine_stage_a(
        seeds, existing_ids=set(existing), budget_remaining=12
    )
    one_counts: dict[tuple, int] = {k: 0 for k in seed_keys}
    for cell in one_each:
        one_counts[_seed_key_from_cell(cell)] += 1
    assert all(c == 1 for c in one_counts.values()), one_counts
    assert len(one_each) == 12


def test_rank_key_prefers_qualified_sample_then_mean_gap_median():
    """min_trades must dominate ranking: qualified before high-mean low-sample."""
    low_sample_high_mean = {
        "variant_id": "low",
        "n_holdout": 2,
        "holdout_mean_net_pnl_pct": 0.99,
        "stability_gap": 0.0,
        "holdout_median_net_pnl_pct": 0.50,
    }
    qualified_lower_mean = {
        "variant_id": "ok",
        "n_holdout": 10,
        "holdout_mean_net_pnl_pct": 0.05,
        "stability_gap": 0.10,
        "holdout_median_net_pnl_pct": 0.02,
    }
    min_trades = 8
    rows = [low_sample_high_mean, qualified_lower_mean]
    rows.sort(key=lambda r: _rank_key(r, min_trades=min_trades), reverse=True)
    assert rows[0]["variant_id"] == "ok"
    assert rows[1]["variant_id"] == "low"

    # Within qualified: mean desc, gap asc, median higher, then sample
    a = {
        "variant_id": "a",
        "n_holdout": 12,
        "holdout_mean_net_pnl_pct": 0.10,
        "stability_gap": 0.05,
        "holdout_median_net_pnl_pct": 0.01,
    }
    b = {
        "variant_id": "b",
        "n_holdout": 12,
        "holdout_mean_net_pnl_pct": 0.10,
        "stability_gap": 0.01,  # smaller gap wins
        "holdout_median_net_pnl_pct": 0.01,
    }
    c = {
        "variant_id": "c",
        "n_holdout": 12,
        "holdout_mean_net_pnl_pct": 0.10,
        "stability_gap": 0.01,
        "holdout_median_net_pnl_pct": 0.08,  # higher median vs b
    }
    # b vs c: same mean/gap → higher median wins → c before b
    # a has larger gap → last among the three
    ranked = sorted([a, b, c], key=lambda r: _rank_key(r, min_trades=8), reverse=True)
    assert [r["variant_id"] for r in ranked] == ["c", "b", "a"]

    # Equal mean/gap/median → larger sample ranks higher
    d1 = {
        "variant_id": "d1",
        "n_holdout": 8,
        "holdout_mean_net_pnl_pct": 0.05,
        "stability_gap": 0.0,
        "holdout_median_net_pnl_pct": 0.0,
    }
    d2 = {
        "variant_id": "d2",
        "n_holdout": 20,
        "holdout_mean_net_pnl_pct": 0.05,
        "stability_gap": 0.0,
        "holdout_median_net_pnl_pct": 0.0,
    }
    ranked2 = sorted([d1, d2], key=lambda r: _rank_key(r, min_trades=8), reverse=True)
    assert ranked2[0]["variant_id"] == "d2"


def test_finalists_prefer_qualified_low_sample_fallback_marked():
    """Refinement/MCPT finalists come from qualified rows when any exist."""
    rows = [
        {
            "variant_id": "low_hi",
            "n_holdout": 2,
            "holdout_mean_net_pnl_pct": 0.50,
            "stability_gap": 0.0,
            "holdout_median_net_pnl_pct": 0.4,
            "low_sample": True,
        },
        {
            "variant_id": "ok1",
            "n_holdout": 10,
            "holdout_mean_net_pnl_pct": 0.05,
            "stability_gap": 0.02,
            "holdout_median_net_pnl_pct": 0.03,
            "low_sample": False,
        },
        {
            "variant_id": "ok2",
            "n_holdout": 9,
            "holdout_mean_net_pnl_pct": 0.04,
            "stability_gap": 0.01,
            "holdout_median_net_pnl_pct": 0.02,
            "low_sample": False,
        },
    ]
    finalists = _select_stage_a_finalists(rows, top_k=12, min_trades=8)
    ids = [r["variant_id"] for r in finalists]
    assert "low_hi" not in ids
    assert set(ids) == {"ok1", "ok2"}

    only_low = [
        {
            "variant_id": "l1",
            "n_holdout": 1,
            "holdout_mean_net_pnl_pct": 0.2,
            "stability_gap": 0.0,
            "holdout_median_net_pnl_pct": 0.1,
            "low_sample": True,
        },
        {
            "variant_id": "l2",
            "n_holdout": 3,
            "holdout_mean_net_pnl_pct": 0.1,
            "stability_gap": 0.0,
            "holdout_median_net_pnl_pct": 0.05,
            "low_sample": True,
        },
    ]
    fallback = _select_stage_a_finalists(only_low, top_k=2, min_trades=8)
    assert len(fallback) == 2
    assert all(r.get("low_sample") is True for r in fallback)


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


def test_sensitivity_slippage_fields_scale_and_base_immutable():
    """Slippage fields scale by mult; base rules and seed overrides stay immutable."""
    import xsp_killer.backtest.regime_hold as rh

    candidate = _candidate_cell()
    bars = load_fixture_daily()
    base_pe = _base_paper_economics()
    rules_before = deepcopy(load_base_rules().get("paper_economics") or {})
    ov_before = deepcopy(candidate.overrides)
    captured: list[tuple[float, float, dict]] = []
    original = rh.run_backtest

    def _capture(bars_arg, rules_path, **kwargs):
        with Path(rules_path).open(encoding="utf-8") as fh:
            rules = yaml.safe_load(fh) or {}
        pe = dict(rules.get("paper_economics") or {})
        mult = (
            float(pe["slippage_usd_per_share"]) / base_pe["slippage_usd_per_share"]
            if base_pe["slippage_usd_per_share"]
            else 1.0
        )
        captured.append((float(kwargs.get("iv_seed", 0.0)), mult, pe))
        return original(bars_arg, rules_path, **kwargs)

    with patch.object(rh, "run_backtest", side_effect=_capture):
        result = run_sensitivity(candidate, bars, source="fixture")

    assert result["cells"]
    assert load_base_rules().get("paper_economics") == rules_before
    assert candidate.overrides == ov_before

    for _iv, mult, pe in captured:
        assert mult in (1.0, 1.5, 2.0)
        assert pe["slippage_usd_per_share"] == pytest.approx(
            base_pe["slippage_usd_per_share"] * mult
        )
        assert pe["slippage_pct_of_premium"] == pytest.approx(
            base_pe["slippage_pct_of_premium"] * mult
        )
        assert pe["slippage_max_pct_of_premium"] == pytest.approx(
            base_pe["slippage_max_pct_of_premium"] * mult
        )
        assert pe["commission_usd_per_contract"] == pytest.approx(
            base_pe["commission_usd_per_contract"]
        )
        assert pe["premium_scale"] == pytest.approx(base_pe["premium_scale"])


def test_sensitivity_iv_majority_when_baseline_absent():
    """When IV 0.18 is absent, 1.5x pass uses actual positives/total majority."""
    from types import SimpleNamespace

    import xsp_killer.backtest.regime_hold as rh

    candidate = _candidate_cell()
    bars = load_fixture_daily()

    def _fake_bt(bars_arg, rules_path, **kwargs):
        iv = float(kwargs.get("iv_seed", 0.0))
        with Path(rules_path).open(encoding="utf-8") as fh:
            rules = yaml.safe_load(fh) or {}
        pe = rules.get("paper_economics") or {}
        base = _base_paper_economics()
        mult = (
            float(pe["slippage_usd_per_share"]) / base["slippage_usd_per_share"]
            if base["slippage_usd_per_share"]
            else 1.0
        )
        # At 1.5x: iv 0.14 and 0.22 positive, 0.28 negative → 2/3 majority
        if abs(mult - 1.5) < 1e-9:
            mean = 0.05 if iv in (0.14, 0.22) else -0.05
        else:
            mean = 0.01
        return SimpleNamespace(
            trades=[SimpleNamespace(net_pnl_pct=mean)], n_entries_blocked=0
        )

    with patch.object(rh, "run_backtest", side_effect=_fake_bt):
        result = run_sensitivity(
            candidate,
            bars,
            source="fixture",
            iv_seeds=(0.14, 0.22, 0.28),
            slippage_mults=(1.0, 1.5, 2.0),
        )
    assert 0.18 not in result["iv_seeds"]
    slip_15 = [
        c for c in result["cells"] if abs(float(c["slippage_mult"]) - 1.5) < 1e-9
    ]
    assert len(slip_15) == 3
    assert sum(1 for c in slip_15 if c["positive"]) == 2
    assert result["slippage_1_5x_positive"] is True

    def _fake_bt_minority(bars_arg, rules_path, **kwargs):
        iv = float(kwargs.get("iv_seed", 0.0))
        with Path(rules_path).open(encoding="utf-8") as fh:
            rules = yaml.safe_load(fh) or {}
        pe = rules.get("paper_economics") or {}
        base = _base_paper_economics()
        mult = (
            float(pe["slippage_usd_per_share"]) / base["slippage_usd_per_share"]
            if base["slippage_usd_per_share"]
            else 1.0
        )
        if abs(mult - 1.5) < 1e-9:
            mean = 0.05 if iv == 0.14 else -0.05
        else:
            mean = 0.01
        return SimpleNamespace(
            trades=[SimpleNamespace(net_pnl_pct=mean)], n_entries_blocked=0
        )

    with patch.object(rh, "run_backtest", side_effect=_fake_bt_minority):
        result2 = run_sensitivity(
            candidate,
            bars,
            source="fixture",
            iv_seeds=(0.14, 0.22, 0.28),
            slippage_mults=(1.0, 1.5, 2.0),
        )
    assert result2["slippage_1_5x_positive"] is False


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
            "dte_target": 30,
            "take_profit_pct": 0.30,
            "stop_loss_pct": 0.20,
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
            "dte_target": 30,
            "take_profit_pct": 0.30,
            "stop_loss_pct": 0.20,
        },
        {
            "variant_id": "h2",
            "holdout_mean_net_pnl_pct": 0.03,
            "max_hold_sessions": 2,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": None,
            "dte_target": 30,
            "take_profit_pct": 0.30,
            "stop_loss_pct": 0.20,
        },
        {
            "variant_id": "h_neg",
            "holdout_mean_net_pnl_pct": -0.02,
            "max_hold_sessions": 3,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": None,
            "dte_target": 30,
            "take_profit_pct": 0.30,
            "stop_loss_pct": 0.20,
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
            "dte_target": 30,
            "take_profit_pct": 0.30,
            "stop_loss_pct": 0.20,
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


def test_behavioral_clones_do_not_form_stability_or_consume_finalist_quota():
    from types import SimpleNamespace

    base = {
        "train_mean_net_pnl_pct": 0.04,
        "validation_mean_net_pnl_pct": 0.03,
        "test_mean_net_pnl_pct": 0.02,
        "full_mean_net_pnl_pct": 0.03,
        "n_validation": 12,
        "n_holdout": 12,
        "max_hold_sessions": 1,
        "regime_gate": "GREEN",
        "prior_day_spy_positive": False,
        "regime_yellow_frac_min": None,
        "dte_target": 30,
        "take_profit_pct": 0.30,
        "stop_loss_pct": 0.20,
    }
    rows = [
        dict(base, variant_id="original"),
        dict(base, variant_id="clone", max_hold_sessions=2),
        dict(base, variant_id="distinct", max_hold_sessions=3),
    ]
    shared = [
        SimpleNamespace(entry_ts="2026-01-02", exit_ts="2026-01-03", exit_reason="tp")
    ]
    distinct = [
        SimpleNamespace(entry_ts="2026-01-02", exit_ts="2026-01-04", exit_reason="tp")
    ]
    annotate_behavior_duplicates(
        rows,
        {"original": shared, "clone": list(shared), "distinct": distinct},
    )
    assert rows[1]["behavior_duplicate_of"] == "original"
    assert stable_windows(rows) == []
    finalists = _select_stage_a_finalists(rows, top_k=3, min_trades=8)
    assert [row["variant_id"] for row in finalists] == ["original", "distinct"]

    from scripts.optimize_regime_hold import _select_finalists

    cli_finalists = _select_finalists(rows, top_k=3, min_trades=8)
    assert [row["variant_id"] for row in cli_finalists] == [
        "original",
        "distinct",
    ]


def test_behavioral_clone_does_not_change_mcpt_family_or_finalist_quota():
    from xsp_killer.backtest.regime_hold import _stage_a_mcpt_family
    from xsp_killer.backtest.report import familywise_max_stat_mcpt

    sessions = [f"2026-01-{day:02d}" for day in range(1, 21)]
    observations = [(session, 0.1) for session in sessions]
    base = {
        "n_validation": len(observations),
        "validation_mean_net_pnl_pct": 0.1,
        "validation_observations": observations,
    }
    unique_rows = [
        dict(base, variant_id="original"),
        dict(base, variant_id="distinct", validation_mean_net_pnl_pct=0.09),
    ]
    rows_with_clone = [
        unique_rows[0],
        dict(base, variant_id="clone", behavior_duplicate_of="original"),
        unique_rows[1],
    ]

    family_without = _stage_a_mcpt_family(unique_rows, min_trades=8)
    family_with = _stage_a_mcpt_family(rows_with_clone, min_trades=8)
    assert family_with == family_without
    assert "clone" not in family_with
    assert familywise_max_stat_mcpt(
        family_with, n_perm=100, seed=7
    ) == familywise_max_stat_mcpt(family_without, n_perm=100, seed=7)

    finalists = _select_stage_a_finalists(rows_with_clone, top_k=2, min_trades=8)
    assert [row["variant_id"] for row in finalists] == ["original", "distinct"]


def test_test_exit_perturbation_cannot_change_selection_behavior_dedupe():
    from types import SimpleNamespace

    rows_a = [{"variant_id": "a"}, {"variant_id": "b"}]
    rows_b = deepcopy(rows_a)
    selection = {
        variant: [
            SimpleNamespace(
                entry_ts="2026-01-02",
                exit_ts="2026-01-03",
                exit_reason="take_profit",
            )
        ]
        for variant in ("a", "b")
    }
    full_before = {
        **selection,
        "b": selection["b"]
        + [
            SimpleNamespace(
                entry_ts="2026-09-01",
                exit_ts="2026-09-02",
                exit_reason="test_exit",
            )
        ],
    }
    full_after = {
        **selection,
        "b": selection["b"]
        + [
            SimpleNamespace(
                entry_ts="2026-09-01",
                exit_ts="2026-09-09",
                exit_reason="perturbed_test_exit",
            )
        ],
    }
    annotate_behavior_duplicates(rows_a, selection, full_before)
    annotate_behavior_duplicates(rows_b, selection, full_after)
    assert rows_a[1]["behavior_duplicate_of"] == "a"
    assert rows_b[1]["behavior_duplicate_of"] == "a"
    assert rows_a[1]["selection_behavior_signature"] == rows_b[1][
        "selection_behavior_signature"
    ]
    assert rows_a[1]["full_behavior_signature"] != rows_b[1][
        "full_behavior_signature"
    ]


def test_train_behavior_clones_do_not_consume_refinement_seed_quota():
    rows = [
        {
            "variant_id": variant,
            "n_train": 10,
            "train_mean_net_pnl_pct": mean,
            "behavior_duplicate_of": duplicate,
        }
        for variant, mean, duplicate in [
            ("a", 0.03, None),
            ("a_clone", 0.02, "a"),
            ("b", 0.01, None),
        ]
    ]
    from xsp_killer.backtest.regime_hold import select_train_refinement_seeds

    selected = select_train_refinement_seeds(rows, top_k=2, min_trades=8)
    assert [row["variant_id"] for row in selected] == ["a", "b"]


def test_train_behavior_canonical_is_independent_of_validation_order():
    from types import SimpleNamespace

    rows = [
        {
            "variant_id": "lower_train",
            "train_mean_net_pnl_pct": 0.01,
            "validation_mean_net_pnl_pct": 0.99,
        },
        {
            "variant_id": "higher_train",
            "train_mean_net_pnl_pct": 0.02,
            "validation_mean_net_pnl_pct": -0.99,
        },
    ]
    shared = [
        SimpleNamespace(entry_ts="2026-01-02", exit_ts="2026-01-03", exit_reason="tp")
    ]
    annotate_behavior_duplicates(
        rows,
        {"lower_train": shared, "higher_train": list(shared)},
        canonical_metric="train_mean_net_pnl_pct",
    )
    by_id = {row["variant_id"]: row for row in rows}
    assert by_id["higher_train"]["behavior_duplicate_of"] is None
    assert by_id["lower_train"]["behavior_duplicate_of"] == "higher_train"


def test_edge_candidate_checks_ranked_finalists_until_one_passes(monkeypatch):
    from scripts import optimize_regime_hold as cli

    finalists = [{"variant_id": "first"}, {"variant_id": "second"}]
    calls: list[str] = []

    def fake_edge(row, sensitivity, intraday, **kwargs):
        calls.append(row["variant_id"])
        passed = row["variant_id"] == "second"
        return passed, "passed" if passed else "failed"

    monkeypatch.setattr(cli, "edge_confirmed", fake_edge)
    row, ok, reason = cli._select_edge_candidate(
        finalists,
        sensitivity_by_id={
            "first": {"variant_id": "first"},
            "second": {"variant_id": "second"},
        },
        intraday_by_id={"first": {}, "second": {}},
        run_b=True,
        min_trades=8,
        min_intraday_trades=20,
    )
    assert (row["variant_id"], ok, reason) == ("second", True, "passed")
    assert calls == ["first", "second"]


def test_edge_candidate_missing_sensitivity_fails_explicitly(monkeypatch):
    from scripts import optimize_regime_hold as cli

    monkeypatch.setattr(
        cli,
        "edge_confirmed",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("gate must not run without matching sensitivity")
        ),
    )
    row, ok, reason = cli._select_edge_candidate(
        [{"variant_id": "best"}],
        sensitivity_by_id={},
        intraday_by_id={"best": {}},
        run_b=True,
        min_trades=8,
        min_intraday_trades=20,
    )
    assert (row["variant_id"], ok, reason) == (
        "best",
        False,
        "sensitivity_missing",
    )


def test_edge_candidate_none_passes_returns_best_row_reason(monkeypatch):
    from scripts import optimize_regime_hold as cli

    monkeypatch.setattr(
        cli,
        "edge_confirmed",
        lambda row, *args, **kwargs: (False, f"{row['variant_id']}_failed"),
    )
    finalists = [{"variant_id": "best"}, {"variant_id": "next"}]
    row, ok, reason = cli._select_edge_candidate(
        finalists,
        sensitivity_by_id={
            "best": {"variant_id": "best"},
            "next": {"variant_id": "next"},
        },
        intraday_by_id={"best": {}, "next": {}},
        run_b=True,
        min_trades=8,
        min_intraday_trades=20,
    )
    assert (row["variant_id"], ok, reason) == ("best", False, "best_failed")


def test_distinct_adjacent_positive_behaviors_can_form_stability():
    rows = [
        {
            "variant_id": variant,
            "train_mean_net_pnl_pct": 0.04,
            "validation_mean_net_pnl_pct": 0.03,
            "test_mean_net_pnl_pct": 0.02,
            "full_mean_net_pnl_pct": 0.03,
            "max_hold_sessions": hold,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "regime_yellow_frac_min": None,
            "dte_target": 30,
            "take_profit_pct": 0.30,
            "stop_loss_pct": 0.20,
            "behavior_signature": variant,
        }
        for variant, hold in [("a", 1), ("b", 2)]
    ]
    assert stable_windows(rows)[0]["member_ids"] == ["a", "b"]


def test_markdown_decision_table_exposes_conflicting_metrics():
    from scripts.optimize_regime_hold import _report_to_markdown

    payload = {
        "generated_at": "now",
        "mode": "fixture",
        "recommendation": {"status": "RESEARCH ONLY"},
        "stage_a": {
            "fidelity": "daily_close_proxy",
            "source": "fixture",
            "ranking": [
                {
                    "variant_id": "conflict",
                    "max_hold_sessions": 2,
                    "n_train": 10,
                    "train_mean_net_pnl_pct": 0.10,
                    "n_validation": 4,
                    "validation_mean_net_pnl_pct": -0.02,
                    "n_test": 3,
                    "test_mean_net_pnl_pct": 0.03,
                    "full_mean_net_pnl_pct": 0.01,
                    "familywise_p_value": 0.2,
                    "familywise_pass_5pct": False,
                    "decision_status": "RESEARCH ONLY",
                    "stage_b": {
                        "n_trades": 2,
                        "mean_net_pnl_pct": -0.1,
                        "residual_open": 1,
                    },
                }
            ],
        },
    }
    text = _report_to_markdown(payload)
    first_table = text.split("|", 1)[1]
    assert "train%" in first_table
    assert "val%" in first_table
    assert "test%" in first_table
    assert "full%" in first_table
    assert "StageB n/mean" in first_table
    assert "residuals" in first_table
    assert "familywise p" in first_table
    assert "10.00" in text and "-2.00" in text and "3.00" in text
    assert "CANDIDATE" not in text
    assert "EDGE-CONFIRMED" not in text


def test_edge_confirmed_requires_all_gates():
    good_row = {
        "variant_id": "good",
        "train_mean_net_pnl_pct": 0.04,
        "validation_mean_net_pnl_pct": 0.05,
        "test_mean_net_pnl_pct": 0.03,
        "full_mean_net_pnl_pct": 0.04,
        "holdout_mean_net_pnl_pct": 0.05,
        "n_validation": 12,
        "n_holdout": 12,
        "familywise_pass_5pct": True,
        "stable_window": True,
    }
    sens_ok = {
        "iv_positive_count": 3,
        "iv_seeds": [0.14, 0.18, 0.22, 0.28],
        "slippage_1_5x_positive": True,
        "cells": [],
    }
    intraday_ok = {
        "n_trades": 20,
        "mean_net_pnl_pct": 0.01,
        "residual_open": 0,
    }

    ok, reason = edge_confirmed(
        good_row,
        sens_ok,
        intraday_ok,
        min_trades=8,
        min_intraday_trades=20,
    )
    assert ok is True
    assert reason == "research_survivor_inactive"

    # Fail: negative validation
    bad = dict(good_row, validation_mean_net_pnl_pct=-0.01)
    ok, _ = edge_confirmed(bad, sens_ok, intraday_ok, min_trades=8)
    assert ok is False

    # Fail: insufficient sample
    bad = dict(good_row, n_validation=3)
    ok, _ = edge_confirmed(bad, sens_ok, intraday_ok, min_trades=8)
    assert ok is False

    # Fail: MCPT
    bad = dict(good_row, familywise_pass_5pct=False)
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


@pytest.mark.parametrize(
    ("intraday", "reason"),
    [
        (
            {"n_trades": 0, "mean_net_pnl_pct": 0.1, "residual_open": 0},
            "intraday_sample_below_min",
        ),
        (
            {"n_trades": 20, "mean_net_pnl_pct": 0.0, "residual_open": 0},
            "intraday_mean_not_positive",
        ),
        (
            {"n_trades": 20, "mean_net_pnl_pct": 0.1, "residual_open": 1},
            "intraday_residual_open",
        ),
    ],
)
def test_edge_confirmed_rejects_weak_intraday(intraday, reason):
    row = {
        "n_validation": 12,
        "validation_mean_net_pnl_pct": 0.05,
        "train_mean_net_pnl_pct": 0.04,
        "test_mean_net_pnl_pct": 0.03,
        "full_mean_net_pnl_pct": 0.04,
        "familywise_pass_5pct": True,
        "stable_window": True,
    }
    sensitivity = {
        "iv_positive_count": 3,
        "slippage_1_5x_positive": True,
    }
    assert edge_confirmed(
        row,
        sensitivity,
        intraday,
        min_trades=8,
        min_intraday_trades=20,
    ) == (False, reason)


@pytest.mark.parametrize(
    "field",
    [
        "train_mean_net_pnl_pct",
        "validation_mean_net_pnl_pct",
        "test_mean_net_pnl_pct",
        "full_mean_net_pnl_pct",
    ],
)
@pytest.mark.parametrize("value", [0.0, -0.01])
def test_edge_confirmed_rejects_nonpositive_cross_split(field, value):
    row = {
        "n_validation": 12,
        "train_mean_net_pnl_pct": 0.04,
        "validation_mean_net_pnl_pct": 0.05,
        "test_mean_net_pnl_pct": 0.03,
        "full_mean_net_pnl_pct": 0.04,
        "familywise_pass_5pct": True,
        "stable_window": True,
        field: value,
    }
    sensitivity = {
        "iv_positive_count": 3,
        "slippage_1_5x_positive": True,
    }
    intraday = {
        "n_trades": 20,
        "mean_net_pnl_pct": 0.01,
        "residual_open": 0,
    }
    assert edge_confirmed(
        row,
        sensitivity,
        intraday,
        min_trades=8,
        min_intraday_trades=20,
    ) == (False, "cross_split_mean_not_positive")


def test_recommended_yaml_always_inactive_no_live_text():
    row = {
        "variant_id": "rha_dte30_tp30_sl20_green_p0_h3",
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
        "exit": {"take_profit_pct": 0.30, "stop_loss_pct": 0.20},
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
    generated = yaml.safe_load(text)
    assert (
        generated[row["variant_id"]]["overrides"]["exit"]["max_hold_sessions"] == 3
    )
    # Generation must not mutate the caller's overrides.
    assert "max_hold_sessions" not in (ov.get("exit") or {})


def test_recommended_yaml_defaults_fail_closed_without_explicit_full_gate():
    row = {
        "variant_id": "partial_stage_a_winner",
        "n_validation": 20,
        "validation_mean_net_pnl_pct": 0.50,
        "familywise_pass_5pct": True,
        "stable_window": True,
        "max_hold_sessions": 3,
    }
    text = recommended_regime_hold_yaml(row, {"exit": {}})

    assert "RESEARCH ONLY" in text
    assert "RESEARCH-SURVIVOR" not in text


def test_modeled_pricing_is_never_promotion_eligible():
    assert (
        promotion_eligible(
            True,
            pricing_fidelity="modeled_bs_lite",
            paper_confirmation=True,
        )
        is False
    )
    assert (
        promotion_eligible(
            True,
            pricing_fidelity="historical_xsp_chain",
            paper_confirmation=False,
        )
        is False
    )
