"""Centered factorial search around 28 DTE ATM for Lane A.

Train/holdout split + holdout ranking + MCPT on top-K only.
Read-only research tool — never flips LIVE_*, never writes secrets.
"""

from __future__ import annotations

import json
import logging
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd
import yaml

from xsp_killer.backtest.engine import BacktestResult, TradeRow, run_backtest
from xsp_killer.backtest.report import mcpt
from xsp_killer.backtest.sweep import BASE_28DTE_ATM_OVERRIDES, _spec_from_overrides
from xsp_killer.backtest.variants import rules_path_for_spec
from xsp_killer.lane_a_variants import VariantSpec, _deep_merge

logger = logging.getLogger("xsp_killer.backtest.optimize")

# Hard budget: full factorial is 3×4×3×2 = 72 (≤ 80).
MAX_GRID_DEFAULT = 80

DTE_GRID = (21, 28, 35)
TP_GRID = (0.08, 0.10, 0.15, 0.20)
SL_GRID = (0.15, 0.20, 0.30)
# (regime_gate, yellow_frac_min, yellow_require_bounce, label)
REGIME_GRID: tuple[tuple[str, float | None, bool | None, str], ...] = (
    ("GREEN", None, None, "green"),
    ("GREEN_OR_YELLOW_BOUNCE", 0.50, False, "gyb"),
)


class GridBudgetError(ValueError):
    """Raised when the optimize grid exceeds the budget without --allow-large."""


def _vid(dte: int, tp: float, sl: float, regime_label: str) -> str:
    tp_i = int(round(tp * 100))
    sl_i = int(round(sl * 100))
    return f"opt_dte{dte}_tp{tp_i}_sl{sl_i}_{regime_label}"


def _patch_for(
    dte: int,
    tp: float,
    sl: float,
    regime_gate: str,
    yellow_frac_min: float | None,
    yellow_require_bounce: bool | None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "dte_pick": "target",
        "dte_target": int(dte),
        "strike_pick": "atm_only",
        "regime_gate": regime_gate,
        "prior_day_spy_positive": False,
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


def build_centered_grid(
    *,
    allow_large: bool = False,
    max_grid: int = MAX_GRID_DEFAULT,
    dtes: tuple[int, ...] | list[int] | None = None,
    tps: tuple[float, ...] | list[float] | None = None,
    sls: tuple[float, ...] | list[float] | None = None,
    regimes: tuple[tuple[str, float | None, bool | None, str], ...] | None = None,
) -> list[VariantSpec]:
    """Full factorial around ``BASE_28DTE_ATM_OVERRIDES`` (default 72 cells).

    Raises ``GridBudgetError`` if ``len(grid) > max_grid`` and not ``allow_large``.
    Strike axis is intentionally excluded (atm_only ≡ cheapest_near_atm offline).
    """
    dte_vals = tuple(dtes) if dtes is not None else DTE_GRID
    tp_vals = tuple(tps) if tps is not None else TP_GRID
    sl_vals = tuple(sls) if sls is not None else SL_GRID
    regime_vals = regimes if regimes is not None else REGIME_GRID

    n = len(dte_vals) * len(tp_vals) * len(sl_vals) * len(regime_vals)
    if n > max_grid and not allow_large:
        raise GridBudgetError(
            f"optimize grid size {n} exceeds budget {max_grid}; "
            "pass --allow-large to override (not recommended)"
        )

    specs: list[VariantSpec] = []
    seen: set[str] = set()
    for dte, tp, sl, reg in product(dte_vals, tp_vals, sl_vals, regime_vals):
        gate, yfrac, ybounce, rlabel = reg
        vid = _vid(int(dte), float(tp), float(sl), rlabel)
        if vid in seen:
            continue
        seen.add(vid)
        patch = _patch_for(int(dte), float(tp), float(sl), gate, yfrac, ybounce)
        merged = _deep_merge(deepcopy(BASE_28DTE_ATM_OVERRIDES), patch)
        logging_cfg = merged.setdefault("logging", {})
        logging_cfg["logic_version"] = f"xsp_lane_a_{vid}"
        specs.append(
            _spec_from_overrides(
                vid,
                merged,
                description=(
                    f"opt dte={dte} tp={tp} sl={sl} regime={gate}"
                ),
            )
        )
    return specs


def build_refine_neighbors(
    seed_specs: list[VariantSpec],
    *,
    existing_ids: set[str],
    allow_large: bool = False,
    max_grid: int = MAX_GRID_DEFAULT,
    budget_remaining: int = 8,
) -> list[VariantSpec]:
    """±1-step neighbor cells around seed survivors (off-grid DTE/TP/SL steps)."""
    if budget_remaining <= 0:
        return []

    extra: list[VariantSpec] = []
    for seed in seed_specs:
        ov = seed.overrides or {}
        entry = ov.get("entry") or {}
        exit_cfg = ov.get("exit") or {}
        dte = int(entry.get("dte_target") or 28)
        tp = float(exit_cfg.get("take_profit_pct") or 0.10)
        sl = float(exit_cfg.get("stop_loss_pct") or 0.20)
        gate = str(entry.get("regime_gate") or "GREEN").upper()
        yfrac = entry.get("regime_yellow_frac_min")
        ybounce = entry.get("regime_yellow_require_bounce")
        rlabel = "gyb" if gate == "GREEN_OR_YELLOW_BOUNCE" else "green"

        neighbor_dtes = sorted({dte, dte - 7, dte + 7})
        neighbor_tps = sorted({round(tp, 4), round(tp - 0.02, 4), round(tp + 0.02, 4)})
        neighbor_sls = sorted({round(sl, 4), round(sl - 0.05, 4), round(sl + 0.05, 4)})

        for nd, ntp, nsl in product(neighbor_dtes, neighbor_tps, neighbor_sls):
            if nd < 7 or nd > 60 or ntp <= 0 or nsl <= 0:
                continue
            if nd == dte and ntp == tp and nsl == sl:
                continue
            vid = _vid(int(nd), float(ntp), float(nsl), rlabel)
            if vid in existing_ids:
                continue
            if len(extra) >= budget_remaining:
                break
            patch = _patch_for(
                int(nd),
                float(ntp),
                float(nsl),
                gate,
                float(yfrac) if yfrac is not None else None,
                bool(ybounce) if ybounce is not None else None,
            )
            merged = _deep_merge(deepcopy(BASE_28DTE_ATM_OVERRIDES), patch)
            logging_cfg = merged.setdefault("logging", {})
            logging_cfg["logic_version"] = f"xsp_lane_a_{vid}"
            extra.append(
                _spec_from_overrides(
                    vid,
                    merged,
                    description=f"refine neighbor of {seed.variant_id}",
                )
            )
            existing_ids.add(vid)
        if len(extra) >= budget_remaining:
            break

    total = len(existing_ids)
    # existing_ids already includes base; extra is new only
    if total > max_grid and not allow_large:
        raise GridBudgetError(
            f"refine would exceed budget {max_grid} (total ids {total}); "
            "pass --allow-large or drop --refine"
        )
    return extra


def partition_trades_by_split(
    trades: list[TradeRow],
    bars: pd.DataFrame,
    *,
    split_frac: float = 0.6,
) -> tuple[list[TradeRow], list[TradeRow], str]:
    """Split trades into train / holdout by bar date-range cut on entry_ts.

    Train = entries on or before the timestamp at ``split_frac`` of the bar
    index; holdout = later entries.
    """
    if not 0.0 < float(split_frac) < 1.0:
        raise ValueError(f"split_frac must be in (0, 1), got {split_frac}")
    if bars is None or len(bars) == 0:
        return [], list(trades), ""

    cut_i = int(len(bars) * float(split_frac))
    cut_i = max(1, min(cut_i, len(bars) - 1))
    split_ts = pd.Timestamp(bars.index[cut_i - 1])
    # Normalize for string comparison with TradeRow.entry_ts
    if split_ts.tzinfo is None:
        split_ts = split_ts.tz_localize("America/New_York")
    split_iso = split_ts.isoformat()

    train: list[TradeRow] = []
    holdout: list[TradeRow] = []
    for t in trades:
        ets = str(t.entry_ts or "")
        try:
            ets_ts = pd.Timestamp(ets)
            if ets_ts.tzinfo is None:
                ets_ts = ets_ts.tz_localize("America/New_York")
            if ets_ts <= split_ts:
                train.append(t)
            else:
                holdout.append(t)
        except (TypeError, ValueError):
            # fallback: lexicographic ISO compare
            if ets <= split_iso:
                train.append(t)
            else:
                holdout.append(t)
    return train, holdout, split_iso


def _mean_pnl(trades: list[TradeRow]) -> float:
    if not trades:
        return 0.0
    return float(sum(t.net_pnl_pct for t in trades) / len(trades))


def _median_pnl(trades: list[TradeRow]) -> float:
    if not trades:
        return 0.0
    return float(median([t.net_pnl_pct for t in trades]))


def _win_pct(trades: list[TradeRow]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.net_pnl_pct > 0)
    return round(100.0 * wins / len(trades), 2)


def _summarize_split(
    train: list[TradeRow],
    holdout: list[TradeRow],
    *,
    variant_id: str,
    n_entries_blocked: int = 0,
) -> dict[str, Any]:
    return {
        "variant_id": variant_id,
        "n_train": len(train),
        "n_holdout": len(holdout),
        "n_trades": len(train) + len(holdout),
        "train_mean_net_pnl_pct": round(_mean_pnl(train), 6),
        "holdout_mean_net_pnl_pct": round(_mean_pnl(holdout), 6),
        "holdout_median_net_pnl_pct": round(_median_pnl(holdout), 6),
        "holdout_win_pct": _win_pct(holdout),
        "train_win_pct": _win_pct(train),
        "n_entries_blocked": n_entries_blocked,
    }


def recommended_variant_yaml(
    row: dict[str, Any],
    overrides: dict[str, Any],
    *,
    min_trades: int = 8,
    promote_ok: bool | None = None,
) -> str:
    """Emit a human-apply YAML snippet with ``active: false`` (never auto-LIVE).

    Promote-shape only when holdout mean > 0, MCPT pass, and n ≥ min_trades;
    otherwise least-bad CANDIDATE. Always ``active: false``.
    """
    n_hold = int(row.get("n_holdout") or 0)
    hold_mean = float(row.get("holdout_mean_net_pnl_pct") or 0.0)
    mcpt_pass = bool(row.get("mcpt_pass_5pct") is True)
    if promote_ok is None:
        promote_ok = hold_mean > 0 and mcpt_pass and n_hold >= int(min_trades)

    vid = str(row.get("variant_id") or "opt_candidate")
    label = "PROMOTE-SHAPE" if promote_ok else "CANDIDATE (least-bad)"
    desc = (
        f"{label} from UW-centered optimize; active:false — human paste only. "
        f"holdout_mean={hold_mean:.4f} n={n_hold} mcpt_pass={mcpt_pass}"
    )
    # Strip logging stamp; re-stamp for pasted id
    ov = deepcopy(overrides)
    log_cfg = ov.setdefault("logging", {})
    log_cfg["logic_version"] = f"xsp_lane_a_{vid}"

    block = {
        vid: {
            "active": False,
            "description": desc,
            "overrides": ov,
        }
    }
    header = (
        "# Paste under config/lane_a_variants.yaml → variants: (human only)\n"
        "# Does not flip live trading gates. active: false always.\n"
        f"# status: {label}\n"
    )
    body = yaml.safe_dump(block, sort_keys=False, default_flow_style=False)
    return header + body


def run_optimize(
    bars: pd.DataFrame,
    *,
    split_frac: float = 0.6,
    min_trades: int = 8,
    top_k: int = 8,
    run_mcpt: bool = False,
    n_perm: int = 1000,
    allow_large: bool = False,
    refine: bool = False,
    iv_seed: float = 0.18,
    use_bs: bool = True,
    source: str = "fixture",
    tmp_dir: Path | None = None,
    mode: str = "fixture",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run centered grid, train/holdout split, rank by holdout mean, MCPT top-K."""
    specs = build_centered_grid(allow_large=allow_large)
    cache_dir = tmp_dir
    own_tmp = None
    if cache_dir is None:
        own_tmp = tempfile.TemporaryDirectory(prefix="xsp_opt_rules_")
        cache_dir = Path(own_tmp.name)

    results_by_id: dict[str, BacktestResult] = {}
    overrides_by_id: dict[str, dict[str, Any]] = {}
    split_iso = ""

    def _run_specs(batch: list[VariantSpec]) -> None:
        nonlocal split_iso
        for spec in batch:
            rpath = rules_path_for_spec(spec, tmp_dir=cache_dir)
            logger.info("optimize run %s", spec.variant_id)
            res = run_backtest(
                bars,
                rpath,
                variant_id=spec.variant_id,
                iv_seed=iv_seed,
                use_bs=use_bs,
                source=source,
            )
            results_by_id[spec.variant_id] = res
            overrides_by_id[spec.variant_id] = deepcopy(spec.overrides)
            if not split_iso and res.trades:
                _, _, split_iso = partition_trades_by_split(
                    res.trades, bars, split_frac=split_frac
                )
        if not split_iso:
            _, _, split_iso = partition_trades_by_split(
                [], bars, split_frac=split_frac
            )

    try:
        _run_specs(specs)

        rows: list[dict[str, Any]] = []
        for vid, res in results_by_id.items():
            train, holdout, split_iso = partition_trades_by_split(
                res.trades, bars, split_frac=split_frac
            )
            row = _summarize_split(
                train,
                holdout,
                variant_id=vid,
                n_entries_blocked=res.n_entries_blocked,
            )
            row["holdout_pnls"] = [t.net_pnl_pct for t in holdout]
            rows.append(row)

        rows.sort(
            key=lambda r: (
                float(r.get("holdout_mean_net_pnl_pct") or 0.0),
                int(r.get("n_holdout") or 0),
            ),
            reverse=True,
        )

        if refine and rows:
            k_seed = min(3, int(top_k), len(rows))
            seed_ids = [r["variant_id"] for r in rows[:k_seed]]
            seed_specs = [
                _spec_from_overrides(sid, overrides_by_id[sid])
                for sid in seed_ids
                if sid in overrides_by_id
            ]
            existing = set(results_by_id.keys())
            budget_left = max(0, MAX_GRID_DEFAULT - len(existing))
            if allow_large:
                budget_left = max(budget_left, 24)
            neighbors = build_refine_neighbors(
                seed_specs,
                existing_ids=existing,
                allow_large=allow_large,
                budget_remaining=budget_left if not allow_large else 24,
            )
            if neighbors:
                logger.info("refine: running %d neighbor cells", len(neighbors))
                _run_specs(neighbors)
                for spec in neighbors:
                    res = results_by_id[spec.variant_id]
                    train, holdout, split_iso = partition_trades_by_split(
                        res.trades, bars, split_frac=split_frac
                    )
                    row = _summarize_split(
                        train,
                        holdout,
                        variant_id=spec.variant_id,
                        n_entries_blocked=res.n_entries_blocked,
                    )
                    row["holdout_pnls"] = [t.net_pnl_pct for t in holdout]
                    rows.append(row)
                rows.sort(
                    key=lambda r: (
                        float(r.get("holdout_mean_net_pnl_pct") or 0.0),
                        int(r.get("n_holdout") or 0),
                    ),
                    reverse=True,
                )

        # MCPT on top-K holdout paths only
        mcpt_budget = min(int(top_k), len(rows))
        for i, row in enumerate(rows):
            if run_mcpt and i < mcpt_budget:
                pnls = row.get("holdout_pnls") or []
                m = mcpt(pnls, n_perm=int(n_perm))
                row["mcpt"] = m
                row["mcpt_p"] = m.get("p_value")
                row["mcpt_pass_5pct"] = m.get("pass_5pct")
            # drop raw series from final ranking (keep in trades dump only)
            row.pop("holdout_pnls", None)

        # Recommendation
        promote_row = None
        for row in rows:
            n_h = int(row.get("n_holdout") or 0)
            mean_h = float(row.get("holdout_mean_net_pnl_pct") or 0.0)
            pass5 = row.get("mcpt_pass_5pct") is True
            if mean_h > 0 and pass5 and n_h >= int(min_trades):
                promote_row = row
                break
        if promote_row is not None:
            rec_row = promote_row
        else:
            rec_row = rows[0] if rows else None
        rec_status = (
            "PROMOTE-SHAPE"
            if promote_row is not None
            else "CANDIDATE (least-bad)"
        )
        rec_yaml = ""
        if rec_row is not None:
            ov = overrides_by_id.get(rec_row["variant_id"], {})
            rec_yaml = recommended_variant_yaml(
                rec_row,
                ov,
                min_trades=min_trades,
                promote_ok=promote_row is not None,
            )

        payload: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "source": source,
            "kind": "optimize_centered_28dte_atm",
            "disclaimer": (
                "Modeled premiums (BS-lite). Relative ranker only. "
                "Does NOT replace paper soak. Live trading gates untouched. "
                "YAML snippet is active:false — human paste only."
            ),
            "grid": {
                "n_specs": len(results_by_id),
                "dte": list(DTE_GRID),
                "take_profit_pct": list(TP_GRID),
                "stop_loss_pct": list(SL_GRID),
                "regime": [r[0] for r in REGIME_GRID],
                "strike_axis": "excluded (atm_only offline proxy)",
                "base": "BASE_28DTE_ATM_OVERRIDES",
                "refine": bool(refine),
            },
            "split": {
                "split_frac": float(split_frac),
                "split_ts": split_iso,
                "min_trades": int(min_trades),
            },
            "ranking": rows,
            "top_k_mcpt": mcpt_budget if run_mcpt else 0,
            "recommendation": {
                "status": rec_status,
                "variant_id": rec_row["variant_id"] if rec_row else None,
                "row": rec_row,
                "yaml_snippet": rec_yaml,
            },
            "trades": {
                vid: [t.to_dict() for t in res.trades]
                for vid, res in results_by_id.items()
            },
            "meta": meta or {},
        }
        return payload
    finally:
        if own_tmp is not None:
            own_tmp.cleanup()


def optimize_report_to_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Lane A centered optimize (28 DTE ATM)")
    lines.append("")
    lines.append(f"- generated: `{payload.get('generated_at')}`")
    lines.append(f"- mode/source: `{payload.get('mode')}` / `{payload.get('source')}`")
    grid = payload.get("grid") or {}
    lines.append(f"- grid cells: **{grid.get('n_specs')}** (base={grid.get('base')})")
    split = payload.get("split") or {}
    lines.append(
        f"- split_frac={split.get('split_frac')} cut=`{split.get('split_ts')}` "
        f"min_trades={split.get('min_trades')}"
    )
    lines.append("")
    lines.append(f"> {payload.get('disclaimer')}")
    lines.append("")

    rec = payload.get("recommendation") or {}
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"- status: **{rec.get('status')}**")
    lines.append(f"- variant: `{rec.get('variant_id')}`")
    lines.append("")
    snippet = rec.get("yaml_snippet") or ""
    if snippet:
        lines.append("```yaml")
        lines.append(snippet.rstrip())
        lines.append("```")
        lines.append("")

    lines.append("## Ranked table (by holdout mean net %)")
    lines.append("")
    ranking = payload.get("ranking") or []
    has_mcpt = any("mcpt_p" in r for r in ranking)
    if has_mcpt:
        lines.append(
            "| rank | variant | n_ho | win% | holdout mean% | train mean% "
            "| MCPT p | pass@5% |"
        )
        lines.append(
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |"
        )
    else:
        lines.append(
            "| rank | variant | n_ho | win% | holdout mean% | train mean% |"
        )
        lines.append("| ---: | --- | ---: | ---: | ---: | ---: |")

    for i, r in enumerate(ranking, 1):
        if has_mcpt:
            p = r.get("mcpt_p")
            p_s = f"{p:.4f}" if isinstance(p, float) else "—"
            pass_s = str(r.get("mcpt_pass_5pct")) if "mcpt_pass_5pct" in r else "—"
            lines.append(
                f"| {i} | `{r['variant_id']}` | {r.get('n_holdout', 0)} | "
                f"{r.get('holdout_win_pct', 0):.1f} | "
                f"{100 * float(r.get('holdout_mean_net_pnl_pct') or 0):.2f} | "
                f"{100 * float(r.get('train_mean_net_pnl_pct') or 0):.2f} | "
                f"{p_s} | {pass_s} |"
            )
        else:
            lines.append(
                f"| {i} | `{r['variant_id']}` | {r.get('n_holdout', 0)} | "
                f"{r.get('holdout_win_pct', 0):.1f} | "
                f"{100 * float(r.get('holdout_mean_net_pnl_pct') or 0):.2f} | "
                f"{100 * float(r.get('train_mean_net_pnl_pct') or 0):.2f} |"
            )

    lines.append("")
    lines.append("## Top survivors (first 8)")
    lines.append("")
    for r in ranking[:8]:
        lines.append(
            f"- `{r['variant_id']}`: holdout_mean="
            f"{100 * float(r.get('holdout_mean_net_pnl_pct') or 0):.2f}% "
            f"n_holdout={r.get('n_holdout')} "
            f"mcpt_pass={r.get('mcpt_pass_5pct')}"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_optimize_report(
    payload: dict[str, Any],
    out_dir: Path,
    *,
    stem: str | None = None,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if stem is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"optimize_{ts}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(optimize_report_to_markdown(payload), encoding="utf-8")
    logger.info("wrote %s and %s", json_path, md_path)
    return json_path, md_path


def print_optimize_table(payload: dict[str, Any]) -> None:
    print(optimize_report_to_markdown(payload))
