"""K155 macro weather operator notes — log-only Lane A monitor enrichment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_K155_NOTES = ROOT / "config" / "k155_operator_notes.yaml"

USDJPY_ZONE = (162.25, 162.50)


def _load_yaml_block(path: Path, key: str) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    block = data.get(key)
    return dict(block) if isinstance(block, dict) else {}


def load_k155_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K155 operator notes from YAML config."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k155")


def load_k158_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K158 operator steals (extends K155) from YAML config."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k158")


def load_k161_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K161 CEV aspiration operator notes (log-only; no solver)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k161")


def load_k162_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K162 Macro Charts sentiment capitulation notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k162")


def load_k167_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K167 Macro Charts SOX/CPI/oil–2YR + Moontower volga notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k167")


def load_k170_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K170 Macro Charts Korea/SOX/DXY + re-industrialization notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k170")


def load_k172_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K172 CF view shift + Asia AI selloff notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k172")


def load_k173_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K173 CF momentum unwind + carry risk map notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k173")


def load_k174_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K174 macro damaged-goods + CF weekend depth notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k174")


def load_k177_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K177 paid damaged-goods + Moontower mixologist notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k177")


def load_k178_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K178 CF equity-cliff teaser notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k178")


def load_k182_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K182 illiquid IV map + HF fragile positioning notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k182")


def load_k191_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K191 treasury compression + Robinhood Chain notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k191")


def load_k193_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K193 FFJ newsflow + SPX selling-pressure teaser notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k193")


def load_k195_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K195 aisuite context + CF crude/positioning teaser notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k195")


def load_k196_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K196 EXIT TO THE LEFT + Moontower hedging + attention SV notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k196")


def load_k198_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K198 IV concavity + Macro Korea/WTI/FOMC regime notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k198")


def load_glitch_falcon_notes(path: Path | None = None) -> dict[str, Any]:
    """Load Glitch Falcon agentic-discipline ops culture notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "glitch_falcon")


def load_k213_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K213 Capital Flows Warsh / equity risk notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k213")


def load_k214_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K214 WuBlock term premium / fiscal-dominance notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k214")


def load_k215_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K215 Macro inflection + WuBlock weekly + Warsh video notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k215")


def load_k219_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K219 IVS SAAM ideas + Moontower + CF Warsh/Bessent notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k219")


def load_k221_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K221 Macro Charts Aug 3 + CF misdirection livestream notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k221")


def load_k222_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K222 VIX-first + amortizing LSV calibration awareness notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k222")


def load_k223_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K223 NNLCI + CF FX teaser + Macro SOX/yields notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k223")


def load_k224_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K224 Klement AI data-centre capex vs earnings boom notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k224")


def load_k225_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K225 Wu July VC + Macro hard-assets regime notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k225")


def load_k226_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K226 CLARITY delay + Heston weak-form + manip velocity notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k226")


def load_k228_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K228 WuBlock HL + Uniswap Pools + ether.fi notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k228")


def load_k229_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K229 Wu Asia TOP10 Russia/Japan regulatory notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k229")


def load_k231_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K231 Donny META/REA + Fed-Warsh week notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k231")


def load_k232_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K232 WuBlock July spot volume regime notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k232")


def load_k233_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K233 Fed Speaks FOMC IV + Wu derivatives volume notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k233")


def load_k234_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K234 Moontower high-IV collar shopping hedge vocabulary notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k234")


def load_k236_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K236 WuBlock July 2026 exchange website traffic notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k236")


def load_k240_notes(path: Path | None = None) -> dict[str, Any]:
    """Load K240 Glitch SPX Talon HITL + Moontower RSSB corr awareness notes (log-only)."""
    return _load_yaml_block(path or DEFAULT_K155_NOTES, "k240")


def build_macro_weather_extras(
    *,
    usdjpy: float | None,
    sofr_curve_note: str | None,
    event_cluster: str | None,
) -> dict[str, Any]:
    """Build log-only macro weather extras for monitor JSON."""
    lo, hi = USDJPY_ZONE
    in_zone = usdjpy is not None and lo <= usdjpy <= hi
    return {
        "usdjpy": usdjpy,
        "usdjpy_zone_lo": lo,
        "usdjpy_zone_hi": hi,
        "usdjpy_in_zone": in_zone,
        "sofr_curve_note": sofr_curve_note,
        "event_cluster": event_cluster,
    }


def conviction_journal_fields(
    *,
    evidence_count: int,
    cross_asset_confirms: int,
    pro_con_balanced: bool,
) -> dict[str, Any]:
    """Trade journal conviction fields; block size-up on balanced pro/con alone."""
    conviction_sufficient = evidence_count >= 2 and cross_asset_confirms >= 1
    block_size_up = pro_con_balanced and not conviction_sufficient
    return {
        "evidence_count": evidence_count,
        "cross_asset_confirms": cross_asset_confirms,
        "pro_con_balanced": pro_con_balanced,
        "conviction_sufficient": conviction_sufficient,
        "block_size_up": block_size_up,
    }


def build_monitor_macro_weather_extras(
    notes: dict[str, Any] | None = None,
    *,
    usdjpy: float | None = None,
    k158_notes: dict[str, Any] | None = None,
    k161_notes: dict[str, Any] | None = None,
    k162_notes: dict[str, Any] | None = None,
    k167_notes: dict[str, Any] | None = None,
    k170_notes: dict[str, Any] | None = None,
    k172_notes: dict[str, Any] | None = None,
    k173_notes: dict[str, Any] | None = None,
    k174_notes: dict[str, Any] | None = None,
    k177_notes: dict[str, Any] | None = None,
    k178_notes: dict[str, Any] | None = None,
    k182_notes: dict[str, Any] | None = None,
    k191_notes: dict[str, Any] | None = None,
    k193_notes: dict[str, Any] | None = None,
    k195_notes: dict[str, Any] | None = None,
    k196_notes: dict[str, Any] | None = None,
    k198_notes: dict[str, Any] | None = None,
    glitch_falcon_notes: dict[str, Any] | None = None,
    k213_notes: dict[str, Any] | None = None,
    k214_notes: dict[str, Any] | None = None,
    k215_notes: dict[str, Any] | None = None,
    k219_notes: dict[str, Any] | None = None,
    k221_notes: dict[str, Any] | None = None,
    k222_notes: dict[str, Any] | None = None,
    k223_notes: dict[str, Any] | None = None,
    k224_notes: dict[str, Any] | None = None,
    k225_notes: dict[str, Any] | None = None,
    k226_notes: dict[str, Any] | None = None,
    k228_notes: dict[str, Any] | None = None,
    k229_notes: dict[str, Any] | None = None,
    k231_notes: dict[str, Any] | None = None,
    k232_notes: dict[str, Any] | None = None,
    k233_notes: dict[str, Any] | None = None,
    k234_notes: dict[str, Any] | None = None,
    k236_notes: dict[str, Any] | None = None,
    k240_notes: dict[str, Any] | None = None,
    notes_path: Path | None = None,
) -> dict[str, Any] | None:
    """Merge K155..K240 + glitch_falcon YAML notes for monitor attachment."""
    path = notes_path or DEFAULT_K155_NOTES
    k155 = notes if notes is not None else load_k155_notes(path)
    if not k155:
        return None

    k158 = k158_notes if k158_notes is not None else load_k158_notes(path)
    k161 = k161_notes if k161_notes is not None else load_k161_notes(path)
    k162 = k162_notes if k162_notes is not None else load_k162_notes(path)
    k167 = k167_notes if k167_notes is not None else load_k167_notes(path)
    k170 = k170_notes if k170_notes is not None else load_k170_notes(path)
    k172 = k172_notes if k172_notes is not None else load_k172_notes(path)
    k173 = k173_notes if k173_notes is not None else load_k173_notes(path)
    k174 = k174_notes if k174_notes is not None else load_k174_notes(path)
    k177 = k177_notes if k177_notes is not None else load_k177_notes(path)
    k178 = k178_notes if k178_notes is not None else load_k178_notes(path)
    k182 = k182_notes if k182_notes is not None else load_k182_notes(path)
    k191 = k191_notes if k191_notes is not None else load_k191_notes(path)
    k193 = k193_notes if k193_notes is not None else load_k193_notes(path)
    k195 = k195_notes if k195_notes is not None else load_k195_notes(path)
    k196 = k196_notes if k196_notes is not None else load_k196_notes(path)
    k198 = k198_notes if k198_notes is not None else load_k198_notes(path)
    glitch_falcon = (
        glitch_falcon_notes
        if glitch_falcon_notes is not None
        else load_glitch_falcon_notes(path)
    )
    k213 = k213_notes if k213_notes is not None else load_k213_notes(path)
    k214 = k214_notes if k214_notes is not None else load_k214_notes(path)
    k215 = k215_notes if k215_notes is not None else load_k215_notes(path)
    k219 = k219_notes if k219_notes is not None else load_k219_notes(path)
    k221 = k221_notes if k221_notes is not None else load_k221_notes(path)
    k222 = k222_notes if k222_notes is not None else load_k222_notes(path)
    k223 = k223_notes if k223_notes is not None else load_k223_notes(path)
    k224 = k224_notes if k224_notes is not None else load_k224_notes(path)
    k225 = k225_notes if k225_notes is not None else load_k225_notes(path)
    k226 = k226_notes if k226_notes is not None else load_k226_notes(path)
    k228 = k228_notes if k228_notes is not None else load_k228_notes(path)
    k229 = k229_notes if k229_notes is not None else load_k229_notes(path)
    k231 = k231_notes if k231_notes is not None else load_k231_notes(path)
    k232 = k232_notes if k232_notes is not None else load_k232_notes(path)
    k233 = k233_notes if k233_notes is not None else load_k233_notes(path)
    k234 = k234_notes if k234_notes is not None else load_k234_notes(path)
    k236 = k236_notes if k236_notes is not None else load_k236_notes(path)
    k240 = k240_notes if k240_notes is not None else load_k240_notes(path)

    sofr = k155.get("sofr_curve")
    sofr_note = sofr.get("note") if isinstance(sofr, dict) else None
    extras = build_macro_weather_extras(
        usdjpy=usdjpy,
        sofr_curve_note=sofr_note,
        event_cluster=str(k155.get("event_cluster") or ""),
    )
    extras["k155_version"] = k155.get("version")
    for key in (
        "events",
        "cme_ssf",
        "fundsmith_sentiment",
        "sox_kospi_watch",
        "usdjpy_zone",
        "macro_weather_snapshot",
        "conviction_journal",
        "vol_edge",
    ):
        if key in k155:
            extras[key] = k155[key]
    if isinstance(sofr, dict):
        extras["sofr_curve"] = sofr

    if k158:
        extras["k158_version"] = k158.get("version")
        for key in (
            "sofr_front_end",
            "fomc_jul29",
            "cpi_skew",
            "japan_yen",
        ):
            if key in k158:
                extras[key] = k158[key]

    if k161:
        extras["k161_version"] = k161.get("version")
        if "cev_aspiration" in k161:
            extras["cev_aspiration"] = k161["cev_aspiration"]

    if k162:
        extras["k162_version"] = k162.get("version")
        if "sentiment_capitulation" in k162:
            extras["sentiment_capitulation"] = k162["sentiment_capitulation"]

    if k167:
        extras["k167_version"] = k167.get("version")
        for key in (
            "oil_vs_2yr",
            "sox_mu_bounce",
            "soft_cpi",
            "moontower_volga",
            "software_igv",
        ):
            if key in k167:
                extras[key] = k167[key]

    if k170:
        extras["k170_version"] = k170.get("version")
        for key in (
            "korea_memory_semis",
            "sox_support",
            "dxy_breakdown",
            "us_reindustrialization",
            "theory_shelf",
            "turbovec",
        ):
            if key in k170:
                extras[key] = k170[key]

    if k172:
        extras["k172_version"] = k172.get("version")
        for key in (
            "cf_view_shift",
            "asia_ai_selloff",
            "lane_a_posture",
            "ai_commoditization",
            "constraints",
        ):
            if key in k172:
                extras[key] = k172[key]

    if k173:
        extras["k173_version"] = k173.get("version")
        for key in (
            "cf_regime_packet",
            "bounce_rr",
            "tavi_costa_mc_teaser",
            "klement_failure_gap",
            "constraints",
        ):
            if key in k173:
                extras[key] = k173[key]

    if k174:
        extras["k174_version"] = k174.get("version")
        for key in (
            "macro_damaged_goods",
            "cf_weekend_depth",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k174:
                extras[key] = k174[key]

    if k177:
        extras["k177_version"] = k177.get("version")
        for key in (
            "paid_macro_damaged_goods",
            "vix_vol_regime",
            "am_vix_sox_context",
            "moontower_mixologist",
            "constraints",
        ):
            if key in k177:
                extras[key] = k177[key]

    if k178:
        extras["k178_version"] = k178.get("version")
        for key in (
            "cf_equity_cliff_teaser",
            "lane_a_overnight",
            "cme_single_stock_futures",
            "constraints",
        ):
            if key in k178:
                extras[key] = k178[key]

    if k182:
        extras["k182_version"] = k182.get("version")
        for key in (
            "liquid_to_illiquid_iv_map",
            "arxiv_2607_19030",
            "hf_fragile_positioning",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k182:
                extras[key] = k182[key]

    if k191:
        extras["k191_version"] = k191.get("version")
        for key in (
            "treasury_compression_teaser",
            "robinhood_chain",
            "caution_stack",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k191:
                extras[key] = k191[key]

    if k193:
        extras["k193_version"] = k193.get("version")
        for key in (
            "ffj_newsflow",
            "cf_spx_selling_pressure_teaser",
            "clarity_act_wublock",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k193:
                extras[key] = k193[key]

    if k195:
        extras["k195_version"] = k195.get("version")
        for key in (
            "aisuite",
            "cf_crude_positioning_teaser",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k195:
                extras[key] = k195[key]

    if k196:
        extras["k196_version"] = k196.get("version")
        for key in (
            "macro_exit_to_the_left",
            "moontower_hedging",
            "attention_sv_arxiv_2607_22254",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k196:
                extras[key] = k196[key]

    if k198:
        extras["k198_version"] = k198.get("version")
        for key in (
            "iv_concavity_arxiv_2607_24680",
            "lane_b_leaps_hedge_rolls",
            "macro_korea_wti_fomc",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k198:
                extras[key] = k198[key]

    if glitch_falcon:
        extras["glitch_falcon_version"] = glitch_falcon.get("version")
        for key in (
            "agentic_discipline",
            "falcon_marketing_stats",
            "agentic_handoff",
            "contrast_vs_macro_charts",
            "lane_a_overnight",
            "constraints",
        ):
            if key in glitch_falcon:
                extras[key] = glitch_falcon[key]

    if k213:
        extras["k213_version"] = k213.get("version")
        for key in (
            "cf_warsh_equity_risk",
            "guruwatcher",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k213:
                extras[key] = k213[key]

    if k214:
        extras["k214_version"] = k214.get("version")
        for key in (
            "wublock_term_premium",
            "watch_list",
            "korea_ai_hardware_liquidation",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k214:
                extras[key] = k214[key]

    if k215:
        extras["k215_version"] = k215.get("version")
        for key in (
            "macro_memory_unwind",
            "risk_markers",
            "wublock_weekly",
            "cf_warsh_video",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k215:
                extras[key] = k215[key]

    if k219:
        extras["k219_version"] = k219.get("version")
        for key in (
            "ivs_diffusion_saam_arxiv_2607_29220",
            "moontower_sound_of_inevitability",
            "cf_warsh_bessent_misdirection",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k219:
                extras[key] = k219[key]

    if k221:
        extras["k221_version"] = k221.get("version")
        for key in (
            "macro_charts_aug3",
            "cf_misdirection_livestream",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k221:
                extras[key] = k221[key]

    if k222:
        extras["k222_version"] = k222.get("version")
        for key in (
            "vdv_vix_first_arxiv_2608_01479",
            "amortizing_lsv_neural_op_arxiv_2608_01217",
            "macro_aug4_mags_tech_bounce",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k222:
                extras[key] = k222[key]

    if k223:
        extras["k223_version"] = k223.get("version")
        for key in (
            "nnlci_arxiv_2608_02778",
            "cf_fx_yen_vix_rally_teaser",
            "macro_aug5_spx_sox_igv",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k223:
                extras[key] = k223[key]

    if k224:
        extras["k224_version"] = k224.get("version")
        for key in (
            "klement_ai_datacentre_capex",
            "last_printed_smh_plan",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k224:
                extras[key] = k224[key]

    if k225:
        extras["k225_version"] = k225.get("version")
        for key in (
            "wublock_july_vc_cefi",
            "macro_aug6_hard_assets",
            "cf_global_economy_teaser",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k225:
                extras[key] = k225[key]

    if k226:
        extras["k226_version"] = k226.get("version")
        for key in (
            "wublock_clarity_act_delay",
            "heston_weak_form_arxiv_2608_05009",
            "options_manip_velocity_arxiv_2608_05373",
            "cf_golden_era_teaser",
            "amd_taalas_asic_thesis",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k226:
                extras[key] = k226[key]

    if k228:
        extras["k228_version"] = k228.get("version")
        for key in (
            "wublock_hl_july_volume",
            "uniswap_pools_robinhood_chain",
            "etherfi_eigenlayer_exit",
            "cf_eow_20260808_teaser",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k228:
                extras[key] = k228[key]

    if k229:
        extras["k229_version"] = k229.get("version")
        for key in (
            "wublock_asia_top10_russia_japan",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k229:
                extras[key] = k229[key]

    if k231:
        extras["k231_version"] = k231.get("version")
        for key in (
            "needs_verification",
            "fed_warsh_week",
            "hot_money_rotation",
            "meta_spot_watch_only",
            "rea_rare_earth_sentiment_only",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k231:
                extras[key] = k231[key]

    if k232:
        extras["k232_version"] = k232.get("version")
        for key in (
            "needs_verification",
            "wublock_july_spot_volume",
            "relative_strength_weakness",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k232:
                extras[key] = k232[key]

    if k233:
        extras["k233_version"] = k233.get("version")
        for key in (
            "fed_speaks_fomc_iv_surface_arxiv_2608_10693",
            "wublock_july_derivatives_volume",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k233:
                extras[key] = k233[key]

    if k234:
        extras["k234_version"] = k234.get("version")
        for key in (
            "moontower_high_iv_collar_shopping",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k234:
                extras[key] = k234[key]

    if k236:
        extras["k236_version"] = k236.get("version")
        for key in (
            "wublock_july_exchange_website_traffic",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k236:
                extras[key] = k236[key]

    if k240:
        extras["k240_version"] = k240.get("version")
        for key in (
            "glitchspx_talon_hitl",
            "moontower_rssb_corr_awareness",
            "hitl_watch_policy",
            "lane_a_overnight",
            "constraints",
        ):
            if key in k240:
                extras[key] = k240[key]

    return extras


def maybe_enrich_with_muse_spark(prompt: str) -> dict[str, Any] | None:
    """Optional log-only Muse Spark enrichment when K157 spike is enabled."""
    from xsp_killer.muse_spark_spike import (
        muse_spark_enabled,
        run_macro_research_enrichment,
    )

    if not muse_spark_enabled():
        return None
    return run_macro_research_enrichment(prompt)


def maybe_log_fable_spike(
    task_id: str,
    *,
    baseline_tokens: int,
    spike_tokens: int,
    diff_touches_prod: bool = False,
    cross_vendor_review_done: bool = False,
) -> dict[str, Any] | None:
    """Optional log-only Fable Advisor spike when K159 is enabled."""
    from xsp_killer.fable_advisor_spike import (
        fable_advisor_enabled,
        run_brief_iteration_spike,
    )

    if not fable_advisor_enabled():
        return None
    return run_brief_iteration_spike(
        task_id,
        baseline_tokens=baseline_tokens,
        spike_tokens=spike_tokens,
        diff_touches_prod=diff_touches_prod,
        cross_vendor_review_done=cross_vendor_review_done,
    )
