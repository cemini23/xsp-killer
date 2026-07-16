"""Stage A: long-history regime and trading-session hold discovery.

Read-only research module. Never flips LIVE_*, never writes secrets.
Hold caps live on StageASpec (not as an unknown live YAML key).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from itertools import product
from typing import Any

from xsp_killer.backtest.optimize import GridBudgetError
from xsp_killer.backtest.sweep import BASE_28DTE_ATM_OVERRIDES, _spec_from_overrides
from xsp_killer.lane_a_variants import VariantSpec, _deep_merge

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
