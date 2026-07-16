"""Tests for Lane A variant soak."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import xsp_killer.lane_a_entry as lane_a_entry
from xsp_killer.lane_a_ta import TaSignal
from xsp_killer.lane_a_variants import (
    VariantSpec,
    _build_promotion_summary,
    _collapse_confounded_clones,
    build_scoreboard,
    clear_pnl_epoch,
    load_variant_specs,
    merged_rules_path,
    reset_soak,
    resync_epoch_briefs,
    resync_epoch_briefs_if_needed,
    run_variant_entry,
)


def _write_variants_config(tmp_path, variants: dict[str, dict]) -> None:
    import yaml

    (tmp_path / "lane_a_variants.yaml").write_text(
        yaml.safe_dump({"variants": variants}, sort_keys=False),
        encoding="utf-8",
    )


def test_load_variant_specs():
    specs = load_variant_specs()
    assert len(specs) >= 11
    ids = {s.variant_id for s in specs}
    assert "v2_28dte_atm" in ids
    assert "v2_28dte_atm_stack3" in ids
    assert "v2_21dte_atm" in ids
    assert "v2_yellow_top_quartile_bounce" in ids
    assert "v2_yellow_mid_bounce" in ids
    active_ids = {s.variant_id for s in specs if s.active}
    # 2026-07-16 UW BT: dip-swing pruned; soak 28 DTE ATM cluster
    assert len(active_ids) == 6
    assert "v2_28dte_atm" in active_ids
    assert "v2_28dte_easy_tp" in active_ids
    assert "v2_yellow_mid_bounce" in active_ids
    assert "v2_14dte_atm" in active_ids
    assert "v2_28dte_atm_stack3" in active_ids
    assert "v2_mid_tenor_80dte_atm" in active_ids
    assert "v2_dip_swing_55dte_otm" not in active_ids
    assert "v2_dip_swing_14dte" not in active_ids
    assert "v2_28dte_green_day" not in active_ids
    assert "v2_dip_swing_50dte_otm" not in active_ids
    assert "v2_yellow_top_quartile_bounce" not in active_ids
    assert "v2_21dte_atm" not in active_ids


def test_merged_rules_dte_target(tmp_path):
    specs = load_variant_specs()
    spec = next(s for s in specs if s.variant_id == "v2_28dte_atm")
    path = merged_rules_path(spec, tmp_dir=tmp_path)
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["entry"]["dte_pick"] == "target"
    assert data["entry"]["dte_target"] == 28
    assert data["entry"]["strike_pick"] == "atm_only"


def test_merged_rules_yellow_bounce_variant(tmp_path):
    specs = load_variant_specs()
    spec = next(s for s in specs if s.variant_id == "v2_yellow_top_quartile_bounce")
    path = merged_rules_path(spec, tmp_dir=tmp_path)
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["entry"]["regime_gate"] == "GREEN_OR_YELLOW_BOUNCE"
    assert data["entry"]["regime_yellow_frac_min"] == 0.75
    assert data["ta"]["entry"]["mode"] == "close_window_only"


def test_merged_rules_yellow_mid_bounce_variant(tmp_path):
    specs = load_variant_specs()
    spec = next(s for s in specs if s.variant_id == "v2_yellow_mid_bounce")
    path = merged_rules_path(spec, tmp_dir=tmp_path)
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["entry"]["regime_gate"] == "GREEN_OR_YELLOW_BOUNCE"
    assert data["entry"]["regime_yellow_frac_min"] == 0.50
    assert data["entry"]["regime_yellow_require_bounce"] is False
    assert data["logging"]["logic_version"] == "xsp_lane_a_v2_yellow_mid_bounce"
    assert data["ta"]["entry"]["mode"] == "close_window_only"


def test_merged_rules_stack3_variant(tmp_path):
    specs = load_variant_specs()
    spec = next(s for s in specs if s.variant_id == "v2_28dte_atm_stack3")
    path = merged_rules_path(spec, tmp_dir=tmp_path)
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["entry"]["dte_target"] == 28
    assert data["paper_entry"]["max_open_positions"] == 3


def test_merged_rules_operator_target_dte_stagger(tmp_path):
    """45–60 DTE OTM stagger grid matches operator dip-swing profile.

    All far-DTE OTM stay inactive after 2026-07-16 UW BT prune (55 was briefly
    re-enabled 2026-07-15). 55/60 still carry variant-only dte_max=65 for a
    future re-enable without Friday collision under baseline 60.
    """
    import yaml

    specs = load_variant_specs()
    targets = {
        45: "v2_dip_swing_45dte_otm",
        50: "v2_dip_swing_50dte_otm",
        55: "v2_dip_swing_55dte_otm",
        60: "v2_dip_swing_60dte_otm",
    }
    for dte, vid in targets.items():
        spec = next(s for s in specs if s.variant_id == vid)
        assert not spec.active
        data = yaml.safe_load(
            merged_rules_path(spec, tmp_dir=tmp_path).read_text(encoding="utf-8")
        )
        assert data["entry"]["dte_pick"] == "target"
        assert data["entry"]["dte_target"] == dte
        assert data["entry"]["strike_pick"] == "otm_one"
        assert data["entry"]["regime_gate"] == "DIP_BOUNCE"
        assert data["paper_entry"]["quantity"] == 2
        assert data["paper_entry"]["max_open_positions"] == 2
        assert data["exit"]["swing_hold"] is True
        assert data["ta"]["entry"]["mode"] == "bb_bounce"
        if dte in (55, 60):
            assert data["entry"]["dte_max"] == 65
        else:
            assert data["entry"]["dte_max"] == 60  # baseline overnight sleeve


def test_merged_rules_mid_tenor_lane_a_two_thirds(tmp_path):
    """Lane A⅔ mid-tenor: ~80 DTE, dte_max 90 variant-only (not baseline overnight)."""
    import yaml

    specs = load_variant_specs()
    spec = next(s for s in specs if s.variant_id == "v2_mid_tenor_80dte_atm")
    assert spec.active is True
    data = yaml.safe_load(
        merged_rules_path(spec, tmp_dir=tmp_path).read_text(encoding="utf-8")
    )
    assert data["entry"]["dte_pick"] == "target"
    assert data["entry"]["dte_target"] == 80
    assert data["entry"]["dte_min"] == 70
    assert data["entry"]["dte_max"] == 90
    assert data["entry"]["strike_pick"] == "atm_only"
    assert data["exit"]["swing_hold"] is True
    assert data["logging"]["logic_version"] == "xsp_lane_a_v2_mid_tenor_80dte_atm"


def test_build_scoreboard(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_28dte_atm": {
                "active": True,
                "description": "Test scoreboard variant",
                "overrides": {},
            }
        },
    )
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "paper_events": [
                            {
                                "paper_pnl_usd": 10.0,
                                "position_id": "paper:XSP:2026-07-18:6010",
                            },
                            {
                                "paper_pnl_usd": -5.0,
                                "position_id": "paper:XSP:2026-07-18:6010",
                            },
                        ],
                        "paper_positions": {
                            "paper:XSP:2026-07-18:6010": {
                                "position_id": "paper:XSP:2026-07-18:6010",
                                "status": "closed",
                                "dte_actual": 23,
                                "expiration_date": "2026-07-18",
                            }
                        },
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-22T19:45:00+00:00",
                                "entered": False,
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    out = build_scoreboard(
        config_path=tmp_path / "lane_a_variants.yaml",
        state_path=state,
        baseline_state_path=tmp_path / "missing-baseline.json",
        out_path=tmp_path / "scoreboard.json",
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    row = next(r for r in payload["variants"] if r["variant_id"] == "v2_28dte_atm")
    assert row["realized_pnl_usd"] == 5.0
    assert row["trades_closed"] == 2
    assert row["avg_pnl_per_trade_usd"] == 2.5
    assert row["sessions_evaluated"] == 1
    assert row["entry_evals_total"] == 1
    assert row["weekend_evals_excluded"] == 0
    assert row["sessions_to_gate"] == 19
    assert row["last_exit"]["dte_actual"] == 23
    assert row["last_exit"]["expiration"] == "2026-07-18"
    assert row["open_positions_mtm_usd"] == 0.0
    assert row["open_positions_mtm_usd_1x"] == 0.0
    assert row["contract_cluster_id"] == "XSP:call:2026-07-18:6010"
    assert row["low_sample"] is True
    assert payload["baseline_prod"] is None
    assert len(payload["shadow_variants"]) == 1
    assert payload["last_entry_eval_at"] == "2026-06-22T19:45:00+00:00"
    assert "Do NOT sum PnL" in payload["comparison_guidance"]
    assert payload["ranking_reliable"] is False
    assert payload["contract_clusters"]["XSP:call:2026-07-18:6010"]["variant_ids"] == [
        "v2_28dte_atm"
    ]


def test_build_scoreboard_includes_stateless_active_spec(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_test_a": {
                "active": True,
                "description": "Active with state",
                "overrides": {},
            },
            "v2_new_variant": {
                "active": True,
                "description": "Active without state",
                "overrides": {},
            },
            "v2_test_b": {
                "active": False,
                "description": "Inactive with stale state",
                "overrides": {},
            },
        },
    )
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_test_a": {
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-22T19:45:00+00:00",
                                "entered": False,
                            }
                        ],
                        "paper_events": [{"paper_pnl_usd": 4.0}],
                        "paper_positions": {},
                    },
                    "v2_test_b": {
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-23T20:00:00+00:00",
                                "entered": True,
                            }
                        ],
                        "paper_events": [{"paper_pnl_usd": 9.0}],
                        "paper_positions": {},
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard.json",
        ).read_text(encoding="utf-8")
    )

    variants = {row["variant_id"]: row for row in payload["shadow_variants"]}
    assert set(variants) == {"v2_test_a", "v2_new_variant"}
    assert variants["v2_test_a"]["sessions_evaluated"] == 1
    assert variants["v2_test_a"]["realized_pnl_usd"] == 4.0
    assert variants["v2_new_variant"]["sessions_evaluated"] == 0
    assert variants["v2_new_variant"]["trades_closed"] == 0
    assert variants["v2_new_variant"]["description"] == "Active without state"
    persisted = json.loads(state.read_text(encoding="utf-8"))
    assert persisted["variants"]["v2_new_variant"] == {
        "paper_positions": {},
        "entry_log": [],
        "paper_events": [],
        "positions": {},
    }


def test_build_scoreboard_ensures_stack3_slice_registration(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_28dte_atm_stack3": {
                "active": True,
                "description": "Stack3 active",
                "overrides": {},
            }
        },
    )
    state = tmp_path / "variants-state.json"
    state.write_text(json.dumps({"variants": {}}, indent=2) + "\n", encoding="utf-8")

    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard-stack3.json",
        ).read_text(encoding="utf-8")
    )

    assert payload["active_variant_ids"] == ["v2_28dte_atm_stack3"]
    assert payload["state_variant_ids"] == ["v2_28dte_atm_stack3"]
    persisted = json.loads(state.read_text(encoding="utf-8"))
    assert "v2_28dte_atm_stack3" in persisted["variants"]


def test_build_scoreboard_respects_soak_reset(tmp_path):
    reset_at = "2026-06-22T12:00:00+00:00"
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "soak_reset_at": reset_at,
                "variants": {
                    "v2_28dte_atm": {
                        "paper_events": [
                            {
                                "paper_pnl_usd": -10.0,
                                "evaluated_at": "2026-06-19T14:00:00+00:00",
                            },
                            {
                                "paper_pnl_usd": 7.0,
                                "evaluated_at": "2026-06-22T14:00:00+00:00",
                            },
                        ],
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-19T19:45:00+00:00",
                                "entered": False,
                            },
                            {
                                "evaluated_at": "2026-06-22T19:45:00+00:00",
                                "entered": False,
                            },
                            {
                                "evaluated_at": "2026-06-23T19:45:00+00:00",
                                "entered": True,
                            },
                        ],
                        "paper_positions": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    out = build_scoreboard(state_path=state, out_path=tmp_path / "scoreboard.json")
    payload = json.loads(out.read_text(encoding="utf-8"))
    row = next(r for r in payload["variants"] if r["variant_id"] == "v2_28dte_atm")
    assert row["realized_pnl_usd"] == 7.0
    assert row["trades_closed"] == 1
    assert row["sessions_evaluated"] == 2
    assert row["sessions_to_gate"] == 18
    assert payload["soak_reset_at"] == reset_at


def test_build_scoreboard_dedupes_weekday_sessions_and_excludes_weekends(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_28dte_atm": {
                "active": True,
                "description": "dedupe test",
                "overrides": {},
            }
        },
    )
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-26T19:45:00+00:00",
                                "entered": False,
                            },
                            {
                                "evaluated_at": "2026-06-26T20:00:00+00:00",
                                "entered": False,
                            },
                            {
                                "evaluated_at": "2026-06-27T19:45:00+00:00",
                                "entered": False,
                            },
                            {
                                "evaluated_at": "2026-06-29T19:45:00+00:00",
                                "entered": True,
                            },
                        ],
                        "paper_events": [],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard.json",
        ).read_text(encoding="utf-8")
    )
    row = next(
        r for r in payload["shadow_variants"] if r["variant_id"] == "v2_28dte_atm"
    )
    assert row["sessions_evaluated"] == 2
    assert row["entry_evals_total"] == 4
    assert row["weekend_evals_excluded"] == 1
    assert row["entered_sessions"] == 1


def test_run_variant_entry_regime_skip_does_not_write_default_entry_brief(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XSP_LANE_A_PAPER_ENTRY", "true")
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.read_regime_detail", lambda: ("RED", False, None, None)
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_entry.evaluate_ta_signals",
        lambda rules, now_et=None: TaSignal(
            signal="bb_bounce",
            primary=None,
            confirm=None,
            entry_ok=True,
            exit_ok=False,
            upper_bb_touched=False,
            detail="forced test signal",
        ),
    )
    lane_a_entry.DEFAULT_OUT.unlink(missing_ok=True)

    decision = run_variant_entry(
        VariantSpec(
            variant_id="brief_regression",
            description="brief path regression",
            active=True,
            overrides={},
        ),
        root_state={"variants": {}},
        state_path=tmp_path / "variants-state.json",
        now_et=datetime(2026, 6, 16, 19, 47, tzinfo=timezone.utc),
        force=True,
    )

    assert decision.entered is False
    assert decision.skip_reason == "regime RED blocks new risk"
    assert lane_a_entry.DEFAULT_OUT.exists() is False


def test_build_scoreboard_sets_liveness_from_latest_entry_eval(tmp_path):
    recent_variant_eval = (
        (datetime.now(timezone.utc) - timedelta(hours=4))
        .replace(microsecond=0)
        .isoformat()
    )
    recent_baseline_eval = (
        (datetime.now(timezone.utc) - timedelta(hours=2))
        .replace(microsecond=0)
        .isoformat()
    )
    backdated_eval = "2026-06-20T23:55:00+00:00"

    state = tmp_path / "variants-state.json"
    baseline = tmp_path / "baseline-state.json"

    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "entry_log": [
                            {"evaluated_at": recent_variant_eval, "entered": False}
                        ],
                        "paper_events": [],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "entry_log": [{"evaluated_at": recent_baseline_eval, "entered": True}],
                "paper_events": [],
                "paper_positions": {},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        build_scoreboard(
            state_path=state,
            baseline_state_path=baseline,
            out_path=tmp_path / "scoreboard-recent.json",
        ).read_text(encoding="utf-8")
    )
    assert payload["last_entry_eval_at"] == recent_baseline_eval
    assert payload["stale"] is False

    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "entry_log": [
                            {"evaluated_at": backdated_eval, "entered": False}
                        ],
                        "paper_events": [],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "entry_log": [{"evaluated_at": backdated_eval, "entered": False}],
                "paper_events": [],
                "paper_positions": {},
            }
        ),
        encoding="utf-8",
    )

    stale_payload = json.loads(
        build_scoreboard(
            state_path=state,
            baseline_state_path=baseline,
            out_path=tmp_path / "scoreboard-stale.json",
        ).read_text(encoding="utf-8")
    )
    assert stale_payload["last_entry_eval_at"] == backdated_eval
    assert stale_payload["stale"] is True


def test_build_scoreboard_includes_open_mtm_and_contract_clusters(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_28dte_atm": {
                "active": True,
                "description": "open mtm test",
                "overrides": {},
            }
        },
    )
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-26T19:45:00+00:00",
                                "entered": True,
                            }
                        ],
                        "paper_events": [],
                        "paper_positions": {
                            "paper:XSP:2026-07-18:6010": {
                                "position_id": "paper:XSP:2026-07-18:6010",
                                "chain_symbol": "XSP",
                                "option_type": "call",
                                "strike": 6010.0,
                                "expiration_date": "2026-07-18",
                                "quantity": 1,
                                "average_price": 20.0,
                                "entry_mid_premium": 20.0,
                                "mark_price": 21.0,
                                "status": "open",
                            }
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard-open.json",
        ).read_text(encoding="utf-8")
    )
    row = next(
        r for r in payload["shadow_variants"] if r["variant_id"] == "v2_28dte_atm"
    )
    assert row["open_positions"] == 1
    assert row["open_positions_mtm_usd"] == 74.7
    assert row["open_positions_mtm_usd_1x"] == 7.47
    assert row["contract_cluster_id"] == "XSP:call:2026-07-18:6010"
    assert (
        payload["contract_clusters"]["XSP:call:2026-07-18:6010"]["open_positions"] == 1
    )


def test_build_scoreboard_exit_shadow_summary(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_28dte_atm": {
                "active": True,
                "description": "exit shadow test",
                "overrides": {},
            }
        },
    )
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "entry_log": [],
                        "paper_events": [],
                        "paper_shadow_events": [
                            {
                                "evaluated_at": "2026-07-01T14:00:00+00:00",
                                "brackets": [
                                    {
                                        "bracket_id": "prod",
                                        "label": "Production rules (active)",
                                        "would_exit": True,
                                        "exit_reason": "time_stop",
                                    },
                                    {
                                        "bracket_id": "no_morning_cut_14dte",
                                        "label": "Suppress morning time_stop for DTE≥14",
                                        "would_exit": False,
                                        "exit_reason": None,
                                    },
                                ],
                            },
                            {
                                "event_type": "virtual_hold_closed",
                                "evaluated_at": "2026-07-02T14:00:00+00:00",
                                "bracket_id": "no_morning_cut_14dte",
                                "label": "Suppress morning time_stop for DTE≥14",
                                "exit_reason": "take_profit",
                                "paper_pnl_usd": 42.5,
                            },
                        ],
                        "shadow_virtual_holds": [
                            {
                                "virtual_hold_id": "vh-1",
                                "bracket_id": "no_morning_cut_14dte",
                                "label": "Suppress morning time_stop for DTE≥14",
                                "status": "open",
                            }
                        ],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard-shadow.json",
        ).read_text(encoding="utf-8")
    )
    row = next(
        r for r in payload["shadow_variants"] if r["variant_id"] == "v2_28dte_atm"
    )
    assert row["exit_shadow"]["events_evaluated"] == 2
    assert row["exit_shadow"]["brackets"]["prod"]["would_exit"] == 1
    assert row["exit_shadow"]["brackets"]["no_morning_cut_14dte"]["would_hold"] == 1
    assert (
        row["exit_shadow"]["brackets"]["no_morning_cut_14dte"]["would_hold_open"] == 1
    )
    assert (
        row["exit_shadow"]["brackets"]["no_morning_cut_14dte"][
            "would_hold_realized_pnl_usd"
        ]
        == 42.5
    )


def test_build_scoreboard_excludes_holiday_sessions(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_28dte_atm": {
                "active": True,
                "description": "holiday filter",
                "overrides": {},
            }
        },
    )
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "entry_log": [
                            {
                                "evaluated_at": "2026-07-03T19:45:00+00:00",
                                "entered": False,
                            },
                            {
                                "evaluated_at": "2026-07-06T19:45:00+00:00",
                                "entered": True,
                            },
                        ],
                        "paper_events": [],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard-holiday.json",
        ).read_text(encoding="utf-8")
    )
    row = next(
        r for r in payload["shadow_variants"] if r["variant_id"] == "v2_28dte_atm"
    )
    assert row["sessions_evaluated"] == 1
    assert row["weekend_evals_excluded"] == 1


def test_build_scoreboard_ranking_reliable_only_after_multi_variant_samples(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_alpha": {
                "active": True,
                "description": "alpha",
                "overrides": {},
            },
            "v2_beta": {
                "active": True,
                "description": "beta",
                "overrides": {},
            },
        },
    )
    weekday_sessions = [
        f"2026-06-{day:02d}T19:45:00+00:00"
        for day in range(1, 29)
        if datetime(2026, 6, day, tzinfo=timezone.utc).weekday() < 5
    ][:20]
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_alpha": {
                        "entry_log": [
                            {"evaluated_at": ts, "entered": True}
                            for ts in weekday_sessions
                        ],
                        "paper_events": [{"paper_pnl_usd": 12.0} for _ in range(20)],
                        "paper_positions": {},
                    },
                    "v2_beta": {
                        "entry_log": [
                            {"evaluated_at": ts, "entered": True}
                            for ts in weekday_sessions
                        ],
                        "paper_events": [{"paper_pnl_usd": 9.0} for _ in range(20)],
                        "paper_positions": {},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard-ranked.json",
        ).read_text(encoding="utf-8")
    )
    assert payload["ranking_reliable"] is True
    assert [row["variant_id"] for row in payload["shadow_variants"]] == [
        "v2_alpha",
        "v2_beta",
    ]
    assert payload["shadow_variants"][0]["low_sample"] is False


def test_reset_soak_archives_and_clears(tmp_path, monkeypatch):
    state = tmp_path / "variants-state.json"
    baseline = tmp_path / "baseline-state.json"
    scoreboard = tmp_path / "scoreboard.json"
    archive = tmp_path / "archive"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "paper_events": [
                            {
                                "paper_pnl_usd": -1.0,
                                "evaluated_at": "2026-06-20T14:00:00+00:00",
                            }
                        ],
                        "entry_log": [{"entered": True}],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps({"paper_events": [{"paper_pnl_usd": -2.0}], "paper_positions": {}}),
        encoding="utf-8",
    )
    scoreboard.write_text('{"variants": []}\n', encoding="utf-8")

    monkeypatch.setattr(
        "xsp_killer.lane_a_variants.load_variant_specs",
        lambda _path=None: [],
    )

    meta = reset_soak(
        commit="abc1234",
        state_path=state,
        baseline_state_path=baseline,
        scoreboard_path=scoreboard,
        archive_dir=archive,
    )
    root = json.loads(state.read_text(encoding="utf-8"))
    base = json.loads(baseline.read_text(encoding="utf-8"))
    assert root["variants"]["v2_28dte_atm"]["paper_events"] == []
    assert root["variants"]["v2_28dte_atm"]["entry_log"] == []
    assert base["paper_events"] == []
    assert meta["soak_reset_commit"] == "abc1234"
    assert len(list(archive.glob("*pre-reset*"))) >= 2


def test_clear_pnl_keeps_entry_log(tmp_path, monkeypatch):
    state = tmp_path / "variants-state.json"
    baseline = tmp_path / "baseline-state.json"
    scoreboard = tmp_path / "scoreboard.json"
    archive = tmp_path / "archive"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "paper_events": [
                            {
                                "paper_pnl_usd": -100.0,
                                "evaluated_at": "2026-06-23T14:00:00+00:00",
                            }
                        ],
                        "entry_log": [{"entered": True}],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps({"paper_events": [{"paper_pnl_usd": -50.0}], "paper_positions": {}}),
        encoding="utf-8",
    )
    scoreboard.write_text('{"variants": []}\n', encoding="utf-8")
    monkeypatch.setattr(
        "xsp_killer.lane_a_variants.load_variant_specs", lambda _path=None: []
    )

    meta = clear_pnl_epoch(
        commit="abc",
        state_path=state,
        baseline_state_path=baseline,
        scoreboard_path=scoreboard,
        archive_dir=archive,
    )
    root = json.loads(state.read_text(encoding="utf-8"))
    assert root["variants"]["v2_28dte_atm"]["paper_events"] == []
    assert root["variants"]["v2_28dte_atm"]["entry_log"] == [{"entered": True}]
    assert meta["pnl_epoch_commit"] == "abc"
    sb = json.loads(scoreboard.read_text(encoding="utf-8"))
    row = sb["shadow_variants"][0]
    assert row["variant_id"] == "v2_28dte_atm"
    assert row["trades_closed"] == 0
    assert row["realized_pnl_usd"] == 0.0
    assert sb["baseline_prod"]["trades_closed"] == 0


def test_resync_epoch_briefs_restores_parity(tmp_path, monkeypatch):
    state = tmp_path / "variants-state.json"
    baseline = tmp_path / "baseline-state.json"
    scoreboard = tmp_path / "scoreboard.json"
    canonical_epoch = "2026-06-23T22:20:36+00:00"
    state.write_text(
        json.dumps(
            {
                "pnl_epoch_at": canonical_epoch,
                "variants": {
                    "v2_28dte_atm": {
                        "paper_events": [],
                        "entry_log": [],
                        "paper_positions": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "pnl_epoch_at": "2026-07-01T23:11:03+00:00",
                "paper_events": [
                    {
                        "paper_pnl_usd": -12.5,
                        "evaluated_at": "2026-06-24T14:00:00+00:00",
                    }
                ],
                "entry_log": [
                    {
                        "evaluated_at": "2026-06-24T19:45:00+00:00",
                        "entered": False,
                        "skip_reason": "regime gate",
                        "regime": "YELLOW",
                    }
                ],
                "paper_positions": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_variants.load_variant_specs",
        lambda _path=None: [
            VariantSpec(
                variant_id="v2_28dte_atm",
                description="Epoch sync test",
                active=True,
                overrides={},
            )
        ],
    )

    meta = resync_epoch_briefs(
        state_path=state,
        baseline_state_path=baseline,
        scoreboard_path=scoreboard,
    )

    telemetry = json.loads(
        (tmp_path / "xsp-lane-a-entry-telemetry-latest.json").read_text(
            encoding="utf-8"
        )
    )
    paper = json.loads(
        (tmp_path / "xsp-lane-a-paper-pnl-latest.json").read_text(encoding="utf-8")
    )
    refreshed_baseline = json.loads(baseline.read_text(encoding="utf-8"))
    payload = json.loads(scoreboard.read_text(encoding="utf-8"))

    assert meta["pnl_epoch_at"] == canonical_epoch
    assert refreshed_baseline["pnl_epoch_at"] == canonical_epoch
    assert telemetry["pnl_epoch_at"] == canonical_epoch
    assert paper["pnl_epoch_at"] == canonical_epoch
    assert payload["pnl_epoch_at"] == canonical_epoch
    assert payload["baseline_prod"]["realized_pnl_usd"] == -12.5
    assert payload["baseline_prod"]["sessions_evaluated"] == 1
    assert payload["active_variant_ids"] == ["v2_28dte_atm"]


def test_resync_epoch_briefs_if_needed_skips_when_parity_ok(tmp_path, monkeypatch):
    state = tmp_path / "variants-state.json"
    baseline = tmp_path / "baseline-state.json"
    scoreboard = tmp_path / "scoreboard.json"
    epoch = "2026-06-23T22:20:36+00:00"
    state.write_text(
        json.dumps({"pnl_epoch_at": epoch, "variants": {"v2_28dte_atm": {}}}),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps({"pnl_epoch_at": epoch, "paper_events": [], "entry_log": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "xsp_killer.lane_a_variants.load_variant_specs",
        lambda _path=None: [
            VariantSpec(
                variant_id="v2_28dte_atm",
                description="sync-if-needed",
                active=True,
                overrides={},
            )
        ],
    )
    meta = resync_epoch_briefs_if_needed(
        state_path=state,
        baseline_state_path=baseline,
        scoreboard_path=scoreboard,
    )
    assert meta["synced"] is False
    assert meta["reason"] == "parity_ok"


def test_build_scoreboard_regime_gate_comparison(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_yellow_mid_bounce": {
                "active": True,
                "description": "Mid bounce test",
                "overrides": {
                    "logging": {"logic_version": "xsp_lane_a_v2_yellow_mid_bounce"},
                    "entry": {
                        "regime_gate": "GREEN_OR_YELLOW_BOUNCE",
                        "regime_yellow_frac_min": 0.50,
                    },
                },
            },
            "v2_yellow_top_quartile_bounce": {
                "active": True,
                "description": "Top quartile bounce test",
                "overrides": {
                    "logging": {
                        "logic_version": "xsp_lane_a_v2_yellow_top_quartile_bounce"
                    },
                    "entry": {
                        "regime_gate": "GREEN_OR_YELLOW_BOUNCE",
                        "regime_yellow_frac_min": 0.75,
                    },
                },
            },
        },
    )
    state = tmp_path / "variants-state.json"
    baseline = tmp_path / "baseline-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_yellow_mid_bounce": {
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-26T19:45:00+00:00",
                                "entered": False,
                                "skip_reason": "regime YELLOW blocks new risk: yellow_frac 0.40 < 0.50",
                                "regime": "YELLOW",
                                "regime_frac": 0.4,
                                "regime_gate": "GREEN_OR_YELLOW_BOUNCE",
                                "bb_entry_ok": True,
                            }
                        ],
                        "paper_events": [],
                        "paper_positions": {},
                    },
                    "v2_yellow_top_quartile_bounce": {
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-26T19:45:00+00:00",
                                "entered": False,
                                "skip_reason": "regime YELLOW blocks new risk: yellow_frac 0.40 < 0.75",
                                "regime": "YELLOW",
                                "regime_frac": 0.4,
                                "regime_gate": "GREEN_OR_YELLOW_BOUNCE",
                                "bb_entry_ok": True,
                            }
                        ],
                        "paper_events": [],
                        "paper_positions": {},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "entry_log": [
                    {
                        "evaluated_at": "2026-06-26T19:45:00+00:00",
                        "entered": False,
                        "skip_reason": "regime YELLOW blocks new risk",
                        "regime": "YELLOW",
                        "regime_gate": "GREEN",
                        "bb_entry_ok": True,
                    }
                ],
                "paper_events": [],
                "paper_positions": {},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=baseline,
            out_path=tmp_path / "scoreboard.json",
        ).read_text(encoding="utf-8")
    )

    mid = next(
        r
        for r in payload["shadow_variants"]
        if r["variant_id"] == "v2_yellow_mid_bounce"
    )
    top = next(
        r
        for r in payload["shadow_variants"]
        if r["variant_id"] == "v2_yellow_top_quartile_bounce"
    )
    assert mid["track_family"] == "yellow_bounce_frac_axis"
    assert mid["regime_yellow_frac_min"] == 0.50
    assert top["regime_yellow_frac_min"] == 0.75
    assert mid["bb_bounce_signal_sessions"] == 1
    assert mid["bb_bounce_blocked_by_regime_sessions"] == 1
    assert payload["baseline_prod"]["track_family"] == "baseline_green"
    assert payload["baseline_prod"]["regime_gate"] == "GREEN"

    comparison = payload["regime_gate_comparison"]
    assert comparison["baseline_variant_id"] == "v2_baseline_prod"
    assert [v["variant_id"] for v in comparison["variants"]] == [
        "v2_baseline_prod",
        "v2_yellow_mid_bounce",
        "v2_yellow_top_quartile_bounce",
    ]
    assert comparison["variants"][1]["regime_yellow_frac_min"] == 0.50
    assert comparison["variants"][2]["regime_yellow_frac_min"] == 0.75


def test_build_scoreboard_vol_shadow_stats(tmp_path):
    _write_variants_config(tmp_path, {})
    state = tmp_path / "variants-state.json"
    baseline = tmp_path / "baseline-state.json"
    state.write_text(
        json.dumps({"variants": {}}),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "entry_log": [
                    {
                        "evaluated_at": "2026-06-26T19:45:00+00:00",
                        "entered": False,
                        "skip_reason": "regime YELLOW blocks new risk",
                        "vol_shadow": {
                            "spy_rv_annualized": 0.22,
                            "shadow_would_block": False,
                            "reason": "spy_rv_22.00%_below_threshold_28.00%",
                        },
                    },
                    {
                        "evaluated_at": "2026-06-27T19:45:00+00:00",
                        "entered": False,
                        "skip_reason": "regime YELLOW blocks new risk",
                        "spy_rv_annualized": 0.31,
                        "vol_shadow_would_block": True,
                        "vol_shadow_reason": "spy_rv_31.00%_gte_threshold_28.00%",
                    },
                ],
                "paper_events": [],
                "paper_positions": {},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=baseline,
            out_path=tmp_path / "scoreboard.json",
        ).read_text(encoding="utf-8")
    )

    baseline_row = payload["baseline_prod"]
    assert baseline_row["vol_shadow_would_block_sessions"] == 1
    assert baseline_row["vol_shadow_latest_spy_rv"] == 0.31
    assert baseline_row["vol_shadow_latest_would_block"] is True
    assert baseline_row["vol_shadow_avg_spy_rv"] == 0.265

    comparison = payload["regime_gate_comparison"]["variants"][0]
    assert comparison["vol_shadow_would_block_sessions"] == 1
    assert comparison["vol_shadow_avg_spy_rv"] == 0.265


def test_promotion_meta_collecting():
    from xsp_killer.lane_a_variants import _promotion_meta

    meta = _promotion_meta(9, 0, 0)
    assert meta["promotion_status"] == "collecting"
    assert meta["sessions_to_promotion_gate"] == 11
    assert meta["entered_sessions_to_promotion_gate"] == 10
    assert meta["promotion_ready"] is False


def test_promotion_meta_insufficient_enters():
    from xsp_killer.lane_a_variants import _promotion_meta

    meta = _promotion_meta(21, 0, 1)
    assert meta["promotion_status"] == "insufficient_enters"
    assert meta["sessions_to_promotion_gate"] == 0
    assert meta["entered_sessions_to_promotion_gate"] == 9
    assert meta["promotion_ready"] is False


def test_promotion_meta_sessions_met_no_trades():
    from xsp_killer.lane_a_variants import _promotion_meta

    meta = _promotion_meta(20, 0, 10)
    assert meta["promotion_status"] == "sessions_met_no_trades"
    assert meta["promotion_ready"] is False


def test_promotion_meta_eligible_review():
    from xsp_killer.lane_a_variants import _promotion_meta

    meta = _promotion_meta(20, 2, 10)
    assert meta["promotion_status"] == "eligible_review"
    assert meta["promotion_ready"] is True


def test_collapse_confounded_clones_in_promotion_summary():
    rows = [
        {
            "variant_id": "v2_28dte_atm",
            "promotion_ready": True,
            "edge_confirmed": False,
            "promotion_status": "eligible_review",
            "trades_closed": 5,
            "realized_pnl_usd": 10.0,
            "wins": 3,
            "losses": 2,
            "win_rate_pct": 60.0,
        },
        {
            "variant_id": "v2_28dte_cheapest",
            "promotion_ready": True,
            "edge_confirmed": False,
            "promotion_status": "eligible_review",
            "trades_closed": 5,
            "realized_pnl_usd": 10.0,
            "wins": 3,
            "losses": 2,
            "win_rate_pct": 60.0,
        },
        {
            "variant_id": "v2_dip_swing_14dte",
            "promotion_ready": True,
            "edge_confirmed": True,
            "promotion_status": "eligible_review",
            "trades_closed": 8,
            "realized_pnl_usd": 40.0,
            "wins": 5,
            "losses": 3,
            "win_rate_pct": 62.5,
        },
    ]
    collapse = _collapse_confounded_clones(rows)
    assert "v2_28dte_cheapest" in collapse["confounded_variant_ids"]
    summary = _build_promotion_summary(rows)
    assert "v2_28dte_atm" in summary["variants_eligible_review"]
    assert "v2_28dte_cheapest" not in summary["variants_eligible_review"]
    assert "v2_28dte_cheapest" in summary["variants_eligible_review_raw"]
    assert "v2_dip_swing_14dte" in summary["variants_eligible_review"]
    assert any(f.get("family_id") == "28dte_atm_book" for f in summary["clone_families"])


def test_build_scoreboard_includes_promotion_summary(tmp_path):
    _write_variants_config(
        tmp_path,
        {
            "v2_28dte_atm": {
                "active": True,
                "description": "promo test",
                "overrides": {},
            }
        },
    )
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_28dte_atm": {
                        "entry_log": [
                            {
                                "evaluated_at": "2026-06-21T19:45:00+00:00",
                                "entered": False,
                            }
                        ],
                        "paper_events": [],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard.json",
        ).read_text(encoding="utf-8")
    )
    assert payload["promotion_summary"]["sessions_gate"] == 20
    assert payload["promotion_summary"]["entered_sessions_gate"] == 10
    row = payload["shadow_variants"][0]
    assert row["promotion_status"] == "collecting"
    assert "regime_skip_breakdown" in payload
    assert "v2_28dte_atm" in payload["regime_skip_breakdown"]["variants"]


def test_dip_swing_variant_is_intraday_enabled():
    from xsp_killer.lane_a_variants import _variant_intraday_enabled

    specs = {s.variant_id: s for s in load_variant_specs()}
    assert "v2_dip_swing_14dte" in specs
    # The dip-swing variant opts into intraday evaluation...
    assert _variant_intraday_enabled(specs["v2_dip_swing_14dte"]) is True
    # ...while a close-window variant does not (stays on the 15:45 cadence).
    assert _variant_intraday_enabled(specs["v2_28dte_atm"]) is False


def test_dip_swing_cluster_isolates_and_ranks():
    from xsp_killer.lane_a_variants import _build_dip_swing_cluster

    rows = [
        {
            "variant_id": "v2_close_window_baseline",
            "avg_pnl_per_trade_usd": 5.0,
            "trades_closed": 10,
            "sessions_evaluated": 22,
            "low_sample": False,
        },
        {
            "variant_id": "v2_dip_swing_14dte",
            "avg_pnl_per_trade_usd": 12.0,
            "trades_closed": 25,
            "sessions_evaluated": 22,
            "low_sample": False,
            "edge_confirmed": True,
        },
        {
            "variant_id": "v2_dip_swing_21dte",
            "avg_pnl_per_trade_usd": 30.0,
            "trades_closed": 1,
            "sessions_evaluated": 22,
            "low_sample": True,
            "edge_confirmed": False,
        },
        {
            "variant_id": "v2_dip_swing_30dte",
            "avg_pnl_per_trade_usd": 3.0,
            "trades_closed": 22,
            "sessions_evaluated": 22,
            "low_sample": False,
            # sample gate cleared but no statistical separation -> not a leader.
            "edge_confirmed": False,
        },
    ]
    cluster = _build_dip_swing_cluster(rows)
    ids = [v["variant_id"] for v in cluster["variants"]]
    # Only dip-swing members, close-window variant excluded.
    assert ids == ["v2_dip_swing_21dte", "v2_dip_swing_14dte", "v2_dip_swing_30dte"]
    assert cluster["count"] == 3
    assert cluster["total_trades_closed"] == 48
    # Leader needs statistical separation (edge_confirmed): the high-avg 21dte is
    # low_sample and 30dte lacks a confirmed edge, so 14dte wins.
    assert cluster["leader"] == "v2_dip_swing_14dte"
    assert "edge_confirmed=true" in cluster["leader_gate"]


def test_wilson_lower_bound_is_small_n_honest():
    from xsp_killer.lane_a_variants import wilson_lower_bound

    assert wilson_lower_bound(0, 0) is None
    # A perfect but tiny record is heavily discounted.
    lb_5 = wilson_lower_bound(5, 5)
    lb_20 = wilson_lower_bound(20, 20)
    assert lb_5 is not None and lb_20 is not None
    assert 0.0 <= lb_5 < lb_20 <= 1.0
    # More wins at fixed n raises the bound; it never exceeds the point estimate.
    assert wilson_lower_bound(15, 20) < wilson_lower_bound(18, 20) <= 18 / 20


def test_variant_breakeven_win_rate_from_tp_sl(tmp_path):
    from xsp_killer.lane_a_variants import _variant_breakeven_win_rate

    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "exit:\n  take_profit_pct: 0.40\n  stop_loss_pct: 0.50\n",
        encoding="utf-8",
    )
    be = _variant_breakeven_win_rate(rules)
    assert be is not None
    assert round(be, 4) == round(0.50 / 0.90, 4)
    missing = tmp_path / "no_exit.yaml"
    missing.write_text("entry: {}\n", encoding="utf-8")
    assert _variant_breakeven_win_rate(missing) is None


def test_dip_swing_cluster_leader_none_without_reliable_sample():
    from xsp_killer.lane_a_variants import _build_dip_swing_cluster

    rows = [
        {
            "variant_id": "v2_dip_swing_14dte",
            "avg_pnl_per_trade_usd": None,
            "trades_closed": 5,
            "sessions_evaluated": 22,
            "low_sample": True,
        },
    ]
    cluster = _build_dip_swing_cluster(rows)
    assert cluster["count"] == 1
    assert cluster["leader"] is None


def test_dip_swing_cluster_leader_none_when_sessions_met_but_trades_under_gate(
    tmp_path,
):
    """A dip-swing member with >=20 sessions but <20 trades is low_sample and
    yields leader=None end-to-end through build_scoreboard."""
    _write_variants_config(
        tmp_path,
        {
            "v2_dip_swing_14dte": {
                "active": True,
                "description": "dip-swing sessions-met trades-short",
                "overrides": {},
            }
        },
    )
    weekday_sessions = [
        f"2026-06-{day:02d}T19:45:00+00:00"
        for day in range(1, 29)
        if datetime(2026, 6, day, tzinfo=timezone.utc).weekday() < 5
    ][:22]
    state = tmp_path / "variants-state.json"
    state.write_text(
        json.dumps(
            {
                "variants": {
                    "v2_dip_swing_14dte": {
                        "entry_log": [
                            {"evaluated_at": ts, "entered": True}
                            for ts in weekday_sessions
                        ],
                        "paper_events": [
                            {"paper_pnl_usd": 10.0},
                            {"paper_pnl_usd": -5.0},
                            {"paper_pnl_usd": 8.0},
                            {"paper_pnl_usd": -3.0},
                            {"paper_pnl_usd": 6.0},
                        ],
                        "paper_positions": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(
        build_scoreboard(
            config_path=tmp_path / "lane_a_variants.yaml",
            state_path=state,
            baseline_state_path=tmp_path / "missing-baseline.json",
            out_path=tmp_path / "scoreboard-dip-swing.json",
        ).read_text(encoding="utf-8")
    )
    row = next(
        r for r in payload["shadow_variants"] if r["variant_id"] == "v2_dip_swing_14dte"
    )
    assert row["sessions_evaluated"] == 20
    assert row["trades_closed"] == 5
    # >=20 sessions but <20 trades -> still low_sample under the tightened gate.
    assert row["low_sample"] is True
    # Dual-log: real-dollar (1x) approximation = paper_$ / premium_scale.
    scale = row["premium_scale"]
    assert scale and scale > 0
    assert row["realized_pnl_usd"] == 16.0
    assert row["realized_pnl_usd_1x_approx"] == round(16.0 / scale, 2)
    assert row["avg_pnl_per_trade_usd_1x_approx"] == round(
        row["avg_pnl_per_trade_usd"] / scale, 2
    )
    # Statistical-separation fields are present; low-sample => no confirmed edge.
    assert row["edge_confirmed"] is False
    assert row["win_rate_wilson_lb_pct"] is not None
    assert row["breakeven_win_rate_pct"] is not None
    cluster = payload["dip_swing_cluster"]
    assert cluster["count"] == 1
    assert cluster["leader"] is None
    assert "edge_confirmed=true" in cluster["leader_gate"]
    assert "realized_pnl_usd_1x_approx" in cluster["variants"][0]
    assert "edge_confirmed" in cluster["variants"][0]


def test_opt_candidate_is_inactive():
    from xsp_killer.backtest.variants import resolve_variant_specs

    all_specs = resolve_variant_specs(variants="all")
    candidate = next(
        s for s in all_specs if s.variant_id == "opt_dte28_tp20_sl30_gyb"
    )
    assert candidate.active is False
    active_ids = {
        s.variant_id for s in resolve_variant_specs(variants="active")
    }
    assert "opt_dte28_tp20_sl30_gyb" not in active_ids

    # Lock approved candidate overrides (UW optimizer leader; soak-inactive).
    ov = candidate.overrides
    assert ov["logging"]["logic_version"] == "xsp_lane_a_opt_dte28_tp20_sl30_gyb"
    entry = ov["entry"]
    assert entry["dte_pick"] == "target"
    assert entry["dte_target"] == 28
    assert entry["strike_pick"] == "atm_only"
    assert entry["regime_gate"] == "GREEN_OR_YELLOW_BOUNCE"
    assert entry["regime_yellow_frac_min"] == 0.50
    assert entry["regime_yellow_require_bounce"] is False
    assert entry["prior_day_spy_positive"] is False
    ta_entry = ov["ta"]["entry"]
    assert ta_entry["mode"] == "close_window_only"
    assert ta_entry["intraday_enabled"] is False
    assert ta_entry["require_vwap_reclaim"] is False
    exit_cfg = ov["exit"]
    assert exit_cfg["take_profit_pct"] == 0.20
    assert exit_cfg["stop_loss_pct"] == 0.30
    assert exit_cfg["require_upper_bb_for_take_profit"] is False
    assert exit_cfg["swing_hold"] is False
    assert exit_cfg["max_hold_dte"] == 0
