"""Resolve Lane A variant configs for backtest (wraps existing merge logic)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xsp_killer.lane_a_variants import (
    DEFAULT_VARIANTS_CONFIG,
    VariantSpec,
    load_variant_specs,
    merged_rules_path,
)


def resolve_variant_specs(
    *,
    variants: str = "active",
    variants_config: Path | None = None,
    variant_ids: list[str] | None = None,
) -> list[VariantSpec]:
    """Load variant specs.

    *variants*:
      - ``active`` — only ``active: true`` keepers
      - ``all`` — every defined variant
      - comma-separated ids — explicit list
    """
    specs = load_variant_specs(variants_config or DEFAULT_VARIANTS_CONFIG)
    if variant_ids:
        want = {v.strip() for v in variant_ids if v.strip()}
        return [s for s in specs if s.variant_id in want]
    key = (variants or "active").strip().lower()
    if key == "all":
        return specs
    if key == "active":
        return [s for s in specs if s.active]
    # treat as comma-separated ids
    want = {p.strip() for p in key.split(",") if p.strip()}
    if want:
        return [s for s in specs if s.variant_id in want]
    return [s for s in specs if s.active]


def rules_path_for_spec(
    spec: VariantSpec, *, tmp_dir: Path | None = None
) -> Path:
    """Deep-merge overrides onto ``lane_a_rules.yaml`` via existing resolver."""
    return merged_rules_path(spec, tmp_dir=tmp_dir)


def baseline_spec() -> VariantSpec:
    """Synthetic 'baseline' with empty overrides (production rules as-is)."""
    return VariantSpec(
        variant_id="v2_baseline_prod",
        description="Production lane_a_rules.yaml (no overrides)",
        active=True,
        overrides={},
    )


def entry_knobs_from_rules_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Extract entry/exit knobs used by the backtest engine."""
    entry = data.get("entry") or {}
    exit_cfg = data.get("exit") or {}
    paper = data.get("paper_entry") or {}
    ta = data.get("ta") or {}
    ta_entry = ta.get("entry") or {}
    return {
        "dte_min": int(entry.get("dte_min", 14)),
        "dte_max": int(entry.get("dte_max", 60)),
        "dte_pick": str(entry.get("dte_pick", "min")).strip().lower(),
        "dte_target": int(entry["dte_target"])
        if entry.get("dte_target") is not None
        else None,
        "strike_pick": str(entry.get("strike_pick", "cheapest_near_atm"))
        .strip()
        .lower(),
        "regime_gate": str(entry.get("regime_gate", "GREEN")).strip().upper(),
        "prior_day_spy_positive": bool(entry.get("prior_day_spy_positive", False)),
        "regime_yellow_frac_min": float(entry.get("regime_yellow_frac_min", 0.75)),
        "regime_yellow_require_bounce": bool(
            entry.get("regime_yellow_require_bounce", True)
        ),
        "max_open_positions": int(paper.get("max_open_positions", 1)),
        "quantity": float(paper.get("quantity", 1)),
        "ta_entry_mode": str(ta_entry.get("mode", "close_window_only")),
        "intraday_entry_enabled": bool(ta_entry.get("intraday_enabled", False)),
        "require_vwap_reclaim": bool(ta_entry.get("require_vwap_reclaim", False)),
        "stop_loss_pct": float(exit_cfg.get("stop_loss_pct", 0.20)),
        "take_profit_pct": float(exit_cfg.get("take_profit_pct", 0.20)),
        "swing_hold": bool(exit_cfg.get("swing_hold", False)),
        "max_hold_dte": int(exit_cfg.get("max_hold_dte", 0)),
        "require_upper_bb_for_take_profit": bool(
            exit_cfg.get("require_upper_bb_for_take_profit", True)
        ),
    }
