"""Tests for K155 macro weather operator notes."""

from __future__ import annotations

from pathlib import Path

import yaml

from xsp_killer.macro_weather_notes import (
    USDJPY_ZONE,
    build_macro_weather_extras,
    build_monitor_macro_weather_extras,
    conviction_journal_fields,
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
    assert extras["sentiment_capitulation"]["no_chase_spmo_semis_into_lane_a_overnight"] is True


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
    assert notes["cf_weekend_depth"][
        "view_changed_unwind_carry_weekend_depth"
    ] is True
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
    assert extras["cf_weekend_depth"][
        "view_changed_unwind_carry_weekend_depth"
    ] is True
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
    assert extras["cf_weekend_depth"][
        "view_changed_unwind_carry_weekend_depth"
    ] is True
    # k182 overwrites lane_a_overnight with keep_tight_vs_k178
    assert extras["lane_a_overnight"]["keep_tight_vs_k178"] is True
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
    # k182 overwrites lane_a_overnight with keep_tight_vs_k178
    assert extras["lane_a_overnight"]["keep_tight_vs_k178"] is True
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
    assert extras["lane_a_overnight"]["keep_tight_vs_k178"] is True
    assert extras["constraints"]["no_integral_solver"] is True
    assert extras["constraints"]["no_strategy_code"] is True


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
    assert "constraints" in report.macro_weather_extras
    assert "events" in report.macro_weather_extras
