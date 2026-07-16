"""Small bounded parameter sweeps around Lane A knobs (not full factorial)."""

from __future__ import annotations

import logging
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml

from xsp_killer.backtest.engine import BacktestResult, run_backtest
from xsp_killer.backtest.variants import (
    baseline_spec,
    resolve_variant_specs,
    rules_path_for_spec,
)
from xsp_killer.lane_a_variants import (
    DEFAULT_RULES,
    VariantSpec,
    _deep_merge,
    load_base_rules,
)

logger = logging.getLogger("xsp_killer.backtest.sweep")

# Keep grid SMALL — plan budget ≤ ~40 total runs.
AXIS_GRIDS: dict[str, list[dict[str, Any]]] = {
    "dte": [
        {"entry": {"dte_pick": "min", "dte_target": None}},
        {"entry": {"dte_pick": "target", "dte_target": 21}},
        {"entry": {"dte_pick": "target", "dte_target": 28}},
    ],
    "strike": [
        {"entry": {"strike_pick": "atm_only"}},
        {"entry": {"strike_pick": "cheapest_near_atm"}},
        {"entry": {"strike_pick": "otm_one"}},
    ],
    "tp": [
        {"exit": {"take_profit_pct": 0.20}},
        {"exit": {"take_profit_pct": 0.25}},
        {"exit": {"take_profit_pct": 0.40}},
        {"exit": {"take_profit_pct": 0.60}},
    ],
    "sl": [
        {"exit": {"stop_loss_pct": 0.20}},
        {"exit": {"stop_loss_pct": 0.50}},
    ],
    "regime": [
        {"entry": {"regime_gate": "GREEN"}},
        {
            "entry": {"regime_gate": "DIP_BOUNCE"},
            "ta": {
                "entry": {
                    "mode": "bb_bounce",
                    "intraday_enabled": True,
                    "require_vwap_reclaim": True,
                }
            },
        },
    ],
    "swing": [
        {"exit": {"swing_hold": False, "max_hold_dte": 0}},
        {"exit": {"swing_hold": True, "max_hold_dte": 2}},
    ],
}

# Dip-swing base kept for reference / legacy docs (not used by micro-sweeps).
DIP_SWING_BASE_OVERRIDES: dict[str, Any] = {
    "logging": {"logic_version": "xsp_lane_a_bt_dip_base"},
    "entry": {
        "dte_pick": "min",
        "strike_pick": "atm_only",
        "regime_gate": "DIP_BOUNCE",
        "prior_day_spy_positive": False,
    },
    "paper_entry": {"max_open_positions": 3},
    "ta": {
        "entry": {
            "mode": "bb_bounce",
            "intraday_enabled": True,
            "require_vwap_reclaim": True,
        }
    },
    "exit": {
        "take_profit_pct": 0.40,
        "stop_loss_pct": 0.50,
        "require_upper_bb_for_take_profit": False,
        "swing_hold": True,
        "max_hold_dte": 2,
    },
}

# 28 DTE ATM cluster base (least-bad on UW BT 2026-07-16). Micro-sweeps center here.
BASE_28DTE_ATM_OVERRIDES: dict[str, Any] = {
    "logging": {"logic_version": "xsp_lane_a_bt_28dte_atm_base"},
    "entry": {
        "dte_pick": "target",
        "dte_target": 28,
        "strike_pick": "atm_only",
        "regime_gate": "GREEN",
        "prior_day_spy_positive": False,
    },
    "paper_entry": {"max_open_positions": 1},
    "ta": {
        "entry": {
            "mode": "close_window_only",
            "intraday_enabled": False,
            "require_vwap_reclaim": False,
        }
    },
    "exit": {
        "take_profit_pct": 0.10,
        "stop_loss_pct": 0.20,
        "require_upper_bb_for_take_profit": False,
        "swing_hold": False,
        "max_hold_dte": 0,
    },
}


def parse_sweep_axes(raw: str | None) -> list[str]:
    if not raw:
        return []
    axes = []
    for part in raw.split(","):
        key = part.strip().lower()
        if not key:
            continue
        if key not in AXIS_GRIDS:
            raise ValueError(
                f"unknown sweep axis {key!r}; choose from {sorted(AXIS_GRIDS)}"
            )
        axes.append(key)
    return axes


def _spec_from_overrides(
    variant_id: str, overrides: dict[str, Any], description: str = ""
) -> VariantSpec:
    return VariantSpec(
        variant_id=variant_id,
        description=description or variant_id,
        active=True,
        overrides=overrides,
    )


def build_sweep_specs(axes: Iterable[str]) -> list[VariantSpec]:
    """One-axis micro-sweep around the 28 DTE ATM base (not full factorial)."""
    specs: list[VariantSpec] = []
    for axis in axes:
        grid = AXIS_GRIDS[axis]
        for j, patch in enumerate(grid):
            merged = _deep_merge(deepcopy(BASE_28DTE_ATM_OVERRIDES), patch)
            # stamp logic_version
            logging_cfg = merged.setdefault("logging", {})
            label = _axis_label(axis, patch)
            vid = f"sweep_{axis}_{label}"
            logging_cfg["logic_version"] = f"xsp_lane_a_{vid}"
            specs.append(
                _spec_from_overrides(
                    vid, merged, description=f"sweep axis={axis} {label}"
                )
            )
            _ = j
    return specs


def _axis_label(axis: str, patch: dict[str, Any]) -> str:
    if axis == "dte":
        e = patch.get("entry") or {}
        if e.get("dte_pick") == "min":
            return "min14"
        return f"t{e.get('dte_target')}"
    if axis == "strike":
        return str((patch.get("entry") or {}).get("strike_pick", "atm"))
    if axis == "tp":
        v = float((patch.get("exit") or {}).get("take_profit_pct", 0))
        return f"tp{int(round(v * 100))}"
    if axis == "sl":
        v = float((patch.get("exit") or {}).get("stop_loss_pct", 0))
        return f"sl{int(round(v * 100))}"
    if axis == "regime":
        return str((patch.get("entry") or {}).get("regime_gate", "GREEN")).lower()
    if axis == "swing":
        on = bool((patch.get("exit") or {}).get("swing_hold"))
        return "on" if on else "off"
    return "x"


def run_variant_sweep(
    bars: pd.DataFrame,
    *,
    variants: str = "active",
    sweep_axes: list[str] | None = None,
    variants_config: Path | None = None,
    include_baseline: bool = True,
    iv_seed: float = 0.18,
    use_bs: bool = True,
    source: str = "fixture",
    tmp_dir: Path | None = None,
) -> list[BacktestResult]:
    """Run active keepers (+ optional one-axis sweeps) over the same bars."""
    specs = resolve_variant_specs(
        variants=variants, variants_config=variants_config
    )
    if include_baseline and not any(s.variant_id == "v2_baseline_prod" for s in specs):
        # Only inject baseline when requesting active/all keepers, not explicit ids
        if variants in ("active", "all") or variants is None:
            specs = [baseline_spec(), *specs]

    if sweep_axes:
        specs = list(specs) + build_sweep_specs(sweep_axes)

    # Cap runaway grids
    if len(specs) > 40:
        logger.warning(
            "sweep produced %d runs; truncating to 40 (plan budget)", len(specs)
        )
        specs = specs[:40]

    results: list[BacktestResult] = []
    cache_dir = tmp_dir
    own_tmp = None
    if cache_dir is None:
        own_tmp = tempfile.TemporaryDirectory(prefix="xsp_bt_rules_")
        cache_dir = Path(own_tmp.name)

    try:
        for spec in specs:
            rpath = rules_path_for_spec(spec, tmp_dir=cache_dir)
            logger.info("backtest run %s", spec.variant_id)
            res = run_backtest(
                bars,
                rpath,
                variant_id=spec.variant_id,
                iv_seed=iv_seed,
                use_bs=use_bs,
                source=source,
            )
            results.append(res)
    finally:
        if own_tmp is not None:
            own_tmp.cleanup()

    return results


def write_merged_rules_dict(overrides: dict[str, Any], path: Path) -> Path:
    """Test helper: merge overrides onto base rules and dump YAML."""
    merged = _deep_merge(load_base_rules(), overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")
    return path


# Silence unused import lint for DEFAULT_RULES (useful for callers/tests)
_ = DEFAULT_RULES
