"""Stage A: long-history regime and trading-session hold discovery.

Read-only research module. Never flips LIVE_*, never writes secrets.
Hold caps live on StageASpec (not as an unknown live YAML key).
"""

from __future__ import annotations

import logging
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from xsp_killer.backtest.engine import BacktestResult, TradeRow, run_backtest
from xsp_killer.backtest.optimize import (
    GridBudgetError,
    _mean_pnl,
    _median_pnl,
    _summarize_split,
    _win_pct,
    partition_trades_by_split,
)
from xsp_killer.backtest.report import mcpt
from xsp_killer.backtest.sweep import BASE_28DTE_ATM_OVERRIDES, _spec_from_overrides
from xsp_killer.backtest.variants import rules_path_for_spec
from xsp_killer.lane_a_variants import VariantSpec, _deep_merge

logger = logging.getLogger("xsp_killer.backtest.regime_hold")

# Re-export for callers / tests
__all__ = [
    "GridBudgetError",
    "HOLD_SESSIONS_GRID",
    "IV_SEEDS",
    "SLIPPAGE_MULTS",
    "StageASpec",
    "build_stage_a_grid",
    "edge_confirmed",
    "recommended_regime_hold_yaml",
    "refine_stage_a",
    "run_sensitivity",
    "run_stage_a",
    "stable_windows",
]

HOLD_SESSIONS_GRID = (1, 2, 3, 5, 10)
IV_SEEDS = (0.14, 0.18, 0.22, 0.28)
SLIPPAGE_MULTS = (1.0, 1.5, 2.0)

MAX_GRID_DEFAULT = 240

# Coarse Stage A fixes DTE/TP/SL; refine varies them later.
COARSE_DTE = 28
COARSE_TP = 0.20
COARSE_SL = 0.30

REFINE_DTE = (21, 28, 35)
REFINE_TP = (0.10, 0.15, 0.20, 0.25)
REFINE_SL = (0.20, 0.30, 0.40)

# Explicit unique regime cells: GREEN once; GYB fraction × bounce (no GREEN dups).
REGIMES: tuple[tuple[str, float | None, bool | None, str], ...] = (
    ("GREEN", None, None, "green"),
    *tuple(
        (
            "GREEN_OR_YELLOW_BOUNCE",
            frac,
            bounce,
            f"gyb{int(frac * 100)}b{int(bounce)}",
        )
        for frac in (0.40, 0.50, 0.60, 0.75)
        for bounce in (False, True)
    ),
)

PRIOR_MODES: tuple[tuple[bool, str], ...] = (
    (False, "p0"),
    (True, "p1"),
)


@dataclass
class StageASpec:
    """VariantSpec plus session-hold cap (not a live YAML key)."""

    spec: VariantSpec
    max_hold_sessions: int

    @property
    def variant_id(self) -> str:
        return self.spec.variant_id

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def active(self) -> bool:
        return self.spec.active

    @property
    def overrides(self) -> dict[str, Any]:
        return self.spec.overrides


def _vid(
    dte: int,
    tp: float,
    sl: float,
    regime_label: str,
    prior_label: str,
    hold: int,
) -> str:
    tp_i = int(round(tp * 100))
    sl_i = int(round(sl * 100))
    return f"rha_dte{dte}_tp{tp_i}_sl{sl_i}_{regime_label}_{prior_label}_h{hold}"


def _patch_for(
    dte: int,
    tp: float,
    sl: float,
    regime_gate: str,
    yellow_frac_min: float | None,
    yellow_require_bounce: bool | None,
    prior_day_spy_positive: bool,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "dte_pick": "target",
        "dte_target": int(dte),
        "strike_pick": "atm_only",
        "regime_gate": regime_gate,
        "prior_day_spy_positive": bool(prior_day_spy_positive),
    }
    if regime_gate == "GREEN_OR_YELLOW_BOUNCE":
        entry["regime_yellow_frac_min"] = float(
            0.50 if yellow_frac_min is None else yellow_frac_min
        )
        entry["regime_yellow_require_bounce"] = bool(
            False if yellow_require_bounce is None else yellow_require_bounce
        )
    return {
        "entry": entry,
        "exit": {
            "take_profit_pct": float(tp),
            "stop_loss_pct": float(sl),
            "require_upper_bb_for_take_profit": False,
            "swing_hold": False,
            "max_hold_dte": 0,
        },
        "ta": {
            "entry": {
                "mode": "close_window_only",
                "intraday_enabled": False,
                "require_vwap_reclaim": False,
            }
        },
    }


def _make_stage_a_spec(
    *,
    dte: int,
    tp: float,
    sl: float,
    regime_gate: str,
    yellow_frac_min: float | None,
    yellow_require_bounce: bool | None,
    regime_label: str,
    prior: bool,
    prior_label: str,
    hold: int,
) -> StageASpec:
    vid = _vid(dte, tp, sl, regime_label, prior_label, hold)
    patch = _patch_for(
        dte, tp, sl, regime_gate, yellow_frac_min, yellow_require_bounce, prior
    )
    merged = _deep_merge(deepcopy(BASE_28DTE_ATM_OVERRIDES), patch)
    logging_cfg = merged.setdefault("logging", {})
    logging_cfg["logic_version"] = f"xsp_lane_a_{vid}"
    prior_word = "positive" if prior else "none"
    desc = (
        f"stageA dte={dte} tp={tp} sl={sl} regime={regime_gate} "
        f"prior={prior_word} hold={hold}"
    )
    return StageASpec(
        spec=_spec_from_overrides(vid, merged, description=desc),
        max_hold_sessions=int(hold),
    )


def build_stage_a_grid(
    *,
    coarse: bool = True,
    allow_large: bool = False,
    max_grid: int = MAX_GRID_DEFAULT,
) -> list[StageASpec]:
    """Bounded coarse Stage A grid: regime × prior × hold at fixed 28/TP20/SL30.

    Raises ``GridBudgetError`` before any backtest runs when over budget.
    """
    if not coarse:
        # Fine grid is produced via refine_stage_a from survivors.
        raise ValueError("fine grid is produced by refine_stage_a, not build_stage_a_grid")

    n = len(REGIMES) * len(PRIOR_MODES) * len(HOLD_SESSIONS_GRID)
    if n > max_grid and not allow_large:
        raise GridBudgetError(
            f"stage A coarse grid size {n} exceeds budget {max_grid}; "
            "pass allow_large=True to override (not recommended)"
        )

    cells: list[StageASpec] = []
    seen: set[str] = set()
    for reg, (prior, plabel), hold in product(REGIMES, PRIOR_MODES, HOLD_SESSIONS_GRID):
        gate, yfrac, ybounce, rlabel = reg
        cell = _make_stage_a_spec(
            dte=COARSE_DTE,
            tp=COARSE_TP,
            sl=COARSE_SL,
            regime_gate=gate,
            yellow_frac_min=yfrac,
            yellow_require_bounce=ybounce,
            regime_label=rlabel,
            prior=prior,
            prior_label=plabel,
            hold=int(hold),
        )
        if cell.variant_id in seen:
            continue
        seen.add(cell.variant_id)
        cells.append(cell)
    return cells


def _regime_label_from_entry(entry: dict[str, Any]) -> str:
    gate = str(entry.get("regime_gate") or "GREEN").upper()
    if gate != "GREEN_OR_YELLOW_BOUNCE":
        return "green"
    frac = float(entry.get("regime_yellow_frac_min") or 0.50)
    bounce = bool(entry.get("regime_yellow_require_bounce") or False)
    return f"gyb{int(round(frac * 100))}b{int(bounce)}"


def _row_seed_fields(row: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize seed fields from ranking row and/or overrides."""
    ov = overrides or {}
    entry = ov.get("entry") or {}
    exit_cfg = ov.get("exit") or {}
    gate = str(
        row.get("regime_gate") or entry.get("regime_gate") or "GREEN"
    ).upper()
    yfrac = row.get("regime_yellow_frac_min", entry.get("regime_yellow_frac_min"))
    ybounce = row.get(
        "regime_yellow_require_bounce", entry.get("regime_yellow_require_bounce")
    )
    prior = bool(
        row.get("prior_day_spy_positive", entry.get("prior_day_spy_positive", False))
    )
    hold = int(row.get("max_hold_sessions") or 1)
    dte = int(row.get("dte_target") or entry.get("dte_target") or COARSE_DTE)
    tp = float(
        row.get("take_profit_pct")
        if row.get("take_profit_pct") is not None
        else (exit_cfg.get("take_profit_pct") or COARSE_TP)
    )
    sl = float(
        row.get("stop_loss_pct")
        if row.get("stop_loss_pct") is not None
        else (exit_cfg.get("stop_loss_pct") or COARSE_SL)
    )
    return {
        "regime_gate": gate,
        "regime_yellow_frac_min": float(yfrac) if yfrac is not None else None,
        "regime_yellow_require_bounce": (
            bool(ybounce) if ybounce is not None else None
        ),
        "prior_day_spy_positive": prior,
        "max_hold_sessions": hold,
        "dte_target": dte,
        "take_profit_pct": tp,
        "stop_loss_pct": sl,
    }


def refine_stage_a(
    seed_rows: list[dict[str, Any]],
    *,
    existing_ids: set[str],
    budget_remaining: int = 120,
    allow_large: bool = False,
    max_grid: int = MAX_GRID_DEFAULT,
    overrides_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[StageASpec]:
    """Refine top survivors over DTE/TP/SL while preserving regime/prior/hold.

    Bounded and deduped before any execution. Raises ``GridBudgetError`` if the
    planned refine batch would exceed ``max_grid`` without ``allow_large``.
    """
    if budget_remaining <= 0 or not seed_rows:
        return []

    ov_map = overrides_by_id or {}
    extra: list[StageASpec] = []
    seen = set(existing_ids)

    for row in seed_rows:
        if len(extra) >= budget_remaining:
            break
        vid0 = str(row.get("variant_id") or "")
        fields = _row_seed_fields(row, ov_map.get(vid0))
        gate = fields["regime_gate"]
        yfrac = fields["regime_yellow_frac_min"]
        ybounce = fields["regime_yellow_require_bounce"]
        prior = fields["prior_day_spy_positive"]
        hold = fields["max_hold_sessions"]
        rlabel = _regime_label_from_entry(
            {
                "regime_gate": gate,
                "regime_yellow_frac_min": yfrac,
                "regime_yellow_require_bounce": ybounce,
            }
        )
        plabel = "p1" if prior else "p0"

        for dte, tp, sl in product(REFINE_DTE, REFINE_TP, REFINE_SL):
            if len(extra) >= budget_remaining:
                break
            # Skip exact coarse seed (already evaluated)
            if (
                int(dte) == int(fields["dte_target"])
                and float(tp) == float(fields["take_profit_pct"])
                and float(sl) == float(fields["stop_loss_pct"])
            ):
                continue
            cell = _make_stage_a_spec(
                dte=int(dte),
                tp=float(tp),
                sl=float(sl),
                regime_gate=gate,
                yellow_frac_min=yfrac,
                yellow_require_bounce=ybounce,
                regime_label=rlabel,
                prior=prior,
                prior_label=plabel,
                hold=int(hold),
            )
            if cell.variant_id in seen:
                continue
            seen.add(cell.variant_id)
            extra.append(cell)

    planned_total = len(existing_ids) + len(extra)
    if planned_total > max_grid and not allow_large:
        raise GridBudgetError(
            f"stage A refine would exceed budget {max_grid} "
            f"(existing={len(existing_ids)} + refine={len(extra)} = {planned_total}); "
            "pass allow_large=True or lower budget_remaining"
        )
    return extra


def _enrich_row(
    row: dict[str, Any],
    *,
    cell: StageASpec,
    train: list[TradeRow],
    holdout: list[TradeRow],
) -> dict[str, Any]:
    entry = cell.overrides.get("entry") or {}
    exit_cfg = cell.overrides.get("exit") or {}
    train_mean = float(row.get("train_mean_net_pnl_pct") or 0.0)
    hold_mean = float(row.get("holdout_mean_net_pnl_pct") or 0.0)
    row["max_hold_sessions"] = int(cell.max_hold_sessions)
    row["regime_gate"] = str(entry.get("regime_gate") or "GREEN")
    row["regime_yellow_frac_min"] = entry.get("regime_yellow_frac_min")
    row["regime_yellow_require_bounce"] = entry.get("regime_yellow_require_bounce")
    row["prior_day_spy_positive"] = bool(entry.get("prior_day_spy_positive", False))
    row["dte_target"] = int(entry.get("dte_target") or COARSE_DTE)
    row["take_profit_pct"] = float(exit_cfg.get("take_profit_pct") or COARSE_TP)
    row["stop_loss_pct"] = float(exit_cfg.get("stop_loss_pct") or COARSE_SL)
    row["stability_gap"] = round(abs(train_mean - hold_mean), 6)
    row["full_mean_net_pnl_pct"] = round(_mean_pnl(train + holdout), 6)
    row["full_median_net_pnl_pct"] = round(_median_pnl(train + holdout), 6)
    row["full_win_pct"] = _win_pct(train + holdout)
    return row


def _rank_key(r: dict[str, Any]) -> tuple[float, float, int]:
    # holdout mean desc, smaller stability gap, more holdout trades
    return (
        float(r.get("holdout_mean_net_pnl_pct") or 0.0),
        -float(r.get("stability_gap") or 0.0),
        int(r.get("n_holdout") or 0),
    )


def run_stage_a(
    bars: pd.DataFrame,
    *,
    split_frac: float = 0.6,
    min_trades: int = 8,
    iv_seed: float = 0.18,
    source: str = "fixture",
    coarse_to_fine: bool = True,
    top_k: int = 12,
    run_mcpt: bool = False,
    n_perm: int = 1000,
    allow_large: bool = False,
    max_grid: int = MAX_GRID_DEFAULT,
    tmp_dir: Path | None = None,
    mode: str = "fixture",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Coarse (then optional fine) Stage A discovery on daily bars."""
    cells = build_stage_a_grid(coarse=True, allow_large=allow_large, max_grid=max_grid)
    cache_dir = tmp_dir
    own_tmp = None
    if cache_dir is None:
        own_tmp = tempfile.TemporaryDirectory(prefix="xsp_rha_rules_")
        cache_dir = Path(own_tmp.name)

    results_by_id: dict[str, BacktestResult] = {}
    cell_by_id: dict[str, StageASpec] = {}
    overrides_by_id: dict[str, dict[str, Any]] = {}
    split_iso = ""

    def _run_cells(batch: list[StageASpec]) -> None:
        nonlocal split_iso
        for cell in batch:
            rpath = rules_path_for_spec(cell.spec, tmp_dir=cache_dir)
            logger.info(
                "stageA run %s hold=%s", cell.variant_id, cell.max_hold_sessions
            )
            res = run_backtest(
                bars,
                rpath,
                variant_id=cell.variant_id,
                iv_seed=iv_seed,
                use_bs=True,
                source=source,
                max_hold_sessions=cell.max_hold_sessions,
            )
            results_by_id[cell.variant_id] = res
            cell_by_id[cell.variant_id] = cell
            overrides_by_id[cell.variant_id] = deepcopy(cell.overrides)
            if not split_iso and res.trades:
                _, _, split_iso = partition_trades_by_split(
                    res.trades, bars, split_frac=split_frac
                )
        if not split_iso:
            _, _, split_iso = partition_trades_by_split(
                [], bars, split_frac=split_frac
            )

    def _rows_from_results(ids: list[str] | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for vid in ids if ids is not None else list(results_by_id.keys()):
            res = results_by_id[vid]
            cell = cell_by_id[vid]
            train, holdout, _ = partition_trades_by_split(
                res.trades, bars, split_frac=split_frac
            )
            row = _summarize_split(
                train,
                holdout,
                variant_id=vid,
                n_entries_blocked=res.n_entries_blocked,
            )
            row["holdout_pnls"] = [t.net_pnl_pct for t in holdout]
            _enrich_row(row, cell=cell, train=train, holdout=holdout)
            out.append(row)
        out.sort(key=_rank_key, reverse=True)
        return out

    try:
        _run_cells(cells)
        rows = _rows_from_results()

        if coarse_to_fine and rows:
            k_seed = min(int(top_k), len(rows))
            seed_rows = rows[:k_seed]
            existing = set(results_by_id.keys())
            budget_left = max(0, int(max_grid) - len(existing))
            if allow_large:
                budget_left = max(budget_left, 120)
            neighbors = refine_stage_a(
                seed_rows,
                existing_ids=existing,
                budget_remaining=budget_left if not allow_large else min(120, budget_left or 120),
                allow_large=allow_large,
                max_grid=max_grid if not allow_large else max(max_grid, len(existing) + 120),
                overrides_by_id=overrides_by_id,
            )
            if neighbors:
                logger.info("stageA refine: running %d cells", len(neighbors))
                _run_cells(neighbors)
                rows = _rows_from_results()

        # MCPT only on top finalists when enabled
        mcpt_budget = min(int(top_k), len(rows))
        for i, row in enumerate(rows):
            if run_mcpt and i < mcpt_budget:
                pnls = row.get("holdout_pnls") or []
                m = mcpt(pnls, n_perm=int(n_perm))
                row["mcpt"] = m
                row["mcpt_p"] = m.get("p_value")
                row["mcpt_pass_5pct"] = m.get("pass_5pct")
            row.pop("holdout_pnls", None)

        disclaimer = (
            "fidelity=daily_close_proxy: entries use daily close as a close-window "
            "proxy; exits checked once per daily bar (not intraday). Modeled premiums "
            "(BS-lite). Relative ranker only. Does NOT replace paper soak. Live trading "
            "gates untouched. YAML snippet is active:false — human paste only."
        )

        payload: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "source": source,
            "kind": "stage_a_regime_hold",
            "fidelity": "daily_close_proxy",
            "disclaimer": disclaimer,
            "grid": {
                "n_specs": len(results_by_id),
                "coarse_n": len(cells),
                "hold_sessions": list(HOLD_SESSIONS_GRID),
                "coarse_dte": COARSE_DTE,
                "coarse_tp": COARSE_TP,
                "coarse_sl": COARSE_SL,
                "regimes": [r[3] for r in REGIMES],
                "coarse_to_fine": bool(coarse_to_fine),
            },
            "split": {
                "split_frac": float(split_frac),
                "split_ts": split_iso,
                "min_trades": int(min_trades),
            },
            "ranking": rows,
            "top_k_mcpt": mcpt_budget if run_mcpt else 0,
            "meta": meta or {},
        }
        return payload
    finally:
        if own_tmp is not None:
            own_tmp.cleanup()
