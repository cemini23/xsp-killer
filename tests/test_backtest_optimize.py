"""Offline tests for centered 28 DTE ATM optimize (fixture-only, no network)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from xsp_killer.backtest.bars import load_fixture_daily
from xsp_killer.backtest.engine import TradeRow
from xsp_killer.backtest.optimize import (
    GridBudgetError,
    build_centered_grid,
    optimize_report_to_markdown,
    partition_trades_by_split,
    partition_trades_three_way,
    recommended_variant_yaml,
    run_optimize,
    write_optimize_report,
)
from xsp_killer.backtest.sweep import BASE_28DTE_ATM_OVERRIDES

ROOT = Path(__file__).resolve().parents[1]


def test_base_is_28dte_atm_bb_off():
    base = BASE_28DTE_ATM_OVERRIDES
    entry = base["entry"]
    exit_cfg = base["exit"]
    ta_entry = base["ta"]["entry"]
    assert entry["dte_pick"] == "target"
    assert entry["dte_target"] == 28
    assert entry["strike_pick"] == "atm_only"
    assert entry["regime_gate"] == "GREEN"
    assert entry["prior_day_spy_positive"] is False
    assert ta_entry["mode"] == "close_window_only"
    assert exit_cfg["take_profit_pct"] == 0.10
    assert exit_cfg["stop_loss_pct"] == 0.20
    assert exit_cfg["require_upper_bb_for_take_profit"] is False
    assert exit_cfg["swing_hold"] is False


def test_grid_size_72_unique_ids_no_strike():
    specs = build_centered_grid()
    assert len(specs) == 72
    ids = [s.variant_id for s in specs]
    assert len(ids) == len(set(ids)), "variant ids must be unique"
    for s in specs:
        strike = (s.overrides.get("entry") or {}).get("strike_pick")
        assert strike == "atm_only"
        assert "cheapest" not in s.variant_id
        assert "otm" not in s.variant_id
        assert "strike" not in s.variant_id


def test_partition_trades_by_split():
    bars = load_fixture_daily()
    n = len(bars)
    mid_i = int(n * 0.6) - 1
    early_ts = str(bars.index[max(0, mid_i - 5)])
    late_ts = str(bars.index[min(n - 1, mid_i + 5)])
    trades = [
        TradeRow(
            variant_id="t",
            entry_ts=early_ts,
            exit_ts=early_ts,
            dte_at_entry=28,
            strike=400.0,
            exit_reason="take_profit",
            net_pnl_pct=0.1,
            pnl_usd=10.0,
            entry_mid=5.0,
            exit_mid=5.5,
            entry_fill=5.1,
            bars_held=2,
        ),
        TradeRow(
            variant_id="t",
            entry_ts=late_ts,
            exit_ts=late_ts,
            dte_at_entry=28,
            strike=400.0,
            exit_reason="stop_loss",
            net_pnl_pct=-0.1,
            pnl_usd=-10.0,
            entry_mid=5.0,
            exit_mid=4.5,
            entry_fill=5.1,
            bars_held=2,
        ),
    ]
    train, holdout, split_iso = partition_trades_by_split(
        trades, bars, split_frac=0.6
    )
    assert split_iso
    assert len(train) + len(holdout) == 2
    assert len(train) == 1
    assert len(holdout) == 1
    assert train[0].net_pnl_pct == 0.1
    assert holdout[0].net_pnl_pct == -0.1


def test_partition_trades_three_way_is_contiguous_and_nonoverlapping():
    bars = load_fixture_daily()
    indexes = [10, int(len(bars) * 0.6), int(len(bars) * 0.8), len(bars) - 1]
    trades = [
        TradeRow(
            variant_id="split",
            entry_ts=str(bars.index[i]),
            exit_ts=str(bars.index[i]),
            dte_at_entry=28,
            strike=400.0,
            exit_reason="take_profit",
            net_pnl_pct=float(i),
            pnl_usd=0.0,
            entry_mid=5.0,
            exit_mid=5.0,
            entry_fill=5.0,
            bars_held=0,
        )
        for i in indexes
    ]
    train, validation, test, cuts = partition_trades_three_way(trades, bars)
    assert len(train) + len(validation) + len(test) == len(trades)
    assert {id(t) for t in train}.isdisjoint({id(t) for t in validation})
    assert {id(t) for t in train}.isdisjoint({id(t) for t in test})
    assert {id(t) for t in validation}.isdisjoint({id(t) for t in test})
    assert max(pd.Timestamp(t.entry_ts) for t in train) <= pd.Timestamp(
        cuts["train_end"]
    )
    assert min(pd.Timestamp(t.entry_ts) for t in test) > pd.Timestamp(
        cuts["validation_end"]
    )


def test_test_period_perturbation_cannot_change_refinement_specs():
    from xsp_killer.backtest.regime_hold import (
        refine_stage_a,
        select_train_refinement_seeds,
    )

    rows = [
        {
            "variant_id": f"rha_dte28_tp20_sl30_green_p0_h{hold}",
            "train_mean_net_pnl_pct": train,
            "n_train": 12,
            "validation_mean_net_pnl_pct": 0.01,
            "test_mean_net_pnl_pct": test,
            "regime_gate": "GREEN",
            "prior_day_spy_positive": False,
            "max_hold_sessions": hold,
            "dte_target": 28,
            "take_profit_pct": 0.20,
            "stop_loss_pct": 0.30,
        }
        for hold, train, test in [(1, 0.03, -99.0), (2, 0.02, 99.0), (3, 0.01, 0.0)]
    ]
    perturbed = [
        dict(row, test_mean_net_pnl_pct=-row["test_mean_net_pnl_pct"])
        for row in rows
    ]
    seeds_a = select_train_refinement_seeds(rows, top_k=2, min_trades=8)
    seeds_b = select_train_refinement_seeds(perturbed, top_k=2, min_trades=8)
    ids = {row["variant_id"] for row in rows}
    specs_a = refine_stage_a(seeds_a, existing_ids=set(ids), budget_remaining=20)
    specs_b = refine_stage_a(seeds_b, existing_ids=set(ids), budget_remaining=20)
    assert [spec.variant_id for spec in specs_a] == [
        spec.variant_id for spec in specs_b
    ]


def test_run_optimize_familywise_mcpt_covers_all_qualified_variants():
    bars = load_fixture_daily()
    top_k = 3
    payload = run_optimize(
        bars,
        split_frac=0.6,
        min_trades=1,
        top_k=top_k,
        run_mcpt=True,
        n_perm=50,
        source="fixture",
        mode="fixture",
    )
    ranking = payload["ranking"]
    assert len(ranking) == 72
    with_familywise = [r for r in ranking if "familywise_p_value" in r]
    qualified = [r for r in ranking if int(r.get("n_validation") or 0) >= 1]
    assert len(with_familywise) == len(qualified)
    exploratory = [r for r in ranking if "exploratory_mcpt" in r]
    assert len(exploratory) <= top_k
    assert all(
        r["exploratory_mcpt"]["adjustment"]
        == "unadjusted_single_variant_exploratory"
        for r in exploratory
    )
    assert payload["recommendation"]["variant_id"]
    snippet = payload["recommendation"].get("yaml_snippet") or ""
    assert "active: false" in snippet.lower() or "active: false" in snippet


def test_budget_guard():
    try:
        build_centered_grid(
            allow_large=False,
            max_grid=10,
            dtes=(21, 28, 35),
            tps=(0.08, 0.10, 0.15, 0.20),
            sls=(0.15, 0.20, 0.30),
        )
        raise AssertionError("expected GridBudgetError")
    except GridBudgetError as exc:
        assert "80" in str(exc) or "budget" in str(exc).lower() or "10" in str(exc)

    # with allow_large, still builds full 72
    specs = build_centered_grid(allow_large=True, max_grid=10)
    assert len(specs) == 72


def test_recommended_yaml_active_false_no_live_secrets():
    row = {
        "variant_id": "opt_dte28_tp10_sl20_green",
        "n_holdout": 12,
        "holdout_mean_net_pnl_pct": 0.02,
        "mcpt_pass_5pct": True,
    }
    ov = {
        "entry": {"dte_target": 28, "strike_pick": "atm_only", "regime_gate": "GREEN"},
        "exit": {"take_profit_pct": 0.10, "stop_loss_pct": 0.20},
    }
    text = recommended_variant_yaml(row, ov, min_trades=8)
    assert "active: false" in text or "active: false" in text.lower()
    # PyYAML dumps bool as "false"
    assert "false" in text.lower()
    low = text.lower()
    assert "live_entries" not in low
    assert "live_exits" not in low
    assert "unusual_whales_api_key" not in low
    assert "secret" not in low or "active: false" in text
    assert "RESEARCH" in text
    assert "PROMOTE" not in text
    assert "CANDIDATE" not in text


def test_cli_fixture_offline(tmp_path):
    out = tmp_path / "reports"
    env = {**os.environ, "UNUSUAL_WHALES_API_KEY": ""}
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "optimize_lane_a.py"),
            "--mode",
            "fixture",
            "--top-k",
            "2",
            "--min-trades",
            "1",
            "--out",
            str(out),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    jsons = list(out.glob("optimize_*.json"))
    mds = list(out.glob("optimize_*.md"))
    assert jsons, "expected optimize json report"
    assert mds, "expected optimize markdown report"
    payload = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert payload.get("ranking")
    assert "LIVE_ENTRIES" not in jsons[0].read_text(encoding="utf-8")


def test_cli_uw_no_key_fallback(tmp_path):
    out = tmp_path / "reports_uw"
    env = {**os.environ}
    env["UNUSUAL_WHALES_API_KEY"] = ""
    # Point tipdrop at empty dir so key load finds nothing
    env["XSP_UW_TIPDROP_ROOT"] = str(tmp_path / "no_tipdrop")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "optimize_lane_a.py"),
            "--mode",
            "uw",
            "--top-k",
            "2",
            "--min-trades",
            "1",
            "--out",
            str(out),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    combined = (proc.stderr + proc.stdout).lower()
    assert "fell back" in combined or list(out.glob("optimize_*.json"))
    # never print key material
    assert "unusual_whales_api_key=" not in combined


def test_no_secrets_in_artifacts(tmp_path):
    bars = load_fixture_daily()
    payload = run_optimize(
        bars,
        split_frac=0.6,
        min_trades=1,
        top_k=2,
        run_mcpt=False,
        source="fixture",
        mode="fixture",
    )
    j, m = write_optimize_report(payload, tmp_path, stem="opt_sec")
    for path in (j, m):
        text = path.read_text(encoding="utf-8")
        low = text.lower()
        assert "unusual_whales_api_key" not in low
        assert "live_entries" not in low or "untouched" in low
        # no env file dumps
        assert "password" not in low
        assert "api_key:" not in low
        # recommendation always inactive
        if "yaml_snippet" in text or "active" in low:
            assert "active: false" in text or "active:false" in low.replace(" ", "")


def test_optimizer_markdown_exposes_conflicting_split_metrics():
    payload = {
        "generated_at": "now",
        "mode": "fixture",
        "source": "fixture",
        "grid": {"n_specs": 1, "base": "base"},
        "split": {
            "train_frac": 0.6,
            "validation_frac": 0.2,
            "test_frac": 0.2,
        },
        "disclaimer": "Modeled pricing.",
        "recommendation": {
            "status": "RESEARCH ONLY",
            "variant_id": "conflict",
        },
        "ranking": [
            {
                "variant_id": "conflict",
                "n_train": 10,
                "train_mean_net_pnl_pct": 0.10,
                "n_validation": 4,
                "validation_mean_net_pnl_pct": -0.02,
                "n_test": 3,
                "test_mean_net_pnl_pct": 0.03,
                "full_mean_net_pnl_pct": 0.01,
                "familywise_p_value": 0.2,
                "familywise_pass_5pct": False,
            }
        ],
    }
    text = optimize_report_to_markdown(payload)
    assert "train%" in text and "val%" in text and "test%" in text and "full%" in text
    assert "familywise p" in text
    assert "10.00" in text and "-2.00" in text and "3.00" in text
    assert "CANDIDATE" not in text and "PROMOTE" not in text
