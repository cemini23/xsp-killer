"""Tests for K155 macro weather operator notes."""

from __future__ import annotations

from pathlib import Path

import yaml

from xsp_killer.macro_weather_notes import (
    USDJPY_ZONE,
    build_macro_weather_extras,
    build_monitor_macro_weather_extras,
    conviction_journal_fields,
    load_glitch_falcon_notes,
    load_k155_notes,
    load_k158_notes,
    load_k161_notes,
    load_k162_notes,
    load_k167_notes,
    load_k170_notes,
    load_k172_notes,
    load_k173_notes,
    load_k174_notes,
    load_k177_notes,
    load_k178_notes,
    load_k182_notes,
    load_k191_notes,
    load_k193_notes,
    load_k195_notes,
    load_k196_notes,
    load_k198_notes,
    load_k213_notes,
    load_k214_notes,
    load_k215_notes,
    load_k219_notes,
    load_k221_notes,
    load_k222_notes,
    load_k223_notes,
    load_k224_notes,
    load_k225_notes,
    load_k226_notes,
    load_k228_notes,
    load_k229_notes,
)


def test_usdjpy_zone_constants():
    assert USDJPY_ZONE == (162.25, 162.50)


def test_build_macro_weather_extras_in_zone():
    extras = build_macro_weather_extras(
        usdjpy=162.35,
        sofr_curve_note="SOFR anchor",
        event_cluster="July FOMC / CPI cluster",
    )
    assert extras["usdjpy_in_zone"] is True
    assert extras["usdjpy_zone_lo"] == 162.25
    assert extras["sofr_curve_note"] == "SOFR anchor"


def test_build_macro_weather_extras_outside_zone():
    extras = build_macro_weather_extras(
        usdjpy=160.0,
        sofr_curve_note=None,
        event_cluster=None,
    )
    assert extras["usdjpy_in_zone"] is False


def test_conviction_journal_blocks_size_up_on_balanced_pro_con():
    blocked = conviction_journal_fields(
        evidence_count=1,
        cross_asset_confirms=0,
        pro_con_balanced=True,
    )
    assert blocked["block_size_up"] is True
    assert blocked["conviction_sufficient"] is False

    allowed = conviction_journal_fields(
        evidence_count=2,
        cross_asset_confirms=1,
        pro_con_balanced=True,
    )
    assert allowed["block_size_up"] is False
    assert allowed["conviction_sufficient"] is True


def test_conviction_journal_no_block_when_not_balanced():
    fields = conviction_journal_fields(
        evidence_count=0,
        cross_asset_confirms=0,
        pro_con_balanced=False,
    )
    assert fields["block_size_up"] is False


def test_load_k155_notes_from_yaml(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "test",
                    "event_cluster": "CPI cluster",
                    "sofr_curve": {"note": "anchor"},
                }
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    assert notes["version"] == "test"
    assert notes["sofr_curve"]["note"] == "anchor"


def test_build_monitor_macro_weather_extras_merges_k155(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                    "events": {"cpi": {"date": "2026-07-15"}},
                    "cme_ssf": {"date": "2026-07-27"},
                }
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(notes, usdjpy=162.40)
    assert extras is not None
    assert extras["usdjpy_in_zone"] is True
    assert extras["events"]["cpi"]["date"] == "2026-07-15"
    assert extras["cme_ssf"]["date"] == "2026-07-27"


def test_load_k155_notes_prod_config():
    notes = load_k155_notes()
    assert notes.get("version") == "2026-07-10"
    assert notes["events"]["cpi"]["date"] == "2026-07-15"
    assert notes["events"]["cpi"]["overnight_posture"] == "halve_or_block"
    assert notes["cme_ssf"]["date"] == "2026-07-27"
    assert notes["cme_ssf"]["tickers"] == ["NVDA", "MSFT", "ORCL", "PLTR"]
    assert notes["macro_weather_snapshot"]["yen_strength_narrative"] == "GPIF_domestic"
    assert "conviction_journal" in notes
    assert "vol_edge" in notes


def test_load_k158_notes_prod_config():
    notes = load_k158_notes()
    assert notes.get("version") == "2026-07-11"
    assert "Z6/Z7" in notes["sofr_front_end"]["journal_spreads"]
    assert "Z6/Z8" in notes["sofr_front_end"]["journal_spreads"]
    assert notes["fomc_jul29"]["date"] == "2026-07-29"
    assert notes["fomc_jul29"]["catalyst_type"] == "binary"
    assert notes["fomc_jul29"]["overnight_posture"] == "tighten"
    assert notes["cpi_skew"]["no_front_run_without"] == "cross_asset_confirms"
    assert notes["japan_yen"]["overlay"] == "negative_real_short_end_funding"


def test_build_monitor_macro_weather_extras_includes_k158(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                    "cme_ssf": {
                        "date": "2026-07-27",
                        "tickers": ["NVDA", "MSFT", "ORCL", "PLTR"],
                    },
                },
                "k158": {
                    "version": "2026-07-11",
                    "sofr_front_end": {
                        "journal_spreads": ["Z6/Z7", "Z6/Z8"],
                    },
                    "fomc_jul29": {
                        "date": "2026-07-29",
                        "catalyst_type": "binary",
                        "overnight_posture": "tighten",
                    },
                    "cpi_skew": {
                        "no_front_run_without": "cross_asset_confirms",
                    },
                    "japan_yen": {
                        "overlay": "negative_real_short_end_funding",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k158_notes=load_k158_notes(cfg),
        notes_path=cfg,
    )
    assert extras is not None
    assert extras["k158_version"] == "2026-07-11"
    assert extras["sofr_front_end"]["journal_spreads"] == ["Z6/Z7", "Z6/Z8"]
    assert extras["fomc_jul29"]["date"] == "2026-07-29"
    assert extras["cpi_skew"]["no_front_run_without"] == "cross_asset_confirms"
    assert extras["japan_yen"]["overlay"] == "negative_real_short_end_funding"
    assert extras["cme_ssf"]["tickers"] == ["NVDA", "MSFT", "ORCL", "PLTR"]


def test_build_monitor_macro_weather_extras_k158_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    assert extras is not None
    assert extras["k158_version"] == "2026-07-11"
    assert "Z6/Z7" in extras["sofr_front_end"]["journal_spreads"]
    assert extras["fomc_jul29"]["overnight_posture"] == "tighten"
    assert extras["cpi_skew"]["skew"] == "disinflation_print_drift_higher"
    assert extras["japan_yen"]["overlay"] == "negative_real_short_end_funding"


def test_load_k161_notes_prod_config():
    notes = load_k161_notes()
    assert notes.get("version") == "2026-07-13"
    cev = notes["cev_aspiration"]
    assert cev["regime_tag_required"] is True
    assert cev["band_thinking_on_positive_drift"] is True
    assert cev["elasticity_widen_bands_when_vol_sensitive"] is True
    assert cev["no_integral_solver"] is True


def test_load_k162_notes_prod_config():
    notes = load_k162_notes()
    assert notes.get("version") == "2026-07-13"
    sc = notes["sentiment_capitulation"]
    assert sc["crowded_semis_risk"] == "elevated"
    assert sc["sox_relative_weakness"] == "watch"
    assert sc["gold_models_turning_up"] == "context_only"
    assert sc["yen_hedge_narrative_only"] is True
    assert sc["no_chase_spmo_semis_into_lane_a_overnight"] is True


def test_build_monitor_macro_weather_extras_includes_k161_k162(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k161": {
                    "version": "2026-07-13",
                    "cev_aspiration": {
                        "regime_tag_required": True,
                        "band_thinking_on_positive_drift": True,
                        "elasticity_widen_bands_when_vol_sensitive": True,
                        "no_integral_solver": True,
                    },
                },
                "k162": {
                    "version": "2026-07-13",
                    "sentiment_capitulation": {
                        "crowded_semis_risk": "elevated",
                        "sox_relative_weakness": "watch",
                        "gold_models_turning_up": "context_only",
                        "yen_hedge_narrative_only": True,
                        "no_chase_spmo_semis_into_lane_a_overnight": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k161_notes=load_k161_notes(cfg),
        k162_notes=load_k162_notes(cfg),
        notes_path=cfg,
    )
    assert extras is not None
    assert extras["k161_version"] == "2026-07-13"
    assert extras["cev_aspiration"]["no_integral_solver"] is True
    assert extras["cev_aspiration"]["band_thinking_on_positive_drift"] is True
    assert extras["k162_version"] == "2026-07-13"
    assert extras["sentiment_capitulation"]["crowded_semis_risk"] == "elevated"
    assert (
        extras["sentiment_capitulation"]["no_chase_spmo_semis_into_lane_a_overnight"]
        is True
    )


def test_build_monitor_macro_weather_extras_k161_k162_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    assert extras is not None
    assert extras["k161_version"] == "2026-07-13"
    assert extras["cev_aspiration"]["no_integral_solver"] is True
    assert extras["cev_aspiration"]["regime_tag_required"] is True
    assert extras["k162_version"] == "2026-07-13"
    assert extras["sentiment_capitulation"]["sox_relative_weakness"] == "watch"
    assert extras["sentiment_capitulation"]["yen_hedge_narrative_only"] is True


def test_load_k167_notes_prod_config():
    notes = load_k167_notes()
    assert notes.get("version") == "2026-07-15"
    assert notes["oil_vs_2yr"]["flag"] == "oil_up_2yr_down_divergence"
    assert notes["oil_vs_2yr"]["overnight_posture"] == "tighten"
    assert notes["sox_mu_bounce"]["no_chase_overnight"] is True
    assert notes["moontower_volga"]["no_auto_structure"] is True
    assert notes["moontower_volga"]["lane"] == "B"
    assert notes["software_igv"]["context_only"] is True
    assert "soft_cpi" in notes


def test_build_monitor_macro_weather_extras_includes_k167(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k167": {
                    "version": "2026-07-15",
                    "oil_vs_2yr": {
                        "flag": "oil_up_2yr_down_divergence",
                        "overnight_posture": "tighten",
                    },
                    "sox_mu_bounce": {"no_chase_overnight": True},
                    "soft_cpi": {"note": "soft CPI context"},
                    "moontower_volga": {
                        "lane": "B",
                        "no_auto_structure": True,
                    },
                    "software_igv": {"context_only": True},
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k167_notes=load_k167_notes(cfg),
        notes_path=cfg,
    )
    assert extras is not None
    assert extras["k167_version"] == "2026-07-15"
    assert extras["oil_vs_2yr"]["flag"] == "oil_up_2yr_down_divergence"
    assert extras["sox_mu_bounce"]["no_chase_overnight"] is True
    assert extras["moontower_volga"]["no_auto_structure"] is True
    assert extras["software_igv"]["context_only"] is True


def test_build_monitor_macro_weather_extras_k167_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    assert extras is not None
    assert extras["k167_version"] == "2026-07-15"
    assert extras["oil_vs_2yr"]["overnight_posture"] == "tighten"
    assert extras["moontower_volga"]["no_auto_structure"] is True
    assert extras["sox_mu_bounce"]["no_chase_overnight"] is True


def test_load_k170_notes_prod_config():
    notes = load_k170_notes()
    assert notes.get("version") == "2026-07-16"
    assert notes["korea_memory_semis"]["overnight_posture"] == "conditional"
    assert notes["sox_support"]["level"] == 12000
    assert notes["dxy_breakdown"]["flag"] == "may_uptrend_break_test"
    assert notes["dxy_breakdown"]["level"] == 100.50
    assert notes["dxy_breakdown"]["overnight_posture"] == "tighten"
    assert notes["us_reindustrialization"]["no_new_rh_sleeve"] is True
    assert notes["us_reindustrialization"]["context_only"] is True
    assert notes["theory_shelf"]["no_integral_solver"] is True
    assert notes["turbovec"]["no_prod_index_swap"] is True


def test_build_monitor_macro_weather_extras_includes_k170(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k170": {
                    "version": "2026-07-16",
                    "korea_memory_semis": {"overnight_posture": "conditional"},
                    "sox_support": {"level": 12000},
                    "dxy_breakdown": {
                        "flag": "may_uptrend_break_test",
                        "level": 100.50,
                        "overnight_posture": "tighten",
                    },
                    "us_reindustrialization": {
                        "context_only": True,
                        "no_new_rh_sleeve": True,
                    },
                    "theory_shelf": {"no_integral_solver": True},
                    "turbovec": {"no_prod_index_swap": True},
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k170_notes=load_k170_notes(cfg),
        notes_path=cfg,
    )
    assert extras is not None
    assert extras["k170_version"] == "2026-07-16"
    assert extras["korea_memory_semis"]["overnight_posture"] == "conditional"
    assert extras["sox_support"]["level"] == 12000
    assert extras["dxy_breakdown"]["overnight_posture"] == "tighten"
    assert extras["us_reindustrialization"]["no_new_rh_sleeve"] is True
    assert extras["theory_shelf"]["no_integral_solver"] is True
    assert extras["turbovec"]["no_prod_index_swap"] is True


def test_build_monitor_macro_weather_extras_k170_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    assert extras is not None
    assert extras["k170_version"] == "2026-07-16"
    assert extras["korea_memory_semis"]["overnight_posture"] == "conditional"
    assert extras["sox_support"]["level"] == 12000
    assert extras["dxy_breakdown"]["level"] == 100.50
    assert extras["dxy_breakdown"]["overnight_posture"] == "tighten"
    assert extras["us_reindustrialization"]["no_new_rh_sleeve"] is True
    assert extras["theory_shelf"]["no_integral_solver"] is True
    assert extras["turbovec"]["no_prod_index_swap"] is True


def test_load_k172_notes_prod_config():
    notes = load_k172_notes()
    assert notes.get("version") == "2026-07-17"
    assert notes["cf_view_shift"]["flag"] == "momentum_unwind_carry_risks"
    assert notes["cf_view_shift"]["overnight_posture"] == "tighten"
    assert notes["asia_ai_selloff"]["no_chase_memory_semis_overnight"] is True
    assert notes["asia_ai_selloff"]["wait_clear_bounce_rr"] is True
    assert notes["asia_ai_selloff"]["korea_margin_call_chatter"] is True
    assert notes["lane_a_posture"]["keep_tight_vs_k170"] is True
    assert notes["ai_commoditization"]["no_new_rh_sleeve"] is True
    assert notes["ai_commoditization"]["context_only"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k172(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k172": {
                    "version": "2026-07-17",
                    "cf_view_shift": {
                        "flag": "momentum_unwind_carry_risks",
                        "overnight_posture": "tighten",
                    },
                    "asia_ai_selloff": {
                        "no_chase_memory_semis_overnight": True,
                        "wait_clear_bounce_rr": True,
                        "korea_margin_call_chatter": True,
                    },
                    "lane_a_posture": {"keep_tight_vs_k170": True},
                    "ai_commoditization": {
                        "context_only": True,
                        "no_new_rh_sleeve": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k172_notes=load_k172_notes(cfg),
        notes_path=cfg,
    )
    assert extras is not None
    assert extras["k172_version"] == "2026-07-17"
    assert extras["cf_view_shift"]["overnight_posture"] == "tighten"
    assert extras["asia_ai_selloff"]["no_chase_memory_semis_overnight"] is True
    assert extras["lane_a_posture"]["keep_tight_vs_k170"] is True
    assert extras["ai_commoditization"]["no_new_rh_sleeve"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k172_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    assert extras is not None
    assert extras["k172_version"] == "2026-07-17"
    assert extras["cf_view_shift"]["flag"] == "momentum_unwind_carry_risks"
    assert extras["cf_view_shift"]["overnight_posture"] == "tighten"
    assert extras["asia_ai_selloff"]["no_chase_memory_semis_overnight"] is True
    assert extras["asia_ai_selloff"]["wait_clear_bounce_rr"] is True
    assert extras["lane_a_posture"]["keep_tight_vs_k170"] is True
    assert extras["ai_commoditization"]["no_new_rh_sleeve"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k173_notes_prod_config():
    notes = load_k173_notes()
    assert notes.get("version") == "2026-07-18"
    assert notes["cf_regime_packet"]["flag"] == "momentum_unwind_carry_risk_map"
    assert notes["bounce_rr"]["prefer_wait_clear_bounce"] is True
    assert notes["bounce_rr"]["no_momentum_chase"] is True
    assert notes["bounce_rr"]["extends_k172"] is True
    assert notes["tavi_costa_mc_teaser"]["context_only"] is True
    assert notes["klement_failure_gap"]["context_only"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k173(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k173": {
                    "version": "2026-07-18",
                    "cf_regime_packet": {
                        "flag": "momentum_unwind_carry_risk_map",
                    },
                    "bounce_rr": {
                        "prefer_wait_clear_bounce": True,
                        "no_momentum_chase": True,
                        "extends_k172": True,
                    },
                    "tavi_costa_mc_teaser": {"context_only": True},
                    "klement_failure_gap": {"context_only": True},
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k173_notes=load_k173_notes(cfg),
        notes_path=cfg,
    )
    assert extras is not None
    assert extras["k173_version"] == "2026-07-18"
    assert extras["cf_regime_packet"]["flag"] == "momentum_unwind_carry_risk_map"
    assert extras["bounce_rr"]["prefer_wait_clear_bounce"] is True
    assert extras["bounce_rr"]["no_momentum_chase"] is True
    assert extras["bounce_rr"]["extends_k172"] is True
    assert extras["tavi_costa_mc_teaser"]["context_only"] is True
    assert extras["klement_failure_gap"]["context_only"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k173_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    assert extras is not None
    assert extras["k173_version"] == "2026-07-18"
    assert extras["cf_regime_packet"]["flag"] == "momentum_unwind_carry_risk_map"
    assert extras["bounce_rr"]["prefer_wait_clear_bounce"] is True
    assert extras["bounce_rr"]["no_momentum_chase"] is True
    assert extras["bounce_rr"]["extends_k172"] is True
    assert extras["tavi_costa_mc_teaser"]["context_only"] is True
    assert extras["klement_failure_gap"]["context_only"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k174_notes_prod_config():
    notes = load_k174_notes()
    damaged = notes["macro_damaged_goods"]
    assert notes.get("version") == "2026-07-19"
    assert damaged["flag"] == "momentum_crash_capitulation_sector_div"
    assert damaged["bounce_rr_unclear"] is True
    assert damaged["do_not_chase"] is True
    assert notes["cf_weekend_depth"]["flag"] == "jul16_19_regime_packet"
    assert notes["cf_weekend_depth"]["view_changed_unwind_carry_weekend_depth"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k172_k173"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k174(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k174": {
                    "version": "2026-07-19",
                    "macro_damaged_goods": {
                        "flag": "momentum_crash_capitulation_sector_div",
                        "bounce_rr_unclear": True,
                        "do_not_chase": True,
                    },
                    "cf_weekend_depth": {
                        "flag": "jul16_19_regime_packet",
                        "view_changed_unwind_carry_weekend_depth": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k172_k173": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k174_notes=load_k174_notes(cfg),
        notes_path=cfg,
    )
    damaged = extras["macro_damaged_goods"]
    assert extras is not None
    assert extras["k174_version"] == "2026-07-19"
    assert damaged["flag"] == "momentum_crash_capitulation_sector_div"
    assert damaged["bounce_rr_unclear"] is True
    assert damaged["do_not_chase"] is True
    assert extras["cf_weekend_depth"]["flag"] == "jul16_19_regime_packet"
    assert extras["cf_weekend_depth"]["view_changed_unwind_carry_weekend_depth"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k172_k173"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k174_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    damaged = extras["macro_damaged_goods"]
    assert extras is not None
    assert extras["k174_version"] == "2026-07-19"
    assert damaged["flag"] == "momentum_crash_capitulation_sector_div"
    assert damaged["bounce_rr_unclear"] is True
    assert damaged["do_not_chase"] is True
    assert extras["cf_weekend_depth"]["flag"] == "jul16_19_regime_packet"
    assert extras["cf_weekend_depth"]["view_changed_unwind_carry_weekend_depth"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k177_notes_prod_config():
    notes = load_k177_notes()
    paid = notes["paid_macro_damaged_goods"]
    assert notes.get("version") == "2026-07-20"
    assert paid["flag"] == "incomplete_capitulation"
    assert paid["bounce_rr_unclear"] is True
    assert paid["do_not_chase"] is True
    assert notes["vix_vol_regime"]["flag"] == "vix_gt_20_sustain_caution"
    assert notes["vix_vol_regime"]["log_only"] is True
    assert notes["vix_vol_regime"]["no_size_gate_flip"] is True
    assert notes["am_vix_sox_context"]["flag"] == "am_vix_short_sox_coil_12k"
    assert notes["am_vix_sox_context"]["extends_k170"] is True
    assert notes["moontower_mixologist"]["flag"] == "iv_percentile_skew_geometry"
    assert notes["moontower_mixologist"]["screen_straddle_rr_strangle"] is True
    assert notes["moontower_mixologist"]["not_cocktail_names"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k177(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k177": {
                    "version": "2026-07-20",
                    "paid_macro_damaged_goods": {
                        "flag": "incomplete_capitulation",
                        "bounce_rr_unclear": True,
                        "do_not_chase": True,
                    },
                    "vix_vol_regime": {
                        "flag": "vix_gt_20_sustain_caution",
                        "log_only": True,
                        "no_size_gate_flip": True,
                    },
                    "am_vix_sox_context": {
                        "flag": "am_vix_short_sox_coil_12k",
                        "extends_k170": True,
                    },
                    "moontower_mixologist": {
                        "flag": "iv_percentile_skew_geometry",
                        "screen_straddle_rr_strangle": True,
                        "not_cocktail_names": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k177_notes=load_k177_notes(cfg),
        notes_path=cfg,
    )
    paid = extras["paid_macro_damaged_goods"]
    assert extras is not None
    assert extras["k177_version"] == "2026-07-20"
    assert paid["flag"] == "incomplete_capitulation"
    assert paid["bounce_rr_unclear"] is True
    assert paid["do_not_chase"] is True
    assert extras["vix_vol_regime"]["flag"] == "vix_gt_20_sustain_caution"
    assert extras["vix_vol_regime"]["log_only"] is True
    assert extras["vix_vol_regime"]["no_size_gate_flip"] is True
    assert extras["am_vix_sox_context"]["flag"] == "am_vix_short_sox_coil_12k"
    assert extras["am_vix_sox_context"]["extends_k170"] is True
    assert extras["moontower_mixologist"]["flag"] == "iv_percentile_skew_geometry"
    assert extras["moontower_mixologist"]["screen_straddle_rr_strangle"] is True
    assert extras["moontower_mixologist"]["not_cocktail_names"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k177_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    paid = extras["paid_macro_damaged_goods"]
    assert extras is not None
    assert extras["k177_version"] == "2026-07-20"
    assert paid["flag"] == "incomplete_capitulation"
    assert paid["bounce_rr_unclear"] is True
    assert paid["do_not_chase"] is True
    assert extras["vix_vol_regime"]["flag"] == "vix_gt_20_sustain_caution"
    assert extras["vix_vol_regime"]["log_only"] is True
    assert extras["vix_vol_regime"]["no_size_gate_flip"] is True
    assert extras["am_vix_sox_context"]["flag"] == "am_vix_short_sox_coil_12k"
    assert extras["am_vix_sox_context"]["extends_k170"] is True
    assert extras["moontower_mixologist"]["flag"] == "iv_percentile_skew_geometry"
    assert extras["moontower_mixologist"]["screen_straddle_rr_strangle"] is True
    assert extras["moontower_mixologist"]["not_cocktail_names"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k178_notes_prod_config():
    notes = load_k178_notes()
    teaser = notes["cf_equity_cliff_teaser"]
    assert notes.get("version") == "2026-07-21"
    assert teaser["flag"] == "spx_near_ath_flow_picture_pending"
    assert teaser["spx_drawdown_from_ath_pct"] == -2.18
    assert teaser["do_not_chase_on_free_teaser"] is True
    assert teaser["wait_paid_flow_picture"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k177"] is True
    assert notes["cme_single_stock_futures"]["context_only"] is True
    assert notes["cme_single_stock_futures"]["no_product_change"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k178(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k178": {
                    "version": "2026-07-21",
                    "cf_equity_cliff_teaser": {
                        "flag": "spx_near_ath_flow_picture_pending",
                        "spx_drawdown_from_ath_pct": -2.18,
                        "do_not_chase_on_free_teaser": True,
                        "wait_paid_flow_picture": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k177": True,
                    },
                    "cme_single_stock_futures": {
                        "context_only": True,
                        "no_product_change": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k178_notes=load_k178_notes(cfg),
        notes_path=cfg,
    )
    teaser = extras["cf_equity_cliff_teaser"]
    assert extras is not None
    assert extras["k178_version"] == "2026-07-21"
    assert teaser["flag"] == "spx_near_ath_flow_picture_pending"
    assert teaser["spx_drawdown_from_ath_pct"] == -2.18
    assert teaser["do_not_chase_on_free_teaser"] is True
    assert teaser["wait_paid_flow_picture"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k177"] is True
    assert extras["cme_single_stock_futures"]["context_only"] is True
    assert extras["cme_single_stock_futures"]["no_product_change"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k178_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    teaser = extras["cf_equity_cliff_teaser"]
    assert extras is not None
    assert extras["k178_version"] == "2026-07-21"
    assert teaser["flag"] == "spx_near_ath_flow_picture_pending"
    assert teaser["spx_drawdown_from_ath_pct"] == -2.18
    assert teaser["do_not_chase_on_free_teaser"] is True
    assert teaser["wait_paid_flow_picture"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["cme_single_stock_futures"]["context_only"] is True
    assert extras["cme_single_stock_futures"]["no_product_change"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k182_notes_prod_config():
    notes = load_k182_notes()
    iv_map = notes["liquid_to_illiquid_iv_map"]
    hf = notes["hf_fragile_positioning"]
    assert notes.get("version") == "2026-07-22"
    assert iv_map["flag"] == "prefer_spx_es_benchmark_when_xsp_thin"
    assert iv_map["prefer_liquid_benchmark"] is True
    assert iv_map["no_sparse_xsp_only_calibration"] is True
    assert notes["arxiv_2607_19030"]["context_only"] is True
    assert notes["arxiv_2607_19030"]["no_energy_book"] is True
    assert hf["flag"] == "cf_jul22_hf_fragile_after_equity_cliff"
    assert hf["do_not_add_size_on_bounce"] is True
    assert hf["wait_paid_flow_confirm"] is True
    assert hf["extends_k178_k177"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k178"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k182(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k182": {
                    "version": "2026-07-22",
                    "liquid_to_illiquid_iv_map": {
                        "flag": "prefer_spx_es_benchmark_when_xsp_thin",
                        "prefer_liquid_benchmark": True,
                        "no_sparse_xsp_only_calibration": True,
                    },
                    "arxiv_2607_19030": {
                        "context_only": True,
                        "no_energy_book": True,
                    },
                    "hf_fragile_positioning": {
                        "flag": "cf_jul22_hf_fragile_after_equity_cliff",
                        "do_not_add_size_on_bounce": True,
                        "wait_paid_flow_confirm": True,
                        "extends_k178_k177": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k178": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k182_notes=load_k182_notes(cfg),
        notes_path=cfg,
    )
    iv_map = extras["liquid_to_illiquid_iv_map"]
    hf = extras["hf_fragile_positioning"]
    assert extras is not None
    assert extras["k182_version"] == "2026-07-22"
    assert iv_map["flag"] == "prefer_spx_es_benchmark_when_xsp_thin"
    assert iv_map["prefer_liquid_benchmark"] is True
    assert iv_map["no_sparse_xsp_only_calibration"] is True
    assert extras["arxiv_2607_19030"]["context_only"] is True
    assert extras["arxiv_2607_19030"]["no_energy_book"] is True
    assert hf["flag"] == "cf_jul22_hf_fragile_after_equity_cliff"
    assert hf["do_not_add_size_on_bounce"] is True
    assert hf["wait_paid_flow_confirm"] is True
    assert hf["extends_k178_k177"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k178"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k182_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    iv_map = extras["liquid_to_illiquid_iv_map"]
    hf = extras["hf_fragile_positioning"]
    assert extras is not None
    assert extras["k182_version"] == "2026-07-22"
    assert iv_map["flag"] == "prefer_spx_es_benchmark_when_xsp_thin"
    assert iv_map["prefer_liquid_benchmark"] is True
    assert iv_map["no_sparse_xsp_only_calibration"] is True
    assert extras["arxiv_2607_19030"]["context_only"] is True
    assert extras["arxiv_2607_19030"]["no_energy_book"] is True
    assert hf["flag"] == "cf_jul22_hf_fragile_after_equity_cliff"
    assert hf["do_not_add_size_on_bounce"] is True
    assert hf["wait_paid_flow_confirm"] is True
    assert hf["extends_k178_k177"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k191_notes_prod_config():
    notes = load_k191_notes()
    treasury = notes["treasury_compression_teaser"]
    rh = notes["robinhood_chain"]
    assert notes.get("version") == "2026-07-23"
    assert treasury["flag"] == "cf_treasury_compressing_for_move"
    assert treasury["vol_regime_watch_only"] is True
    assert treasury["no_lane_a_size_on_free_teaser"] is True
    assert rh["flag"] == "arbitrum_l2_stock_tokens_rwa"
    assert rh["distribution_context"] is True
    assert rh["no_new_rh_sleeve"] is True
    assert notes["caution_stack"]["continue_hf_fragile_damaged_goods"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k182"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True
    assert notes["constraints"]["no_new_rh_sleeve"] is True


def test_build_monitor_macro_weather_extras_includes_k191(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k191": {
                    "version": "2026-07-23",
                    "treasury_compression_teaser": {
                        "flag": "cf_treasury_compressing_for_move",
                        "vol_regime_watch_only": True,
                        "no_lane_a_size_on_free_teaser": True,
                    },
                    "robinhood_chain": {
                        "flag": "arbitrum_l2_stock_tokens_rwa",
                        "distribution_context": True,
                        "no_new_rh_sleeve": True,
                    },
                    "caution_stack": {
                        "continue_hf_fragile_damaged_goods": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k182": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_new_rh_sleeve": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k191_notes=load_k191_notes(cfg),
        notes_path=cfg,
    )
    treasury = extras["treasury_compression_teaser"]
    rh = extras["robinhood_chain"]
    assert extras is not None
    assert extras["k191_version"] == "2026-07-23"
    assert treasury["flag"] == "cf_treasury_compressing_for_move"
    assert treasury["vol_regime_watch_only"] is True
    assert treasury["no_lane_a_size_on_free_teaser"] is True
    assert rh["flag"] == "arbitrum_l2_stock_tokens_rwa"
    assert rh["distribution_context"] is True
    assert rh["no_new_rh_sleeve"] is True
    assert extras["caution_stack"]["continue_hf_fragile_damaged_goods"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k182"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True
    assert extras["constraints"]["no_new_rh_sleeve"] is True


def test_build_monitor_macro_weather_extras_k191_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    treasury = extras["treasury_compression_teaser"]
    rh = extras["robinhood_chain"]
    assert extras is not None
    assert extras["k191_version"] == "2026-07-23"
    assert treasury["flag"] == "cf_treasury_compressing_for_move"
    assert treasury["vol_regime_watch_only"] is True
    assert treasury["no_lane_a_size_on_free_teaser"] is True
    assert rh["flag"] == "arbitrum_l2_stock_tokens_rwa"
    assert rh["distribution_context"] is True
    assert rh["no_new_rh_sleeve"] is True
    assert extras["caution_stack"]["continue_hf_fragile_damaged_goods"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k193_notes_prod_config():
    notes = load_k193_notes()
    ffj = notes["ffj_newsflow"]
    teaser = notes["cf_spx_selling_pressure_teaser"]
    assert notes.get("version") == "2026-07-24"
    assert ffj["flag"] == "arxiv_2607_20645_not_deployment_ready"
    assert ffj["best_all_label_match_pct"] == 52.4
    assert ffj["require_false_positive_budget"] is True
    assert ffj["prefer_low_fp_models"] is True
    assert ffj["human_gate_required"] is True
    assert teaser["flag"] == "spx_selling_pressure_title_only"
    assert teaser["title_only_not_signal"] is True
    assert teaser["confirm_livestream_or_report"] is True
    assert notes["clarity_act_wublock"]["awareness_only"] is True
    assert notes["clarity_act_wublock"]["no_action_unless_rh_chain_overlap"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k191"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_title_only"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k193(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k193": {
                    "version": "2026-07-24",
                    "ffj_newsflow": {
                        "flag": "arxiv_2607_20645_not_deployment_ready",
                        "best_all_label_match_pct": 52.4,
                        "require_false_positive_budget": True,
                        "prefer_low_fp_models": True,
                        "human_gate_required": True,
                    },
                    "cf_spx_selling_pressure_teaser": {
                        "flag": "spx_selling_pressure_title_only",
                        "title_only_not_signal": True,
                        "confirm_livestream_or_report": True,
                    },
                    "clarity_act_wublock": {
                        "awareness_only": True,
                        "no_action_unless_rh_chain_overlap": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k191": True,
                        "no_posture_change_on_title_only": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k193_notes=load_k193_notes(cfg),
        notes_path=cfg,
    )
    ffj = extras["ffj_newsflow"]
    teaser = extras["cf_spx_selling_pressure_teaser"]
    assert extras is not None
    assert extras["k193_version"] == "2026-07-24"
    assert ffj["flag"] == "arxiv_2607_20645_not_deployment_ready"
    assert ffj["best_all_label_match_pct"] == 52.4
    assert ffj["require_false_positive_budget"] is True
    assert ffj["prefer_low_fp_models"] is True
    assert ffj["human_gate_required"] is True
    assert teaser["flag"] == "spx_selling_pressure_title_only"
    assert teaser["title_only_not_signal"] is True
    assert teaser["confirm_livestream_or_report"] is True
    assert extras["clarity_act_wublock"]["awareness_only"] is True
    assert extras["clarity_act_wublock"]["no_action_unless_rh_chain_overlap"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k191"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_title_only"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k193_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    ffj = extras["ffj_newsflow"]
    teaser = extras["cf_spx_selling_pressure_teaser"]
    assert extras is not None
    assert extras["k193_version"] == "2026-07-24"
    assert ffj["flag"] == "arxiv_2607_20645_not_deployment_ready"
    assert ffj["best_all_label_match_pct"] == 52.4
    assert ffj["require_false_positive_budget"] is True
    assert ffj["prefer_low_fp_models"] is True
    assert ffj["human_gate_required"] is True
    assert teaser["flag"] == "spx_selling_pressure_title_only"
    assert teaser["title_only_not_signal"] is True
    assert teaser["confirm_livestream_or_report"] is True
    assert extras["clarity_act_wublock"]["awareness_only"] is True
    assert extras["clarity_act_wublock"]["no_action_unless_rh_chain_overlap"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k195_notes_prod_config():
    notes = load_k195_notes()
    aisuite = notes["aisuite"]
    teaser = notes["cf_crude_positioning_teaser"]
    assert notes.get("version") == "2026-07-25"
    assert aisuite["flag"] == "andrewyng_aisuite_mit_context"
    assert aisuite["context_only"] is True
    assert aisuite["provider_uniform_client_shape"] is True
    assert aisuite["no_stack_rewrite"] is True
    assert aisuite["no_adapter_until_spike_approved"] is True
    assert teaser["flag"] == "macro_positioning_crude_risk_title_only"
    assert teaser["title_only_not_signal"] is True
    assert teaser["confirm_report_before_overnight_size"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k193"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_title_only"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k195(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k195": {
                    "version": "2026-07-25",
                    "aisuite": {
                        "flag": "andrewyng_aisuite_mit_context",
                        "context_only": True,
                        "provider_uniform_client_shape": True,
                        "no_stack_rewrite": True,
                        "no_adapter_until_spike_approved": True,
                    },
                    "cf_crude_positioning_teaser": {
                        "flag": "macro_positioning_crude_risk_title_only",
                        "title_only_not_signal": True,
                        "confirm_report_before_overnight_size": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k193": True,
                        "no_posture_change_on_title_only": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k195_notes=load_k195_notes(cfg),
        notes_path=cfg,
    )
    aisuite = extras["aisuite"]
    teaser = extras["cf_crude_positioning_teaser"]
    assert extras is not None
    assert extras["k195_version"] == "2026-07-25"
    assert aisuite["flag"] == "andrewyng_aisuite_mit_context"
    assert aisuite["context_only"] is True
    assert aisuite["provider_uniform_client_shape"] is True
    assert aisuite["no_stack_rewrite"] is True
    assert aisuite["no_adapter_until_spike_approved"] is True
    assert teaser["flag"] == "macro_positioning_crude_risk_title_only"
    assert teaser["title_only_not_signal"] is True
    assert teaser["confirm_report_before_overnight_size"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k193"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_title_only"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k195_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    aisuite = extras["aisuite"]
    teaser = extras["cf_crude_positioning_teaser"]
    assert extras is not None
    assert extras["k195_version"] == "2026-07-25"
    assert aisuite["flag"] == "andrewyng_aisuite_mit_context"
    assert aisuite["context_only"] is True
    assert aisuite["provider_uniform_client_shape"] is True
    assert aisuite["no_stack_rewrite"] is True
    assert aisuite["no_adapter_until_spike_approved"] is True
    assert teaser["flag"] == "macro_positioning_crude_risk_title_only"
    assert teaser["title_only_not_signal"] is True
    assert teaser["confirm_report_before_overnight_size"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k196_notes_prod_config():
    notes = load_k196_notes()
    exit_left = notes["macro_exit_to_the_left"]
    hedge = notes["moontower_hedging"]
    attention = notes["attention_sv_arxiv_2607_22254"]
    assert notes.get("version") == "2026-07-27"
    assert exit_left["flag"] == "something_doesnt_feel_right_regime_watch"
    assert exit_left["regime_watch_only"] is True
    assert exit_left["no_chase_until_bounce_breakdown_resolves"] is True
    assert hedge["flag"] == "hedge_cost_smart_flow_overhedge"
    assert hedge["lane_b_tolerate_residual_delta"] is True
    assert hedge["no_mechanical_hedge_every_tick"] is True
    assert attention["watch_only"] is True
    assert attention["no_lane_change_without_calibration"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k195"] is True
    assert notes["lane_a_overnight"]["keep_exits_tight"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k196(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k196": {
                    "version": "2026-07-27",
                    "macro_exit_to_the_left": {
                        "flag": "something_doesnt_feel_right_regime_watch",
                        "regime_watch_only": True,
                        "no_chase_until_bounce_breakdown_resolves": True,
                    },
                    "moontower_hedging": {
                        "flag": "hedge_cost_smart_flow_overhedge",
                        "lane_b_tolerate_residual_delta": True,
                        "no_mechanical_hedge_every_tick": True,
                    },
                    "attention_sv_arxiv_2607_22254": {
                        "watch_only": True,
                        "no_lane_change_without_calibration": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k195": True,
                        "keep_exits_tight": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k196_notes=load_k196_notes(cfg),
        notes_path=cfg,
    )
    exit_left = extras["macro_exit_to_the_left"]
    hedge = extras["moontower_hedging"]
    attention = extras["attention_sv_arxiv_2607_22254"]
    assert extras is not None
    assert extras["k196_version"] == "2026-07-27"
    assert exit_left["flag"] == "something_doesnt_feel_right_regime_watch"
    assert exit_left["regime_watch_only"] is True
    assert exit_left["no_chase_until_bounce_breakdown_resolves"] is True
    assert hedge["flag"] == "hedge_cost_smart_flow_overhedge"
    assert hedge["lane_b_tolerate_residual_delta"] is True
    assert hedge["no_mechanical_hedge_every_tick"] is True
    assert attention["watch_only"] is True
    assert attention["no_lane_change_without_calibration"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k195"] is True
    assert extras["lane_a_overnight"]["keep_exits_tight"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k196_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    exit_left = extras["macro_exit_to_the_left"]
    hedge = extras["moontower_hedging"]
    attention = extras["attention_sv_arxiv_2607_22254"]
    assert extras is not None
    assert extras["k196_version"] == "2026-07-27"
    assert exit_left["flag"] == "something_doesnt_feel_right_regime_watch"
    assert exit_left["regime_watch_only"] is True
    assert exit_left["no_chase_until_bounce_breakdown_resolves"] is True
    assert hedge["flag"] == "hedge_cost_smart_flow_overhedge"
    assert hedge["lane_b_tolerate_residual_delta"] is True
    assert hedge["no_mechanical_hedge_every_tick"] is True
    assert attention["watch_only"] is True
    assert attention["no_lane_change_without_calibration"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k198_notes_prod_config():
    notes = load_k198_notes()
    iv = notes["iv_concavity_arxiv_2607_24680"]
    macro = notes["macro_korea_wti_fomc"]
    assert notes.get("version") == "2026-07-28"
    assert iv["flag"] == "event_day_smile_concavity_first_class"
    assert iv["watch_concave_w_inverse_u"] is True
    assert iv["no_assume_classical_u_smile_on_event_days"] is True
    assert (
        notes["lane_b_leaps_hedge_rolls"]["check_tenor_stability_before_static_smile"]
        is True
    )
    assert macro["flag"] == "asia_tech_crash_wti_dump_fomc_uncertainty"
    assert macro["regime_watch_only"] is True
    assert macro["no_chase_korea_ai_narrative_alone"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k196"] is True
    assert notes["lane_a_overnight"]["keep_exits_tight_into_fomc"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k198(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k198": {
                    "version": "2026-07-28",
                    "iv_concavity_arxiv_2607_24680": {
                        "flag": "event_day_smile_concavity_first_class",
                        "watch_concave_w_inverse_u": True,
                        "no_assume_classical_u_smile_on_event_days": True,
                    },
                    "lane_b_leaps_hedge_rolls": {
                        "check_tenor_stability_before_static_smile": True,
                    },
                    "macro_korea_wti_fomc": {
                        "flag": "asia_tech_crash_wti_dump_fomc_uncertainty",
                        "regime_watch_only": True,
                        "no_chase_korea_ai_narrative_alone": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k196": True,
                        "keep_exits_tight_into_fomc": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k198_notes=load_k198_notes(cfg),
        notes_path=cfg,
    )
    iv = extras["iv_concavity_arxiv_2607_24680"]
    macro = extras["macro_korea_wti_fomc"]
    assert extras is not None
    assert extras["k198_version"] == "2026-07-28"
    assert iv["flag"] == "event_day_smile_concavity_first_class"
    assert iv["watch_concave_w_inverse_u"] is True
    assert iv["no_assume_classical_u_smile_on_event_days"] is True
    assert (
        extras["lane_b_leaps_hedge_rolls"]["check_tenor_stability_before_static_smile"]
        is True
    )
    assert macro["flag"] == "asia_tech_crash_wti_dump_fomc_uncertainty"
    assert macro["regime_watch_only"] is True
    assert macro["no_chase_korea_ai_narrative_alone"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k196"] is True
    assert extras["lane_a_overnight"]["keep_exits_tight_into_fomc"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k198_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    iv = extras["iv_concavity_arxiv_2607_24680"]
    macro = extras["macro_korea_wti_fomc"]
    assert extras is not None
    assert extras["k198_version"] == "2026-07-28"
    assert iv["flag"] == "event_day_smile_concavity_first_class"
    assert iv["watch_concave_w_inverse_u"] is True
    assert iv["no_assume_classical_u_smile_on_event_days"] is True
    assert (
        extras["lane_b_leaps_hedge_rolls"]["check_tenor_stability_before_static_smile"]
        is True
    )
    assert macro["flag"] == "asia_tech_crash_wti_dump_fomc_uncertainty"
    assert macro["regime_watch_only"] is True
    assert macro["no_chase_korea_ai_narrative_alone"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_glitch_falcon_notes_prod_config():
    notes = load_glitch_falcon_notes()
    disc = notes["agentic_discipline"]
    stats = notes["falcon_marketing_stats"]
    assert notes.get("version") == "2026-07-29"
    assert disc["flag"] == "checklist_complete_identical_sizing_no_fomo"
    assert disc["trade_only_when_predeclared_conditions_fire"] is True
    assert disc["size_not_a_mood"] is True
    assert stats["do_not_promote_unverified"] is True
    assert stats["no_monitor_conviction_or_discord_copy"] is True
    assert (
        notes["agentic_handoff"]["automate_only_after_human_proven_repeatability"]
        is True
    )
    assert notes["agentic_handoff"]["mirrors_wiki_ingest_human_gates"] is True
    assert (
        notes["contrast_vs_macro_charts"]["psychology_process_not_level_watch"] is True
    )
    assert notes["lane_a_overnight"]["keep_tight_vs_k198"] is True
    assert notes["lane_a_overnight"]["checklist_complete_only"] is True
    assert notes["lane_a_overnight"]["size_not_a_mood"] is True
    assert notes["constraints"]["no_falcon_stats_in_monitors"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_glitch_falcon(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "glitch_falcon": {
                    "version": "2026-07-29",
                    "agentic_discipline": {
                        "flag": "checklist_complete_identical_sizing_no_fomo",
                        "trade_only_when_predeclared_conditions_fire": True,
                        "size_not_a_mood": True,
                    },
                    "falcon_marketing_stats": {
                        "do_not_promote_unverified": True,
                        "no_monitor_conviction_or_discord_copy": True,
                    },
                    "agentic_handoff": {
                        "automate_only_after_human_proven_repeatability": True,
                        "mirrors_wiki_ingest_human_gates": True,
                    },
                    "contrast_vs_macro_charts": {
                        "psychology_process_not_level_watch": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k198": True,
                        "checklist_complete_only": True,
                        "size_not_a_mood": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_falcon_stats_in_monitors": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        glitch_falcon_notes=load_glitch_falcon_notes(cfg),
        notes_path=cfg,
    )
    disc = extras["agentic_discipline"]
    stats = extras["falcon_marketing_stats"]
    assert extras is not None
    assert extras["glitch_falcon_version"] == "2026-07-29"
    assert disc["flag"] == "checklist_complete_identical_sizing_no_fomo"
    assert disc["trade_only_when_predeclared_conditions_fire"] is True
    assert disc["size_not_a_mood"] is True
    assert stats["do_not_promote_unverified"] is True
    assert stats["no_monitor_conviction_or_discord_copy"] is True
    assert (
        extras["agentic_handoff"]["automate_only_after_human_proven_repeatability"]
        is True
    )
    assert (
        extras["contrast_vs_macro_charts"]["psychology_process_not_level_watch"] is True
    )
    assert extras["lane_a_overnight"]["keep_tight_vs_k198"] is True
    assert extras["lane_a_overnight"]["checklist_complete_only"] is True
    assert extras["lane_a_overnight"]["size_not_a_mood"] is True
    assert extras["constraints"]["no_falcon_stats_in_monitors"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_glitch_falcon_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    disc = extras["agentic_discipline"]
    stats = extras["falcon_marketing_stats"]
    assert extras is not None
    assert extras["glitch_falcon_version"] == "2026-07-29"
    assert disc["flag"] == "checklist_complete_identical_sizing_no_fomo"
    assert disc["trade_only_when_predeclared_conditions_fire"] is True
    assert disc["size_not_a_mood"] is True
    assert stats["do_not_promote_unverified"] is True
    assert stats["no_monitor_conviction_or_discord_copy"] is True
    assert (
        extras["agentic_handoff"]["automate_only_after_human_proven_repeatability"]
        is True
    )
    assert (
        extras["contrast_vs_macro_charts"]["psychology_process_not_level_watch"] is True
    )
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    # k224 overwrites constraints (keeps prior flags; drops no_falcon_stats)
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k213_notes_prod_config():
    notes = load_k213_notes()
    warsh = notes["cf_warsh_equity_risk"]
    assert notes.get("version") == "2026-07-30"
    assert warsh["flag"] == "warsh_fed_path_vs_crash_narrative"
    assert warsh["tentative_macro_color_only"] is True
    assert warsh["no_order_change_from_rss_teaser"] is True
    assert notes["guruwatcher"]["do_not_arm_levels_from_this_piece"] is True
    assert notes["guruwatcher"]["no_numeric_macro_charts_claim"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_glitch_falcon"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k213(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k213": {
                    "version": "2026-07-30",
                    "cf_warsh_equity_risk": {
                        "flag": "warsh_fed_path_vs_crash_narrative",
                        "tentative_macro_color_only": True,
                        "no_order_change_from_rss_teaser": True,
                    },
                    "guruwatcher": {
                        "do_not_arm_levels_from_this_piece": True,
                        "no_numeric_macro_charts_claim": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_glitch_falcon": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k213_notes=load_k213_notes(cfg),
        notes_path=cfg,
    )
    warsh = extras["cf_warsh_equity_risk"]
    assert extras is not None
    assert extras["k213_version"] == "2026-07-30"
    assert warsh["flag"] == "warsh_fed_path_vs_crash_narrative"
    assert warsh["tentative_macro_color_only"] is True
    assert warsh["no_order_change_from_rss_teaser"] is True
    assert extras["guruwatcher"]["do_not_arm_levels_from_this_piece"] is True
    assert extras["guruwatcher"]["no_numeric_macro_charts_claim"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_glitch_falcon"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k213_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    warsh = extras["cf_warsh_equity_risk"]
    assert extras is not None
    assert extras["k213_version"] == "2026-07-30"
    assert warsh["flag"] == "warsh_fed_path_vs_crash_narrative"
    assert warsh["tentative_macro_color_only"] is True
    assert warsh["no_order_change_from_rss_teaser"] is True
    assert extras["guruwatcher"]["do_not_arm_levels_from_this_piece"] is True
    assert extras["guruwatcher"]["no_numeric_macro_charts_claim"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k214_notes_prod_config():
    notes = load_k214_notes()
    term = notes["wublock_term_premium"]
    assert notes.get("version") == "2026-07-30"
    assert term["flag"] == "treasuries_rerated_above_effr_fiscal_dominance"
    assert term["whole_curve_above_effr"] is True
    assert term["peak_surcharge_20y_bp"] == 152
    assert term["no_auto_strategy_flip"] is True
    assert notes["watch_list"]["acm_cr_term_premium"] is True
    assert notes["korea_ai_hardware_liquidation"]["not_direct_xsp_entry_signal"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k213"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_essay"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k214(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k214": {
                    "version": "2026-07-30",
                    "wublock_term_premium": {
                        "flag": "treasuries_rerated_above_effr_fiscal_dominance",
                        "whole_curve_above_effr": True,
                        "peak_surcharge_20y_bp": 152,
                        "no_auto_strategy_flip": True,
                    },
                    "watch_list": {"acm_cr_term_premium": True},
                    "korea_ai_hardware_liquidation": {
                        "not_direct_xsp_entry_signal": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k213": True,
                        "no_posture_change_on_essay": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k214_notes=load_k214_notes(cfg),
        notes_path=cfg,
    )
    term = extras["wublock_term_premium"]
    assert extras is not None
    assert extras["k214_version"] == "2026-07-30"
    assert term["flag"] == "treasuries_rerated_above_effr_fiscal_dominance"
    assert term["peak_surcharge_20y_bp"] == 152
    assert extras["watch_list"]["acm_cr_term_premium"] is True
    assert (
        extras["korea_ai_hardware_liquidation"]["not_direct_xsp_entry_signal"] is True
    )
    assert extras["lane_a_overnight"]["keep_tight_vs_k213"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_essay"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k214_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    term = extras["wublock_term_premium"]
    assert extras is not None
    assert extras["k214_version"] == "2026-07-30"
    assert term["flag"] == "treasuries_rerated_above_effr_fiscal_dominance"
    assert term["whole_curve_above_effr"] is True
    assert term["peak_surcharge_20y_bp"] == 152
    assert term["no_auto_strategy_flip"] is True
    assert extras["watch_list"]["acm_cr_term_premium"] is True
    assert (
        extras["korea_ai_hardware_liquidation"]["not_direct_xsp_entry_signal"] is True
    )
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k215_notes_prod_config():
    notes = load_k215_notes()
    mem = notes["macro_memory_unwind"]
    assert notes.get("version") == "2026-07-31"
    assert mem["flag"] == "memory_fund_wipeout_tactical_inflection"
    assert mem["regime_color_only"] is True
    assert mem["no_auto_strategy_change"] is True
    assert notes["risk_markers"]["memory_unwind"] is True
    assert notes["wublock_weekly"]["sec_clarity_contingency"] is True
    assert notes["cf_warsh_video"]["extends_k213"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k214"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_includes_k215(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k215": {
                    "version": "2026-07-31",
                    "macro_memory_unwind": {
                        "flag": "memory_fund_wipeout_tactical_inflection",
                        "regime_color_only": True,
                        "no_auto_strategy_change": True,
                    },
                    "risk_markers": {"memory_unwind": True},
                    "wublock_weekly": {"sec_clarity_contingency": True},
                    "cf_warsh_video": {"extends_k213": True},
                    "lane_a_overnight": {
                        "keep_tight_vs_k214": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k215_notes=load_k215_notes(cfg),
        notes_path=cfg,
    )
    mem = extras["macro_memory_unwind"]
    assert extras is not None
    assert extras["k215_version"] == "2026-07-31"
    assert mem["flag"] == "memory_fund_wipeout_tactical_inflection"
    assert mem["regime_color_only"] is True
    assert extras["risk_markers"]["memory_unwind"] is True
    assert extras["wublock_weekly"]["sec_clarity_contingency"] is True
    assert extras["cf_warsh_video"]["extends_k213"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k214"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_build_monitor_macro_weather_extras_k215_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    mem = extras["macro_memory_unwind"]
    assert extras is not None
    assert extras["k215_version"] == "2026-07-31"
    assert mem["flag"] == "memory_fund_wipeout_tactical_inflection"
    assert mem["regime_color_only"] is True
    assert mem["no_auto_strategy_change"] is True
    assert extras["risk_markers"]["memory_unwind"] is True
    assert extras["wublock_weekly"]["sec_clarity_contingency"] is True
    assert extras["cf_warsh_video"]["extends_k213"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


def test_load_k219_notes_prod_config():
    notes = load_k219_notes()
    ivs = notes["ivs_diffusion_saam_arxiv_2607_29220"]
    moon = notes["moontower_sound_of_inevitability"]
    cf = notes["cf_warsh_bessent_misdirection"]
    assert notes.get("version") == "2026-08-03"
    assert ivs["flag"] == "surface_quality_no_arb_residual_ideas_only"
    assert ivs["steal_surface_quality_diagnostics"] is True
    assert ivs["steal_no_arb_residual_framing"] is True
    assert ivs["lane_b_leaps_vol_context"] is True
    assert ivs["csi300_domain_off_topic"] is True
    assert ivs["no_diffusion_training_or_serving"] is True
    assert moon["flag"] == "mm_discipline_risk_posture_not_signal"
    assert moon["risk_posture_only"] is True
    assert moon["not_a_signal_generator"] is True
    assert cf["flag"] == "ai_capex_macro_framing_regime_notes"
    assert cf["ai_capex_macro_framing"] is True
    assert cf["no_auto_trade"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k215"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True
    assert notes["constraints"]["no_diffusion_vendor"] is True


def test_build_monitor_macro_weather_extras_includes_k219(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k219": {
                    "version": "2026-08-03",
                    "ivs_diffusion_saam_arxiv_2607_29220": {
                        "flag": "surface_quality_no_arb_residual_ideas_only",
                        "steal_surface_quality_diagnostics": True,
                        "no_diffusion_training_or_serving": True,
                    },
                    "moontower_sound_of_inevitability": {
                        "flag": "mm_discipline_risk_posture_not_signal",
                        "not_a_signal_generator": True,
                    },
                    "cf_warsh_bessent_misdirection": {
                        "flag": "ai_capex_macro_framing_regime_notes",
                        "no_auto_trade": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k215": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k219_notes=load_k219_notes(cfg),
        notes_path=cfg,
    )
    ivs = extras["ivs_diffusion_saam_arxiv_2607_29220"]
    assert extras is not None
    assert extras["k219_version"] == "2026-08-03"
    assert ivs["flag"] == "surface_quality_no_arb_residual_ideas_only"
    assert ivs["no_diffusion_training_or_serving"] is True
    assert extras["moontower_sound_of_inevitability"]["not_a_signal_generator"] is True
    assert extras["cf_warsh_bessent_misdirection"]["no_auto_trade"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k215"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_diffusion_vendor"] is True


def test_build_monitor_macro_weather_extras_k219_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    ivs = extras["ivs_diffusion_saam_arxiv_2607_29220"]
    moon = extras["moontower_sound_of_inevitability"]
    cf = extras["cf_warsh_bessent_misdirection"]
    assert extras is not None
    assert extras["k219_version"] == "2026-08-03"
    assert ivs["flag"] == "surface_quality_no_arb_residual_ideas_only"
    assert ivs["steal_surface_quality_diagnostics"] is True
    assert ivs["no_diffusion_training_or_serving"] is True
    assert moon["flag"] == "mm_discipline_risk_posture_not_signal"
    assert moon["not_a_signal_generator"] is True
    assert cf["flag"] == "ai_capex_macro_framing_regime_notes"
    assert cf["no_auto_trade"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True
    assert extras["constraints"]["no_diffusion_vendor"] is True


def test_load_k221_notes_prod_config():
    notes = load_k221_notes()
    mc = notes["macro_charts_aug3"]
    cf = notes["cf_misdirection_livestream"]
    assert notes.get("version") == "2026-08-03"
    assert mc["flag"] == "momentum_crash_closed_regime_color"
    assert mc["momentum_crash_closed"] is True
    assert mc["msft_amzn_july_strength"] is True
    assert mc["august_tactical_setup"] is True
    assert mc["vix_cot_1st_percentile"] is True
    assert mc["spx_net_long_extreme"] is True
    assert mc["regime_color_only"] is True
    assert mc["no_auto_strategy_change"] is True
    assert cf["flag"] == "ai_capital_flows_awareness_only"
    assert cf["warsh_bessent_ai_capex_misdirection"] is True
    assert cf["fx_positioning_teaser"] is True
    assert cf["vol_suppression_teaser"] is True
    assert cf["no_levels_from_teaser"] is True
    assert cf["awareness_only"] is True
    assert cf["no_auto_trade"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k219"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True
    assert notes["constraints"]["no_diffusion_vendor"] is True
    assert notes["constraints"]["no_cf_workers_vendor"] is True


def test_build_monitor_macro_weather_extras_includes_k221(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k221": {
                    "version": "2026-08-03",
                    "macro_charts_aug3": {
                        "flag": "momentum_crash_closed_regime_color",
                        "momentum_crash_closed": True,
                        "msft_amzn_july_strength": True,
                        "august_tactical_setup": True,
                        "vix_cot_1st_percentile": True,
                        "spx_net_long_extreme": True,
                        "regime_color_only": True,
                        "no_auto_strategy_change": True,
                    },
                    "cf_misdirection_livestream": {
                        "flag": "ai_capital_flows_awareness_only",
                        "warsh_bessent_ai_capex_misdirection": True,
                        "fx_positioning_teaser": True,
                        "vol_suppression_teaser": True,
                        "no_levels_from_teaser": True,
                        "awareness_only": True,
                        "no_auto_trade": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k219": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                        "no_cf_workers_vendor": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k221_notes=load_k221_notes(cfg),
        notes_path=cfg,
    )
    mc = extras["macro_charts_aug3"]
    assert extras is not None
    assert extras["k221_version"] == "2026-08-03"
    assert mc["flag"] == "momentum_crash_closed_regime_color"
    assert mc["regime_color_only"] is True
    assert mc["no_auto_strategy_change"] is True
    assert extras["cf_misdirection_livestream"]["awareness_only"] is True
    assert extras["cf_misdirection_livestream"]["no_auto_trade"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k219"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_cf_workers_vendor"] is True


def test_build_monitor_macro_weather_extras_k221_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    mc = extras["macro_charts_aug3"]
    cf = extras["cf_misdirection_livestream"]
    assert extras is not None
    assert extras["k221_version"] == "2026-08-03"
    assert mc["flag"] == "momentum_crash_closed_regime_color"
    assert mc["momentum_crash_closed"] is True
    assert mc["msft_amzn_july_strength"] is True
    assert mc["vix_cot_1st_percentile"] is True
    assert mc["spx_net_long_extreme"] is True
    assert mc["regime_color_only"] is True
    assert mc["no_auto_strategy_change"] is True
    assert cf["flag"] == "ai_capital_flows_awareness_only"
    assert cf["warsh_bessent_ai_capex_misdirection"] is True
    assert cf["fx_positioning_teaser"] is True
    assert cf["vol_suppression_teaser"] is True
    assert cf["no_levels_from_teaser"] is True
    assert cf["awareness_only"] is True
    assert cf["no_auto_trade"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_cf_workers_vendor"] is True


def test_load_k222_notes_prod_config():
    notes = load_k222_notes()
    vdv = notes["vdv_vix_first_arxiv_2608_01479"]
    lsv = notes["amortizing_lsv_neural_op_arxiv_2608_01217"]
    mags = notes["macro_aug4_mags_tech_bounce"]
    assert notes.get("version") == "2026-08-04"
    assert vdv["flag"] == "vix_first_joint_spx_vix_ideas_only"
    assert vdv["calibrate_vix_futures_options_first"] is True
    assert vdv["derive_spx_sv_consistent_with_vix"] is True
    assert vdv["lane_b_leaps_hedge_research"] is True
    assert vdv["no_live_auto_calibrator"] is True
    assert lsv["flag"] == "offline_amortize_online_eval_ideas_only"
    assert lsv["deeponet_fno_projection_consistent"] is True
    assert lsv["synthetic_latency_98_5_to_0_6_ms_context"] is True
    assert lsv["offline_amortize_online_evaluate"] is True
    assert lsv["no_neural_operator_serving"] is True
    assert mags["flag"] == "mags_tech_bounce_regime_guruwatcher_primary"
    assert mags["mags_tech_bounce_regime_only"] is True
    assert mags["guruwatcher_primary"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k221"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True
    assert notes["constraints"]["no_live_auto_calibrator"] is True
    assert notes["constraints"]["no_neural_operator_serving"] is True


def test_build_monitor_macro_weather_extras_includes_k222(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k222": {
                    "version": "2026-08-04",
                    "vdv_vix_first_arxiv_2608_01479": {
                        "flag": "vix_first_joint_spx_vix_ideas_only",
                        "calibrate_vix_futures_options_first": True,
                        "derive_spx_sv_consistent_with_vix": True,
                        "lane_b_leaps_hedge_research": True,
                        "no_live_auto_calibrator": True,
                    },
                    "amortizing_lsv_neural_op_arxiv_2608_01217": {
                        "flag": "offline_amortize_online_eval_ideas_only",
                        "deeponet_fno_projection_consistent": True,
                        "synthetic_latency_98_5_to_0_6_ms_context": True,
                        "offline_amortize_online_evaluate": True,
                        "no_neural_operator_serving": True,
                    },
                    "macro_aug4_mags_tech_bounce": {
                        "flag": "mags_tech_bounce_regime_guruwatcher_primary",
                        "mags_tech_bounce_regime_only": True,
                        "guruwatcher_primary": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k221": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                        "no_cf_workers_vendor": True,
                        "no_live_auto_calibrator": True,
                        "no_neural_operator_serving": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k222_notes=load_k222_notes(cfg),
        notes_path=cfg,
    )
    vdv = extras["vdv_vix_first_arxiv_2608_01479"]
    assert extras is not None
    assert extras["k222_version"] == "2026-08-04"
    assert vdv["flag"] == "vix_first_joint_spx_vix_ideas_only"
    assert vdv["no_live_auto_calibrator"] is True
    assert (
        extras["amortizing_lsv_neural_op_arxiv_2608_01217"][
            "no_neural_operator_serving"
        ]
        is True
    )
    assert extras["macro_aug4_mags_tech_bounce"]["guruwatcher_primary"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k221"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_live_auto_calibrator"] is True
    assert extras["constraints"]["no_neural_operator_serving"] is True


def test_build_monitor_macro_weather_extras_k222_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    vdv = extras["vdv_vix_first_arxiv_2608_01479"]
    lsv = extras["amortizing_lsv_neural_op_arxiv_2608_01217"]
    mags = extras["macro_aug4_mags_tech_bounce"]
    assert extras is not None
    assert extras["k222_version"] == "2026-08-04"
    assert vdv["flag"] == "vix_first_joint_spx_vix_ideas_only"
    assert vdv["calibrate_vix_futures_options_first"] is True
    assert vdv["derive_spx_sv_consistent_with_vix"] is True
    assert vdv["lane_b_leaps_hedge_research"] is True
    assert vdv["no_live_auto_calibrator"] is True
    assert lsv["flag"] == "offline_amortize_online_eval_ideas_only"
    assert lsv["deeponet_fno_projection_consistent"] is True
    assert lsv["synthetic_latency_98_5_to_0_6_ms_context"] is True
    assert lsv["offline_amortize_online_evaluate"] is True
    assert lsv["no_neural_operator_serving"] is True
    assert mags["flag"] == "mags_tech_bounce_regime_guruwatcher_primary"
    assert mags["mags_tech_bounce_regime_only"] is True
    assert mags["guruwatcher_primary"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True
    assert extras["constraints"]["no_diffusion_vendor"] is True
    assert extras["constraints"]["no_cf_workers_vendor"] is True
    assert extras["constraints"]["no_live_auto_calibrator"] is True
    assert extras["constraints"]["no_neural_operator_serving"] is True


def test_load_k223_notes_prod_config():
    notes = load_k223_notes()
    nnlci = notes["nnlci_arxiv_2608_02778"]
    cf = notes["cf_fx_yen_vix_rally_teaser"]
    macro = notes["macro_aug5_spx_sox_igv"]
    assert notes.get("version") == "2026-08-05"
    assert nnlci["flag"] == "offline_multi_asset_heston_barrier_ideas_only"
    assert nnlci["coarse_refined_mesh_nn_corrector"] is True
    assert nnlci["rmse_4_to_12x_claim_context"] is True
    assert nnlci["offline_research_only"] is True
    assert nnlci["no_live_pricer_wire"] is True
    assert cf["flag"] == "yen_carry_ai_liquidity_vix_up_on_rally"
    assert cf["yen_intervention_teaser"] is True
    assert cf["carry_ai_liquidity"] is True
    assert cf["vix_up_on_equity_rally"] is True
    assert cf["awareness_only"] is True
    assert cf["no_levels_from_teaser"] is True
    assert macro["flag"] == "spx_ath_sox_igv_30yr_failed_breakout_regime"
    assert macro["tech_materials_breadth"] is True
    assert macro["sox_igv_resistance_breaks_no_printed_levels"] is True
    assert macro["spx_ath_context"] is True
    assert macro["thirty_yr_failed_breakout"] is True
    assert macro["regime_color_only"] is True
    assert macro["no_auto_strategy_change"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k222"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True
    assert notes["constraints"]["no_live_pricer_wire"] is True


def test_build_monitor_macro_weather_extras_includes_k223(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k223": {
                    "version": "2026-08-05",
                    "nnlci_arxiv_2608_02778": {
                        "flag": "offline_multi_asset_heston_barrier_ideas_only",
                        "coarse_refined_mesh_nn_corrector": True,
                        "rmse_4_to_12x_claim_context": True,
                        "offline_research_only": True,
                        "no_live_pricer_wire": True,
                    },
                    "cf_fx_yen_vix_rally_teaser": {
                        "flag": "yen_carry_ai_liquidity_vix_up_on_rally",
                        "yen_intervention_teaser": True,
                        "carry_ai_liquidity": True,
                        "vix_up_on_equity_rally": True,
                        "awareness_only": True,
                        "no_levels_from_teaser": True,
                    },
                    "macro_aug5_spx_sox_igv": {
                        "flag": "spx_ath_sox_igv_30yr_failed_breakout_regime",
                        "tech_materials_breadth": True,
                        "sox_igv_resistance_breaks_no_printed_levels": True,
                        "spx_ath_context": True,
                        "thirty_yr_failed_breakout": True,
                        "regime_color_only": True,
                        "no_auto_strategy_change": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k222": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                        "no_cf_workers_vendor": True,
                        "no_live_auto_calibrator": True,
                        "no_neural_operator_serving": True,
                        "no_live_pricer_wire": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k223_notes=load_k223_notes(cfg),
        notes_path=cfg,
    )
    nnlci = extras["nnlci_arxiv_2608_02778"]
    assert extras is not None
    assert extras["k223_version"] == "2026-08-05"
    assert nnlci["flag"] == "offline_multi_asset_heston_barrier_ideas_only"
    assert nnlci["no_live_pricer_wire"] is True
    assert extras["cf_fx_yen_vix_rally_teaser"]["awareness_only"] is True
    assert extras["macro_aug5_spx_sox_igv"]["regime_color_only"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k222"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_live_pricer_wire"] is True


def test_build_monitor_macro_weather_extras_k223_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    nnlci = extras["nnlci_arxiv_2608_02778"]
    cf = extras["cf_fx_yen_vix_rally_teaser"]
    macro = extras["macro_aug5_spx_sox_igv"]
    assert extras is not None
    assert extras["k223_version"] == "2026-08-05"
    assert nnlci["flag"] == "offline_multi_asset_heston_barrier_ideas_only"
    assert nnlci["coarse_refined_mesh_nn_corrector"] is True
    assert nnlci["rmse_4_to_12x_claim_context"] is True
    assert nnlci["offline_research_only"] is True
    assert nnlci["no_live_pricer_wire"] is True
    assert cf["flag"] == "yen_carry_ai_liquidity_vix_up_on_rally"
    assert cf["yen_intervention_teaser"] is True
    assert cf["carry_ai_liquidity"] is True
    assert cf["vix_up_on_equity_rally"] is True
    assert cf["awareness_only"] is True
    assert cf["no_levels_from_teaser"] is True
    assert macro["flag"] == "spx_ath_sox_igv_30yr_failed_breakout_regime"
    assert macro["tech_materials_breadth"] is True
    assert macro["sox_igv_resistance_breaks_no_printed_levels"] is True
    assert macro["spx_ath_context"] is True
    assert macro["thirty_yr_failed_breakout"] is True
    assert macro["regime_color_only"] is True
    assert macro["no_auto_strategy_change"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True
    assert extras["constraints"]["no_diffusion_vendor"] is True
    assert extras["constraints"]["no_cf_workers_vendor"] is True
    assert extras["constraints"]["no_live_auto_calibrator"] is True
    assert extras["constraints"]["no_neural_operator_serving"] is True
    assert extras["constraints"]["no_live_pricer_wire"] is True


def test_load_k224_notes_prod_config():
    notes = load_k224_notes()
    klement = notes["klement_ai_datacentre_capex"]
    smh = notes["last_printed_smh_plan"]
    assert notes.get("version") == "2026-08-05"
    assert klement["flag"] == "ai_capex_vs_earnings_boom_mean_reversion_risk"
    assert klement["us_earnings_60pct_above_trend_ai_context"] is True
    assert klement["one_gw_build_vs_compute_revenue_poor"] is True
    assert klement["mean_reversion_multiple_compression_risk"] is True
    assert klement["not_a_timed_short"] is True
    assert klement["lane_ab_ai_semis_exposure"] is True
    assert klement["regime_awareness_only"] is True
    assert smh["flag"] == "aug4_macro_smh_plan_guruwatcher_primary"
    assert smh["guruwatcher_primary"] is True
    assert smh["no_new_printed_smh_sox_nvda_levels"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k223"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True
    assert notes["constraints"]["no_tabular_llm_prediction"] is True


def test_build_monitor_macro_weather_extras_includes_k224(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k224": {
                    "version": "2026-08-05",
                    "klement_ai_datacentre_capex": {
                        "flag": "ai_capex_vs_earnings_boom_mean_reversion_risk",
                        "us_earnings_60pct_above_trend_ai_context": True,
                        "one_gw_build_vs_compute_revenue_poor": True,
                        "mean_reversion_multiple_compression_risk": True,
                        "not_a_timed_short": True,
                        "lane_ab_ai_semis_exposure": True,
                        "regime_awareness_only": True,
                    },
                    "last_printed_smh_plan": {
                        "flag": "aug4_macro_smh_plan_guruwatcher_primary",
                        "guruwatcher_primary": True,
                        "no_new_printed_smh_sox_nvda_levels": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k223": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                        "no_cf_workers_vendor": True,
                        "no_live_auto_calibrator": True,
                        "no_neural_operator_serving": True,
                        "no_live_pricer_wire": True,
                        "no_tabular_llm_prediction": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k224_notes=load_k224_notes(cfg),
        notes_path=cfg,
    )
    klement = extras["klement_ai_datacentre_capex"]
    assert extras is not None
    assert extras["k224_version"] == "2026-08-05"
    assert klement["flag"] == "ai_capex_vs_earnings_boom_mean_reversion_risk"
    assert klement["not_a_timed_short"] is True
    assert extras["last_printed_smh_plan"]["guruwatcher_primary"] is True
    assert extras["last_printed_smh_plan"]["no_new_printed_smh_sox_nvda_levels"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k223"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_tabular_llm_prediction"] is True


def test_build_monitor_macro_weather_extras_k224_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    klement = extras["klement_ai_datacentre_capex"]
    smh = extras["last_printed_smh_plan"]
    assert extras is not None
    assert extras["k224_version"] == "2026-08-05"
    assert klement["flag"] == "ai_capex_vs_earnings_boom_mean_reversion_risk"
    assert klement["us_earnings_60pct_above_trend_ai_context"] is True
    assert klement["one_gw_build_vs_compute_revenue_poor"] is True
    assert klement["mean_reversion_multiple_compression_risk"] is True
    assert klement["not_a_timed_short"] is True
    assert klement["lane_ab_ai_semis_exposure"] is True
    assert klement["regime_awareness_only"] is True
    assert smh["flag"] == "aug4_macro_smh_plan_guruwatcher_primary"
    assert smh["guruwatcher_primary"] is True
    assert smh["no_new_printed_smh_sox_nvda_levels"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True
    assert extras["constraints"]["no_diffusion_vendor"] is True
    assert extras["constraints"]["no_cf_workers_vendor"] is True
    assert extras["constraints"]["no_live_auto_calibrator"] is True
    assert extras["constraints"]["no_neural_operator_serving"] is True
    assert extras["constraints"]["no_live_pricer_wire"] is True
    assert extras["constraints"]["no_tabular_llm_prediction"] is True


def test_load_k225_notes_prod_config():
    notes = load_k225_notes()
    cefi = notes["wublock_july_vc_cefi"]
    macro = notes["macro_aug6_hard_assets"]
    teaser = notes["cf_global_economy_teaser"]
    assert notes.get("version") == "2026-08-06"
    assert cefi["flag"] == "cefi_tokenization_vc_regime_context"
    assert cefi["citadel_cryptocom_400m_20b_valuation_context"] is True
    assert cefi["alpaca_tokenization_custody_claim_context"] is True
    assert cefi["prime_intellect_context"] is True
    assert cefi["watch_spill_into_vol_regime_narrative"] is True
    assert cefi["no_auto_trade"] is True
    assert macro["flag"] == "tactically_bullish_tech_strategically_bullish_hard_assets"
    assert macro["tech_ai_tactical_bullish"] is True
    assert macro["hard_assets_gdx_gold_strategic"] is True
    assert macro["soft_regime_note_overnight_lanes"] is True
    assert macro["playbook_snapshot_gates_unchanged"] is True
    assert teaser["flag"] == "rss_teaser_only_no_invented_claims"
    assert teaser["rss_teaser_only"] is True
    assert teaser["no_invented_claims"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k224"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True
    assert notes["constraints"]["no_tabular_llm_prediction"] is True


def test_build_monitor_macro_weather_extras_includes_k225(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k225": {
                    "version": "2026-08-06",
                    "wublock_july_vc_cefi": {
                        "flag": "cefi_tokenization_vc_regime_context",
                        "citadel_cryptocom_400m_20b_valuation_context": True,
                        "alpaca_tokenization_custody_claim_context": True,
                        "prime_intellect_context": True,
                        "watch_spill_into_vol_regime_narrative": True,
                        "no_auto_trade": True,
                    },
                    "macro_aug6_hard_assets": {
                        "flag": (
                            "tactically_bullish_tech_strategically_bullish_hard_assets"
                        ),
                        "tech_ai_tactical_bullish": True,
                        "hard_assets_gdx_gold_strategic": True,
                        "soft_regime_note_overnight_lanes": True,
                        "playbook_snapshot_gates_unchanged": True,
                    },
                    "cf_global_economy_teaser": {
                        "flag": "rss_teaser_only_no_invented_claims",
                        "rss_teaser_only": True,
                        "no_invented_claims": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k224": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                        "no_cf_workers_vendor": True,
                        "no_live_auto_calibrator": True,
                        "no_neural_operator_serving": True,
                        "no_live_pricer_wire": True,
                        "no_tabular_llm_prediction": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k225_notes=load_k225_notes(cfg),
        notes_path=cfg,
    )
    cefi = extras["wublock_july_vc_cefi"]
    assert extras is not None
    assert extras["k225_version"] == "2026-08-06"
    assert cefi["flag"] == "cefi_tokenization_vc_regime_context"
    assert cefi["no_auto_trade"] is True
    assert extras["macro_aug6_hard_assets"]["playbook_snapshot_gates_unchanged"] is True
    assert extras["cf_global_economy_teaser"]["no_invented_claims"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k224"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_tabular_llm_prediction"] is True


def test_build_monitor_macro_weather_extras_k225_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    cefi = extras["wublock_july_vc_cefi"]
    macro = extras["macro_aug6_hard_assets"]
    teaser = extras["cf_global_economy_teaser"]
    assert extras is not None
    assert extras["k225_version"] == "2026-08-06"
    assert cefi["flag"] == "cefi_tokenization_vc_regime_context"
    assert cefi["citadel_cryptocom_400m_20b_valuation_context"] is True
    assert cefi["alpaca_tokenization_custody_claim_context"] is True
    assert cefi["prime_intellect_context"] is True
    assert cefi["watch_spill_into_vol_regime_narrative"] is True
    assert cefi["no_auto_trade"] is True
    assert macro["flag"] == "tactically_bullish_tech_strategically_bullish_hard_assets"
    assert macro["tech_ai_tactical_bullish"] is True
    assert macro["hard_assets_gdx_gold_strategic"] is True
    assert macro["soft_regime_note_overnight_lanes"] is True
    assert macro["playbook_snapshot_gates_unchanged"] is True
    assert teaser["flag"] == "rss_teaser_only_no_invented_claims"
    assert teaser["rss_teaser_only"] is True
    assert teaser["no_invented_claims"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True
    assert extras["constraints"]["no_diffusion_vendor"] is True
    assert extras["constraints"]["no_cf_workers_vendor"] is True
    assert extras["constraints"]["no_live_auto_calibrator"] is True
    assert extras["constraints"]["no_neural_operator_serving"] is True
    assert extras["constraints"]["no_live_pricer_wire"] is True
    assert extras["constraints"]["no_tabular_llm_prediction"] is True



def test_load_k226_notes_prod_config():
    notes = load_k226_notes()
    clarity = notes["wublock_clarity_act_delay"]
    heston = notes["heston_weak_form_arxiv_2608_05009"]
    manip = notes["options_manip_velocity_arxiv_2608_05373"]
    teaser = notes["cf_golden_era_teaser"]
    amd = notes["amd_taalas_asic_thesis"]
    assert notes.get("version") == "2026-08-07"
    assert clarity["flag"] == "clarity_vote_delayed_tokenized_rwa_regime"
    assert clarity["clarity_act_vote_delayed_again"] is True
    assert clarity["bernstein_2026_odds_declining_context"] is True
    assert clarity["project_crypto_may_accelerate"] is True
    assert clarity["soft_regime_tokenized_rwa"] is True
    assert clarity["playbook_snapshot_gates_unchanged"] is True
    assert heston["flag"] == "inverse_sv_recovery_awareness_only"
    assert heston["inverse_recovery_sv_from_price_path"] is True
    assert heston["awareness_only"] is True
    assert heston["no_live_calibrator"] is True
    assert manip["flag"] == "state_velocity_detectors_surveillance_awareness"
    assert manip["pump_and_crash_surveillance_awareness"] is True
    assert manip["no_prod_detector_this_batch"] is True
    assert teaser["flag"] == "rss_teaser_only_no_invented_claims"
    assert teaser["rss_teaser_only"] is True
    assert teaser["no_invented_claims"] is True
    assert amd["flag"] == "soft_inference_capex_awareness"
    assert amd["latent_space_context"] is True
    assert amd["soft_inference_capex_awareness"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k225"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_integral_solver"] is True
    assert notes["constraints"]["no_strategy_code"] is True
    assert notes["constraints"]["no_tabular_llm_prediction"] is True
    assert notes["constraints"]["no_prod_manip_detector"] is True


def test_build_monitor_macro_weather_extras_includes_k226(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k226": {
                    "version": "2026-08-07",
                    "wublock_clarity_act_delay": {
                        "flag": "clarity_vote_delayed_tokenized_rwa_regime",
                        "clarity_act_vote_delayed_again": True,
                        "bernstein_2026_odds_declining_context": True,
                        "project_crypto_may_accelerate": True,
                        "soft_regime_tokenized_rwa": True,
                        "playbook_snapshot_gates_unchanged": True,
                    },
                    "heston_weak_form_arxiv_2608_05009": {
                        "flag": "inverse_sv_recovery_awareness_only",
                        "inverse_recovery_sv_from_price_path": True,
                        "awareness_only": True,
                        "no_live_calibrator": True,
                    },
                    "options_manip_velocity_arxiv_2608_05373": {
                        "flag": "state_velocity_detectors_surveillance_awareness",
                        "pump_and_crash_surveillance_awareness": True,
                        "no_prod_detector_this_batch": True,
                    },
                    "cf_golden_era_teaser": {
                        "flag": "rss_teaser_only_no_invented_claims",
                        "rss_teaser_only": True,
                        "no_invented_claims": True,
                    },
                    "amd_taalas_asic_thesis": {
                        "flag": "soft_inference_capex_awareness",
                        "latent_space_context": True,
                        "soft_inference_capex_awareness": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k225": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                        "no_cf_workers_vendor": True,
                        "no_live_auto_calibrator": True,
                        "no_neural_operator_serving": True,
                        "no_live_pricer_wire": True,
                        "no_tabular_llm_prediction": True,
                        "no_prod_manip_detector": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k226_notes=load_k226_notes(cfg),
        notes_path=cfg,
    )
    clarity = extras["wublock_clarity_act_delay"]
    assert extras is not None
    assert extras["k226_version"] == "2026-08-07"
    assert clarity["flag"] == "clarity_vote_delayed_tokenized_rwa_regime"
    assert clarity["playbook_snapshot_gates_unchanged"] is True
    assert extras["heston_weak_form_arxiv_2608_05009"]["no_live_calibrator"] is True
    assert extras["options_manip_velocity_arxiv_2608_05373"][
        "no_prod_detector_this_batch"
    ] is True
    assert extras["cf_golden_era_teaser"]["no_invented_claims"] is True
    assert extras["amd_taalas_asic_thesis"]["soft_inference_capex_awareness"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k225"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_prod_manip_detector"] is True
    assert extras["constraints"]["no_tabular_llm_prediction"] is True


def test_build_monitor_macro_weather_extras_k226_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    clarity = extras["wublock_clarity_act_delay"]
    heston = extras["heston_weak_form_arxiv_2608_05009"]
    manip = extras["options_manip_velocity_arxiv_2608_05373"]
    teaser = extras["cf_golden_era_teaser"]
    amd = extras["amd_taalas_asic_thesis"]
    assert extras is not None
    assert extras["k226_version"] == "2026-08-07"
    assert clarity["flag"] == "clarity_vote_delayed_tokenized_rwa_regime"
    assert clarity["clarity_act_vote_delayed_again"] is True
    assert clarity["bernstein_2026_odds_declining_context"] is True
    assert clarity["project_crypto_may_accelerate"] is True
    assert clarity["soft_regime_tokenized_rwa"] is True
    assert clarity["playbook_snapshot_gates_unchanged"] is True
    assert heston["flag"] == "inverse_sv_recovery_awareness_only"
    assert heston["inverse_recovery_sv_from_price_path"] is True
    assert heston["awareness_only"] is True
    assert heston["no_live_calibrator"] is True
    assert manip["flag"] == "state_velocity_detectors_surveillance_awareness"
    assert manip["pump_and_crash_surveillance_awareness"] is True
    assert manip["no_prod_detector_this_batch"] is True
    assert teaser["flag"] == "rss_teaser_only_no_invented_claims"
    assert teaser["rss_teaser_only"] is True
    assert teaser["no_invented_claims"] is True
    assert amd["flag"] == "soft_inference_capex_awareness"
    assert amd["latent_space_context"] is True
    assert amd["soft_inference_capex_awareness"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True
    assert extras["constraints"]["no_diffusion_vendor"] is True
    assert extras["constraints"]["no_cf_workers_vendor"] is True
    assert extras["constraints"]["no_live_auto_calibrator"] is True
    assert extras["constraints"]["no_neural_operator_serving"] is True
    assert extras["constraints"]["no_live_pricer_wire"] is True
    assert extras["constraints"]["no_tabular_llm_prediction"] is True
    assert extras["constraints"]["no_prod_manip_detector"] is True




def test_load_k228_notes_prod_config():
    notes = load_k228_notes()
    hl = notes["wublock_hl_july_volume"]
    uni = notes["uniswap_pools_robinhood_chain"]
    eth = notes["etherfi_eigenlayer_exit"]
    teaser = notes["cf_eow_20260808_teaser"]
    assert notes.get("version") == "2026-08-08"
    assert hl["flag"] == "hyperliquid_liquidity_concentration_awareness"
    assert hl["july_perps_218b_context"] is True
    assert hl["top8_share_54pct_context"] is True
    assert hl["liquidity_concentration_awareness"] is True
    assert hl["no_auto_trade"] is True
    assert uni["flag"] == "meme_launch_distribution_vol_narrative"
    assert uni["meme_launches_on_robinhood_chain"] is True
    assert uni["distribution_vol_narrative_only"] is True
    assert eth["flag"] == "restaking_regime_weeths_symbiotic"
    assert eth["eigenlayer_exit_context"] is True
    assert eth["weeths_symbiotic_context"] is True
    assert eth["restaking_regime_note"] is True
    assert teaser["flag"] == "rss_teaser_only_no_invented_claims"
    assert teaser["rss_teaser_only"] is True
    assert teaser["no_invented_claims"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k226"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["playbook_snapshot_gates_unchanged"] is True
    assert notes["constraints"]["no_live_auto_calibrator"] is True


def test_build_monitor_macro_weather_extras_includes_k228(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k228": {
                    "version": "2026-08-08",
                    "wublock_hl_july_volume": {
                        "flag": "hyperliquid_liquidity_concentration_awareness",
                        "july_perps_218b_context": True,
                        "top8_share_54pct_context": True,
                        "liquidity_concentration_awareness": True,
                        "no_auto_trade": True,
                    },
                    "uniswap_pools_robinhood_chain": {
                        "flag": "meme_launch_distribution_vol_narrative",
                        "meme_launches_on_robinhood_chain": True,
                        "distribution_vol_narrative_only": True,
                    },
                    "etherfi_eigenlayer_exit": {
                        "flag": "restaking_regime_weeths_symbiotic",
                        "eigenlayer_exit_context": True,
                        "weeths_symbiotic_context": True,
                        "restaking_regime_note": True,
                    },
                    "cf_eow_20260808_teaser": {
                        "flag": "rss_teaser_only_no_invented_claims",
                        "rss_teaser_only": True,
                        "no_invented_claims": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k226": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                        "no_cf_workers_vendor": True,
                        "no_live_auto_calibrator": True,
                        "no_neural_operator_serving": True,
                        "no_live_pricer_wire": True,
                        "no_tabular_llm_prediction": True,
                        "no_prod_manip_detector": True,
                        "playbook_snapshot_gates_unchanged": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k228_notes=load_k228_notes(cfg),
        notes_path=cfg,
    )
    assert extras is not None
    assert extras["k228_version"] == "2026-08-08"
    assert extras["wublock_hl_july_volume"]["no_auto_trade"] is True
    assert extras["uniswap_pools_robinhood_chain"]["distribution_vol_narrative_only"] is True
    assert extras["etherfi_eigenlayer_exit"]["restaking_regime_note"] is True
    assert extras["cf_eow_20260808_teaser"]["no_invented_claims"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k226"] is True
    assert extras["constraints"]["playbook_snapshot_gates_unchanged"] is True


def test_build_monitor_macro_weather_extras_k228_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    assert extras is not None
    assert extras["k228_version"] == "2026-08-08"
    assert extras["wublock_hl_july_volume"]["july_perps_218b_context"] is True
    assert extras["uniswap_pools_robinhood_chain"]["meme_launches_on_robinhood_chain"] is True
    assert extras["etherfi_eigenlayer_exit"]["weeths_symbiotic_context"] is True
    assert extras["cf_eow_20260808_teaser"]["rss_teaser_only"] is True
    # k229 overwrites lane_a_overnight with keep_tight_vs_k228
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True


def test_load_k229_notes_prod_config():
    notes = load_k229_notes()
    asia = notes["wublock_asia_top10_russia_japan"]
    assert notes.get("version") == "2026-08-09"
    assert asia["flag"] == "asia_regulatory_regime_context"
    assert asia["russia_282_fz_phased_20260901"] is True
    assert asia["non_qualified_300k_rub_yr_cap_context"] is True
    assert asia["cbr_supervision_licensed_path_20270701"] is True
    assert asia["moscow_exchange_custody_prep_late2026_early2027"] is True
    assert asia["japan_fsa_crypto_stablecoin_division_20260807"] is True
    assert asia["tse_material_transformation_re_review"] is True
    assert asia["crypto_treasury_listing_risk_narrative"] is True
    assert asia["secondary_taiwan_india_bithumb_upbit_awareness"] is True
    assert asia["no_auto_lane_size_or_overnight_change"] is True
    assert asia["playbook_snapshot_gates_unchanged"] is True
    assert notes["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert notes["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert notes["constraints"]["no_auto_lane_size_change"] is True
    assert notes["constraints"]["no_live_auto_calibrator"] is True


def test_build_monitor_macro_weather_extras_includes_k229(tmp_path: Path):
    cfg = tmp_path / "k155.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "k155": {
                    "version": "2026-07-10",
                    "event_cluster": "July FOMC / CPI cluster",
                    "sofr_curve": {"note": "SOFR anchor"},
                },
                "k229": {
                    "version": "2026-08-09",
                    "wublock_asia_top10_russia_japan": {
                        "flag": "asia_regulatory_regime_context",
                        "russia_282_fz_phased_20260901": True,
                        "non_qualified_300k_rub_yr_cap_context": True,
                        "cbr_supervision_licensed_path_20270701": True,
                        "moscow_exchange_custody_prep_late2026_early2027": True,
                        "japan_fsa_crypto_stablecoin_division_20260807": True,
                        "tse_material_transformation_re_review": True,
                        "crypto_treasury_listing_risk_narrative": True,
                        "secondary_taiwan_india_bithumb_upbit_awareness": True,
                        "no_auto_lane_size_or_overnight_change": True,
                        "playbook_snapshot_gates_unchanged": True,
                    },
                    "lane_a_overnight": {
                        "keep_tight_vs_k228": True,
                        "no_posture_change_on_teaser": True,
                    },
                    "constraints": {
                        "no_integral_solver": True,
                        "no_strategy_code": True,
                        "no_diffusion_vendor": True,
                        "no_cf_workers_vendor": True,
                        "no_live_auto_calibrator": True,
                        "no_neural_operator_serving": True,
                        "no_live_pricer_wire": True,
                        "no_tabular_llm_prediction": True,
                        "no_prod_manip_detector": True,
                        "no_auto_lane_size_change": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    notes = load_k155_notes(cfg)
    extras = build_monitor_macro_weather_extras(
        notes,
        usdjpy=162.40,
        k229_notes=load_k229_notes(cfg),
        notes_path=cfg,
    )
    assert extras is not None
    assert extras["k229_version"] == "2026-08-09"
    assert extras["wublock_asia_top10_russia_japan"]["playbook_snapshot_gates_unchanged"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["constraints"]["no_auto_lane_size_change"] is True


def test_build_monitor_macro_weather_extras_k229_from_prod_config():
    extras = build_monitor_macro_weather_extras(usdjpy=162.35)
    asia = extras["wublock_asia_top10_russia_japan"]
    assert extras is not None
    assert extras["k229_version"] == "2026-08-09"
    assert asia["flag"] == "asia_regulatory_regime_context"
    assert asia["russia_282_fz_phased_20260901"] is True
    assert asia["japan_fsa_crypto_stablecoin_division_20260807"] is True
    assert asia["no_auto_lane_size_or_overnight_change"] is True
    assert asia["playbook_snapshot_gates_unchanged"] is True
    assert extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert extras["lane_a_overnight"]["no_posture_change_on_teaser"] is True
    assert extras["constraints"]["no_auto_lane_size_change"] is True
    assert extras["constraints"]["no_prod_manip_detector"] is True



def test_run_monitor_attaches_macro_weather_extras(tmp_path, monkeypatch):
    from xsp_killer.lane_a_monitor import run_monitor

    monkeypatch.setattr(
        "xsp_killer.lane_a_monitor.rh_read_enabled",
        lambda: False,
    )
    report = run_monitor(
        state_path=tmp_path / "state.json",
        positions_override=[],
        publish_intel=False,
        write_paper_brief=False,
    )
    assert report.macro_weather_extras is not None
    assert report.macro_weather_extras["k155_version"] == "2026-07-10"
    assert report.macro_weather_extras["k158_version"] == "2026-07-11"
    assert report.macro_weather_extras["k161_version"] == "2026-07-13"
    assert report.macro_weather_extras["k162_version"] == "2026-07-13"
    assert report.macro_weather_extras["k167_version"] == "2026-07-15"
    assert report.macro_weather_extras["k170_version"] == "2026-07-16"
    assert report.macro_weather_extras["k172_version"] == "2026-07-17"
    assert report.macro_weather_extras["k173_version"] == "2026-07-18"
    assert report.macro_weather_extras["k174_version"] == "2026-07-19"
    assert report.macro_weather_extras["k177_version"] == "2026-07-20"
    assert report.macro_weather_extras["k178_version"] == "2026-07-21"
    assert report.macro_weather_extras["k182_version"] == "2026-07-22"
    assert report.macro_weather_extras["k191_version"] == "2026-07-23"
    assert report.macro_weather_extras["k193_version"] == "2026-07-24"
    assert report.macro_weather_extras["k195_version"] == "2026-07-25"
    assert report.macro_weather_extras["k196_version"] == "2026-07-27"
    assert report.macro_weather_extras["k198_version"] == "2026-07-28"
    assert report.macro_weather_extras["glitch_falcon_version"] == "2026-07-29"
    assert report.macro_weather_extras["k213_version"] == "2026-07-30"
    assert report.macro_weather_extras["k214_version"] == "2026-07-30"
    assert report.macro_weather_extras["k215_version"] == "2026-07-31"
    assert report.macro_weather_extras["k219_version"] == "2026-08-03"
    assert report.macro_weather_extras["k221_version"] == "2026-08-03"
    assert report.macro_weather_extras["k222_version"] == "2026-08-04"
    assert report.macro_weather_extras["k223_version"] == "2026-08-05"
    assert report.macro_weather_extras["k224_version"] == "2026-08-05"
    assert report.macro_weather_extras["k225_version"] == "2026-08-06"
    assert report.macro_weather_extras["k226_version"] == "2026-08-07"
    assert report.macro_weather_extras["k228_version"] == "2026-08-08"
    assert report.macro_weather_extras["k229_version"] == "2026-08-09"
    assert "sofr_front_end" in report.macro_weather_extras
    assert "fomc_jul29" in report.macro_weather_extras
    assert "cev_aspiration" in report.macro_weather_extras
    assert "sentiment_capitulation" in report.macro_weather_extras
    assert "oil_vs_2yr" in report.macro_weather_extras
    assert "moontower_volga" in report.macro_weather_extras
    assert "korea_memory_semis" in report.macro_weather_extras
    assert "dxy_breakdown" in report.macro_weather_extras
    assert "theory_shelf" in report.macro_weather_extras
    assert "turbovec" in report.macro_weather_extras
    assert "cf_view_shift" in report.macro_weather_extras
    assert "asia_ai_selloff" in report.macro_weather_extras
    assert "ai_commoditization" in report.macro_weather_extras
    assert "cf_regime_packet" in report.macro_weather_extras
    assert "bounce_rr" in report.macro_weather_extras
    assert "tavi_costa_mc_teaser" in report.macro_weather_extras
    assert "klement_failure_gap" in report.macro_weather_extras
    assert "macro_damaged_goods" in report.macro_weather_extras
    assert "cf_weekend_depth" in report.macro_weather_extras
    assert "lane_a_overnight" in report.macro_weather_extras
    assert "paid_macro_damaged_goods" in report.macro_weather_extras
    assert "vix_vol_regime" in report.macro_weather_extras
    assert "am_vix_sox_context" in report.macro_weather_extras
    assert "moontower_mixologist" in report.macro_weather_extras
    assert "cf_equity_cliff_teaser" in report.macro_weather_extras
    assert "cme_single_stock_futures" in report.macro_weather_extras
    assert "liquid_to_illiquid_iv_map" in report.macro_weather_extras
    assert "arxiv_2607_19030" in report.macro_weather_extras
    assert "hf_fragile_positioning" in report.macro_weather_extras
    assert "treasury_compression_teaser" in report.macro_weather_extras
    assert "robinhood_chain" in report.macro_weather_extras
    assert "caution_stack" in report.macro_weather_extras
    assert "ffj_newsflow" in report.macro_weather_extras
    assert "cf_spx_selling_pressure_teaser" in report.macro_weather_extras
    assert "clarity_act_wublock" in report.macro_weather_extras
    assert "aisuite" in report.macro_weather_extras
    assert "cf_crude_positioning_teaser" in report.macro_weather_extras
    assert "macro_exit_to_the_left" in report.macro_weather_extras
    assert "moontower_hedging" in report.macro_weather_extras
    assert "attention_sv_arxiv_2607_22254" in report.macro_weather_extras
    assert "iv_concavity_arxiv_2607_24680" in report.macro_weather_extras
    assert "lane_b_leaps_hedge_rolls" in report.macro_weather_extras
    assert "macro_korea_wti_fomc" in report.macro_weather_extras
    assert "agentic_discipline" in report.macro_weather_extras
    assert "falcon_marketing_stats" in report.macro_weather_extras
    assert "agentic_handoff" in report.macro_weather_extras
    assert "contrast_vs_macro_charts" in report.macro_weather_extras
    assert "cf_warsh_equity_risk" in report.macro_weather_extras
    assert "guruwatcher" in report.macro_weather_extras
    assert "wublock_term_premium" in report.macro_weather_extras
    assert "watch_list" in report.macro_weather_extras
    assert "korea_ai_hardware_liquidation" in report.macro_weather_extras
    assert "macro_memory_unwind" in report.macro_weather_extras
    assert "risk_markers" in report.macro_weather_extras
    assert "wublock_weekly" in report.macro_weather_extras
    assert "cf_warsh_video" in report.macro_weather_extras
    assert "ivs_diffusion_saam_arxiv_2607_29220" in report.macro_weather_extras
    assert "moontower_sound_of_inevitability" in report.macro_weather_extras
    assert "cf_warsh_bessent_misdirection" in report.macro_weather_extras
    assert "macro_charts_aug3" in report.macro_weather_extras
    assert "cf_misdirection_livestream" in report.macro_weather_extras
    assert "vdv_vix_first_arxiv_2608_01479" in report.macro_weather_extras
    assert "amortizing_lsv_neural_op_arxiv_2608_01217" in report.macro_weather_extras
    assert "macro_aug4_mags_tech_bounce" in report.macro_weather_extras
    assert "nnlci_arxiv_2608_02778" in report.macro_weather_extras
    assert "cf_fx_yen_vix_rally_teaser" in report.macro_weather_extras
    assert "macro_aug5_spx_sox_igv" in report.macro_weather_extras
    assert "klement_ai_datacentre_capex" in report.macro_weather_extras
    assert "last_printed_smh_plan" in report.macro_weather_extras
    assert "wublock_july_vc_cefi" in report.macro_weather_extras
    assert "macro_aug6_hard_assets" in report.macro_weather_extras
    assert "cf_global_economy_teaser" in report.macro_weather_extras
    assert "wublock_clarity_act_delay" in report.macro_weather_extras
    assert "heston_weak_form_arxiv_2608_05009" in report.macro_weather_extras
    assert "options_manip_velocity_arxiv_2608_05373" in report.macro_weather_extras
    assert "cf_golden_era_teaser" in report.macro_weather_extras
    assert "amd_taalas_asic_thesis" in report.macro_weather_extras
    assert "wublock_hl_july_volume" in report.macro_weather_extras
    assert "uniswap_pools_robinhood_chain" in report.macro_weather_extras
    assert "etherfi_eigenlayer_exit" in report.macro_weather_extras
    assert "cf_eow_20260808_teaser" in report.macro_weather_extras
    assert "wublock_asia_top10_russia_japan" in report.macro_weather_extras
    assert "constraints" in report.macro_weather_extras
    assert "events" in report.macro_weather_extras
    assert report.macro_weather_extras["lane_a_overnight"]["keep_tight_vs_k228"] is True
    assert (
        report.macro_weather_extras["macro_aug6_hard_assets"][
            "playbook_snapshot_gates_unchanged"
        ]
        is True
    )
    assert (
        report.macro_weather_extras["wublock_clarity_act_delay"][
            "playbook_snapshot_gates_unchanged"
        ]
        is True
    )
    assert report.macro_weather_extras["constraints"]["no_prod_manip_detector"] is True
    assert (
        report.macro_weather_extras["lane_a_overnight"]["no_posture_change_on_teaser"]
        is True
    )
    assert report.macro_weather_extras["constraints"]["no_diffusion_vendor"] is True
    assert report.macro_weather_extras["constraints"]["no_cf_workers_vendor"] is True
    assert report.macro_weather_extras["constraints"]["no_live_auto_calibrator"] is True
    assert (
        report.macro_weather_extras["constraints"]["no_neural_operator_serving"] is True
    )
    assert report.macro_weather_extras["constraints"]["no_live_pricer_wire"] is True
    assert report.macro_weather_extras["constraints"]["no_tabular_llm_prediction"] is True
    assert report.macro_weather_extras["constraints"]["no_auto_lane_size_change"] is True
    assert (
        report.macro_weather_extras["wublock_asia_top10_russia_japan"][
            "playbook_snapshot_gates_unchanged"
        ]
        is True
    )
    assert (
        report.macro_weather_extras["wublock_asia_top10_russia_japan"][
            "no_auto_lane_size_or_overnight_change"
        ]
        is True
    )
