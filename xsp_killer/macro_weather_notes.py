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
    notes_path: Path | None = None,
) -> dict[str, Any] | None:
    """Merge K155/K158/K161/K162/K167 YAML notes with runtime extras for monitor attachment."""
    path = notes_path or DEFAULT_K155_NOTES
    k155 = notes if notes is not None else load_k155_notes(path)
    if not k155:
        return None

    k158 = k158_notes if k158_notes is not None else load_k158_notes(path)
    k161 = k161_notes if k161_notes is not None else load_k161_notes(path)
    k162 = k162_notes if k162_notes is not None else load_k162_notes(path)
    k167 = k167_notes if k167_notes is not None else load_k167_notes(path)

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

    return extras


def maybe_enrich_with_muse_spark(prompt: str) -> dict[str, Any] | None:
    """Optional log-only Muse Spark enrichment when K157 spike is enabled."""
    from xsp_killer.muse_spark_spike import muse_spark_enabled, run_macro_research_enrichment

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
    from xsp_killer.fable_advisor_spike import fable_advisor_enabled, run_brief_iteration_spike

    if not fable_advisor_enabled():
        return None
    return run_brief_iteration_spike(
        task_id,
        baseline_tokens=baseline_tokens,
        spike_tokens=spike_tokens,
        diff_touches_prod=diff_touches_prod,
        cross_vendor_review_done=cross_vendor_review_done,
    )
