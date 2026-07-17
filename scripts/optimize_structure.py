#!/usr/bin/env python3
"""Stage B structure compare: naked long call vs call debit spread.

Reuses volume quiet-day gate + time-phased early SL under Nagus locks.
Does **not** flip LIVE_ENTRIES / LIVE_EXITS. Emitted YAML is always
``active: false``. Pricing is always ``modeled_bs_lite`` (never historical
XSP chain).

Offline:  ``python scripts/optimize_structure.py --mode fixture --structure both -v``
Strict:   ``python scripts/optimize_structure.py --mode uw --period 5y \\
            --intraday-period 60d --structure both --mcpt --out reports/backtest -v``
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — best-effort only
        pass

from xsp_killer.backtest.bars import (  # noqa: E402
    FixtureFallbackError,
    InsufficientBarsError,
    load_bars,
    load_uw_bars_strict,
)
from xsp_killer.backtest.intraday import (  # noqa: E402
    assert_intraday_coverage,
    bar_coverage,
    run_intraday_backtest,
)
from xsp_killer.backtest.optimize import (  # noqa: E402
    GridBudgetError,
    partition_trades_by_split,
)
from xsp_killer.backtest.regime_hold import (  # noqa: E402
    COARSE_SL,
    COARSE_SL_EARLY,
    COARSE_SL_EARLY_MINUTES,
    COARSE_TP,
    recommended_regime_hold_yaml,
)
from xsp_killer.backtest.report import familywise_max_stat_mcpt  # noqa: E402
from xsp_killer.backtest.sweep import (  # noqa: E402
    BASE_28DTE_ATM_OVERRIDES,
    _spec_from_overrides,
)
from xsp_killer.backtest.variants import rules_path_for_spec  # noqa: E402
from xsp_killer.lane_a_variants import VariantSpec, _deep_merge  # noqa: E402

logger = logging.getLogger("xsp_killer.optimize_structure")

# Hetzner prod tipdrop first; Windows laptop path is David's local checkout.
_DEFAULT_TIPDROP = (
    Path("/opt/tipdrop-scanner")
    if Path("/opt/tipdrop-scanner").is_dir()
    else Path(r"C:\Users\Owner\institutional-shadow")
)

_FORBIDDEN_ARTIFACT = (
    "LIVE_ENTRIES",
    "LIVE_EXITS",
    "UNUSUAL_WHALES_API_KEY",
)

STRUCTURE_MODES = ("naked", "debit_spread")

# Nagus locks for this structure compare (CLI may override volume / hold).
NAGUS_DTE = 30
NAGUS_STRIKE = "atm_only"
NAGUS_REGIME = "OFF"
NAGUS_PRIOR = False
# Close window baseline — do not re-sweep am/mid/late this pass.
NAGUS_WINDOW_START = "15:45"
NAGUS_WINDOW_END = "16:00"
DEFAULT_HOLDS = (5,)
DEFAULT_VOLUME_GATES: tuple[float | None, ...] = (0.33, None)
DEFAULT_WIDTH_STRIKES = 2
MAX_GRID_DEFAULT = 12


def _load_uw_key_from_tipdrop() -> None:
    """Load only UNUSUAL_WHALES_API_KEY from tipdrop .env if env unset.

    Never logs or prints the key value — only whether loading succeeded.
    """
    existing = os.getenv("UNUSUAL_WHALES_API_KEY", "").strip()
    if existing:
        return

    tipdrop = os.getenv("XSP_UW_TIPDROP_ROOT", "").strip()
    root = Path(tipdrop) if tipdrop else _DEFAULT_TIPDROP
    env_path = root / ".env"
    if not env_path.is_file():
        logger.debug("tipdrop .env not found at %s", env_path)
        return

    try:
        text = env_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("could not read tipdrop .env: %s", exc)
        return

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key != "UNUSUAL_WHALES_API_KEY":
            continue
        val = val.strip().strip("'").strip('"')
        if val:
            os.environ["UNUSUAL_WHALES_API_KEY"] = val
            logger.info("loaded API key from tipdrop .env (value not logged)")
            return
    logger.debug("API key not found in tipdrop .env")


def _vol_label(max_pctile: float | None) -> str:
    if max_pctile is None:
        return "vall"
    return f"vq{int(round(float(max_pctile) * 100))}"


def _structure_label(mode: str) -> str:
    return "naked" if mode == "naked" else "dspread"


def _vid(
    structure_mode: str,
    *,
    vol_label: str,
    hold: int,
    dte: int = NAGUS_DTE,
    tp: float = COARSE_TP,
    sl: float = COARSE_SL,
    width_strikes: int = DEFAULT_WIDTH_STRIKES,
) -> str:
    tp_i = int(round(tp * 100))
    sl_i = int(round(sl * 100))
    slabel = _structure_label(structure_mode)
    if structure_mode == "debit_spread":
        return (
            f"st_{slabel}_w{width_strikes}_dte{dte}_tp{tp_i}_sl{sl_i}_"
            f"{vol_label}_h{hold}"
        )
    return f"st_{slabel}_dte{dte}_tp{tp_i}_sl{sl_i}_{vol_label}_h{hold}"


def build_structure_grid(
    *,
    structures: list[str] | None = None,
    volume_gates: list[float | None] | None = None,
    holds: list[int] | None = None,
    width_strikes: int = DEFAULT_WIDTH_STRIKES,
    max_grid: int = MAX_GRID_DEFAULT,
    allow_large: bool = False,
) -> list[dict[str, Any]]:
    """Bounded cells: structure × volume × hold under Nagus locks."""
    modes = list(structures) if structures else list(STRUCTURE_MODES)
    for mode in modes:
        if mode not in STRUCTURE_MODES:
            raise ValueError(
                f"unknown structure mode {mode!r}; choose from {STRUCTURE_MODES}"
            )
    vols = list(volume_gates) if volume_gates is not None else list(DEFAULT_VOLUME_GATES)
    hold_list = list(holds) if holds is not None else list(DEFAULT_HOLDS)
    width = max(1, int(width_strikes))

    n = len(modes) * len(vols) * len(hold_list)
    if n > int(max_grid) and not allow_large:
        raise GridBudgetError(
            f"structure grid size {n} exceeds budget {max_grid}; "
            "narrow --structure / --volume-pctile / holds or pass --allow-large"
        )

    cells: list[dict[str, Any]] = []
    for mode, vol, hold in product(modes, vols, hold_list):
        vlab = _vol_label(vol)
        vid = _vid(mode, vol_label=vlab, hold=int(hold), width_strikes=width)
        entry: dict[str, Any] = {
            "dte_pick": "target",
            "dte_target": int(NAGUS_DTE),
            "strike_pick": NAGUS_STRIKE,
            "regime_gate": NAGUS_REGIME,
            "prior_day_spy_positive": bool(NAGUS_PRIOR),
            "volume_gate_lookback": 63,
            "window_start_et": NAGUS_WINDOW_START,
            "window_end_et": NAGUS_WINDOW_END,
            "structure_mode": mode,
            "debit_spread_width_strikes": int(width),
        }
        if vol is not None:
            entry["volume_gate_max_pctile"] = float(vol)
        patch = {
            "entry": entry,
            "exit": {
                "take_profit_pct": float(COARSE_TP),
                "stop_loss_pct": float(COARSE_SL),
                "stop_loss_pct_early": float(COARSE_SL_EARLY),
                "stop_loss_early_minutes": int(COARSE_SL_EARLY_MINUTES),
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
        merged = _deep_merge(deepcopy(BASE_28DTE_ATM_OVERRIDES), patch)
        logging_cfg = merged.setdefault("logging", {})
        logging_cfg["logic_version"] = f"xsp_lane_a_{vid}"
        vol_word = "off" if vol is None else f"max_pctile<={vol}"
        desc = (
            f"structure={mode} width_strikes={width} dte={NAGUS_DTE} "
            f"tp={COARSE_TP} sl={COARSE_SL} early_sl={COARSE_SL_EARLY} "
            f"volume={vol_word} hold={hold} window=close"
        )
        spec = _spec_from_overrides(vid, merged, description=desc)
        # Keep research candidates inactive in any emitted YAML.
        spec = VariantSpec(
            variant_id=spec.variant_id,
            description=spec.description,
            active=False,
            overrides=spec.overrides,
        )
        cells.append(
            {
                "variant_id": vid,
                "structure_mode": mode,
                "debit_spread_width_strikes": int(width),
                "volume_gate_max_pctile": vol,
                "max_hold_sessions": int(hold),
                "spec": spec,
                "overrides": deepcopy(merged),
            }
        )
    return cells


def _parse_volume_pctiles(raw: str | None) -> list[float | None]:
    """Parse comma list; token ``none`` / ``all`` / empty → ungated cell."""
    if raw is None or not str(raw).strip():
        return list(DEFAULT_VOLUME_GATES)
    out: list[float | None] = []
    for part in str(raw).split(","):
        tok = part.strip().lower()
        if not tok:
            continue
        if tok in ("none", "all", "off", "vall"):
            out.append(None)
            continue
        out.append(float(tok))
    return out or list(DEFAULT_VOLUME_GATES)


def _parse_structures(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        return list(STRUCTURE_MODES)
    token = str(raw).strip().lower()
    if token == "both":
        return list(STRUCTURE_MODES)
    out: list[str] = []
    for part in token.split(","):
        tok = part.strip().lower()
        if tok == "both":
            out.extend(STRUCTURE_MODES)
        elif tok:
            out.append(tok)
    # de-dupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for m in out:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq or list(STRUCTURE_MODES)


def _parse_holds(raw: str | None) -> list[int]:
    if raw is None or not str(raw).strip():
        return list(DEFAULT_HOLDS)
    out: list[int] = []
    for part in str(raw).split(","):
        tok = part.strip()
        if tok:
            out.append(int(tok))
    return out or list(DEFAULT_HOLDS)


def _summarize_intraday(res: Any) -> dict[str, Any]:
    pnls = [t.net_pnl_pct for t in res.trades]
    n = len(pnls)
    mean_p = float(sum(pnls) / n) if n else 0.0
    wins = sum(1 for p in pnls if p > 0)
    early_n = sum(1 for t in res.trades if getattr(t, "early_green", False))
    return {
        "variant_id": res.variant_id,
        "n_trades": n,
        "mean_net_pnl_pct": round(mean_p, 6),
        "win_pct": round(100.0 * wins / n, 2) if n else 0.0,
        "early_green_rate": round(early_n / n, 4) if n else 0.0,
        "n_early_green": int(early_n),
        "n_entries_blocked": int(res.n_entries_blocked),
        "n_blocked_spread": int(getattr(res, "n_blocked_spread", 0) or 0),
        "residual_open": int(getattr(res, "residual_open", 0)),
        "residual_marked_pnl_pct": getattr(
            res, "residual_marked_pnl_pct", None
        ),
        "source": res.source,
        "exit_reasons": {
            r: sum(1 for t in res.trades if t.exit_reason == r)
            for r in sorted({t.exit_reason for t in res.trades})
        },
    }


def _scrub_forbidden(text: str) -> str:
    out = text
    for token in _FORBIDDEN_ARTIFACT:
        if token in out:
            out = out.replace(token, "REDACTED")
    return out


def _daily_coverage(bars: Any, interval: str = "1d") -> dict[str, Any]:
    if bars is None or len(bars) == 0:
        return {
            "n_bars": 0,
            "n_sessions": 0,
            "start": None,
            "end": None,
            "interval": interval,
            "has_overnight_bars": False,
            "session_phases_observed": ["daily"] if interval == "1d" else [],
        }
    start = bars.index[0]
    end = bars.index[-1]
    n_sess = int(bars.index.normalize().nunique())
    coverage = {
        "n_bars": int(len(bars)),
        "n_sessions": n_sess,
        "start": start.isoformat() if hasattr(start, "isoformat") else str(start),
        "end": end.isoformat() if hasattr(end, "isoformat") else str(end),
        "interval": interval,
        "has_overnight_bars": False,
        "session_phases_observed": ["daily"],
    }
    coverage.update(bars.attrs.get("uw_cache_status") or {})
    return coverage


def _load_daily(
    args: argparse.Namespace,
) -> tuple[Any, str, dict[str, Any]]:
    if args.mode == "uw" and args.strict_uw:
        bars, cov = load_uw_bars_strict(
            args.ticker,
            period=args.period,
            interval="1d",
            min_bars=max(50, int(args.min_trades) * 2),
            min_sessions=0,
            max_cache_age=float(args.max_cache_age_hours),
            refresh=bool(args.refresh_uw),
        )
        cov["strict_uw"] = True
        return bars, "uw", cov
    bars, source = load_bars(
        mode=args.mode,
        interval="1d",
        ticker=args.ticker,
        period=args.period,
        refresh=bool(args.refresh_uw),
    )
    coverage = _daily_coverage(bars, "1d")
    coverage["strict_uw"] = bool(args.strict_uw)
    coverage.setdefault("refresh_requested", bool(args.refresh_uw))
    return bars, source, coverage


def _load_intraday(
    args: argparse.Namespace,
) -> tuple[Any, str, dict[str, Any]]:
    if args.mode == "uw" and args.strict_uw:
        bars, cov = load_uw_bars_strict(
            args.ticker,
            period=args.intraday_period,
            interval="15m",
            min_bars=int(args.min_intraday_bars),
            min_sessions=int(args.min_intraday_sessions),
            max_cache_age=float(args.max_cache_age_hours),
            refresh=bool(args.refresh_uw),
        )
        cov["strict_uw"] = True
        return bars, "uw", cov
    if args.mode == "uw":
        bars, source = load_bars(
            mode="uw",
            interval="15m",
            ticker=args.ticker,
            period=args.intraday_period,
            refresh=bool(args.refresh_uw),
        )
        cov = bar_coverage(bars)
        cov.update(bars.attrs.get("uw_cache_status") or {})
        cov["strict_uw"] = bool(args.strict_uw)
        cov.setdefault("refresh_requested", bool(args.refresh_uw))
        if source == "uw":
            assert_intraday_coverage(
                bars,
                min_bars=int(args.min_intraday_bars),
                min_sessions=int(args.min_intraday_sessions),
            )
        return bars, source, cov
    bars, source = load_bars(mode="fixture", interval="15m", ticker=args.ticker)
    cov = bar_coverage(bars)
    cov["strict_uw"] = False
    cov["refresh_requested"] = False
    return bars, source, cov


def _report_to_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Structure Compare Report (naked vs debit_spread)")
    lines.append("")
    lines.append(f"- generated_at: `{payload.get('generated_at')}`")
    lines.append(f"- mode: `{payload.get('mode')}`")
    lines.append(f"- strict_uw: `{payload.get('strict_uw')}`")
    lines.append(
        f"- pricing_fidelity: `{payload.get('pricing_fidelity', 'modeled_bs_lite')}`"
    )
    args_block = payload.get("args") or {}
    lines.append(
        f"- UW cache: max_age_hours={args_block.get('max_cache_age_hours')} "
        f"refresh={args_block.get('refresh_uw')}"
    )
    rec_status = (payload.get("recommendation") or {}).get("status")
    lines.append(f"- recommendation: **{rec_status}**")
    lines.append("")
    lines.append("## Safety")
    lines.append("")
    lines.append(
        "- Read-only research. Does not flip live gates. "
        "YAML snippet is always `active: false` (human paste only). "
        "Premiums are **modeled_bs_lite** — never historical XSP chain fills."
    )
    lines.append("")

    cov = payload.get("coverage") or {}
    if cov:
        lines.append("## Coverage")
        lines.append("")
        lines.append(
            f"- bars: {cov.get('start')} → {cov.get('end')} "
            f"n_bars={cov.get('n_bars')} n_sessions={cov.get('n_sessions')} "
            f"phases={cov.get('session_phases_observed')}"
        )
        lines.append("")

    ranking = payload.get("ranking") or []
    lines.append("## Side-by-side (by Stage B mean)")
    lines.append("")
    lines.append(
        "| variant | structure | hold | vol | n | mean% | win% | "
        "early_green_rate | blocked | blocked_spread | status |"
    )
    lines.append(
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|"
    )
    for r in ranking:
        vol = r.get("volume_gate_max_pctile")
        vol_text = "off" if vol is None else f"{float(vol):.2f}"
        lines.append(
            f"| `{r.get('variant_id')}` | {r.get('structure_mode')} | "
            f"{r.get('max_hold_sessions')} | {vol_text} | "
            f"{r.get('n_trades')} | "
            f"{100 * float(r.get('mean_net_pnl_pct') or 0):.2f} | "
            f"{r.get('win_pct')} | "
            f"{float(r.get('early_green_rate') or 0):.2f} | "
            f"{r.get('n_entries_blocked', 0)} | "
            f"{r.get('n_blocked_spread', 0)} | "
            f"{r.get('decision_status', 'RESEARCH ONLY')} |"
        )
    lines.append("")

    # Compact by-structure rollup when both present.
    by_struct = payload.get("by_structure") or {}
    if by_struct:
        lines.append("## By structure_mode")
        lines.append("")
        lines.append("| structure | n_cells | mean_of_means% | total_n |")
        lines.append("|---|---:|---:|---:|")
        for mode, row in by_struct.items():
            lines.append(
                f"| {mode} | {row.get('n_cells')} | "
                f"{100 * float(row.get('mean_of_means') or 0):.2f} | "
                f"{row.get('total_trades')} |"
            )
        lines.append("")

    rec = payload.get("recommendation") or {}
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"- status: **{rec.get('status')}**")
    lines.append(f"- variant_id: `{rec.get('variant_id')}`")
    lines.append(f"- structure_mode: `{rec.get('structure_mode')}`")
    lines.append(f"- edge_reason: `{rec.get('edge_reason')}`")
    lines.append(
        "- Note: RESEARCH ONLY unless existing edge_confirmed + "
        "promotion_eligible gates pass (they should not flip live)."
    )
    lines.append("")
    lines.append("### Inactive YAML snippet")
    lines.append("")
    lines.append("```yaml")
    lines.append((rec.get("yaml_snippet") or "# (none)").rstrip())
    lines.append("```")
    lines.append("")
    return _scrub_forbidden("\n".join(lines) + "\n")


def write_structure_report(
    payload: dict[str, Any],
    out_dir: Path,
    *,
    stem: str | None = None,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if stem is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"structure_{ts}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_text = _scrub_forbidden(json.dumps(payload, indent=2) + "\n")
    md_text = _report_to_markdown(payload)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    logger.info("wrote %s and %s", json_path, md_path)
    return json_path, md_path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Stage B structure compare (naked vs debit_spread) under Nagus "
            "defaults. Reuses volume gate + phased early SL. "
            "Does not touch LIVE_* or auto-edit lane_a_variants.yaml."
        )
    )
    p.add_argument(
        "--mode",
        choices=("fixture", "uw"),
        default="fixture",
        help="Data source (--mode uw is strict by default)",
    )
    p.add_argument(
        "--period",
        default="5y",
        help="UW daily history period for regime/volume context (default 5y)",
    )
    p.add_argument(
        "--intraday-period",
        default="60d",
        help="UW 15m history period for Stage B (default 60d)",
    )
    p.add_argument(
        "--structure",
        default="both",
        help="naked | debit_spread | both (default both)",
    )
    p.add_argument(
        "--width-strikes",
        type=int,
        default=DEFAULT_WIDTH_STRIKES,
        help=f"Debit spread width in strike steps (default {DEFAULT_WIDTH_STRIKES})",
    )
    p.add_argument(
        "--volume-pctile",
        default="0.33,none",
        help="Comma volume max pctiles; 'none' = ungated control (default 0.33,none)",
    )
    p.add_argument(
        "--holds",
        default="5",
        help="Comma max_hold_sessions values (default 5)",
    )
    p.add_argument(
        "--split-frac",
        type=float,
        default=0.6,
        help="Train fraction of bar date-range (default 0.6)",
    )
    p.add_argument(
        "--min-trades",
        type=int,
        default=4,
        help="Min trades for soft sample notes (default 4; fixture-friendly)",
    )
    p.add_argument(
        "--mcpt",
        action="store_true",
        help="Run family-wise MCPT-lite on cell mean returns",
    )
    p.add_argument(
        "--mcpt-perm",
        type=int,
        default=200,
        help="MCPT permutations (default 200; keep small for fixture)",
    )
    p.add_argument(
        "--allow-large",
        action="store_true",
        help="Allow grid size above the default budget",
    )
    p.add_argument(
        "--max-grid",
        type=int,
        default=MAX_GRID_DEFAULT,
        help=f"Grid budget (default {MAX_GRID_DEFAULT})",
    )
    uw_policy = p.add_mutually_exclusive_group()
    uw_policy.add_argument(
        "--allow-fixture-fallback",
        action="store_true",
        help="Research override: allow UW mode to fall back to fixtures",
    )
    uw_policy.add_argument(
        "--require-uw",
        action="store_true",
        help="Deprecated compatibility alias; forces --mode uw strict loading",
    )
    p.add_argument(
        "--refresh-uw",
        action="store_true",
        help="Bypass UW caches and fetch fresh bars",
    )
    p.add_argument(
        "--max-cache-age-hours",
        type=float,
        default=24.0,
        help="Strict UW cache freshness limit in hours (default 24)",
    )
    p.add_argument(
        "--min-intraday-bars",
        type=int,
        default=200,
        help="Stage B floor: minimum 15m bars (default 200)",
    )
    p.add_argument(
        "--min-intraday-sessions",
        type=int,
        default=20,
        help="Stage B floor: minimum session dates (default 20)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports" / "backtest",
        help="Output directory for structure_*.json + .md",
    )
    p.add_argument("--ticker", default="SPY")
    p.add_argument("--iv", type=float, default=0.18, help="IV seed for BS-lite")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.max_cache_age_hours < 0:
        raise SystemExit("--max-cache-age-hours must be non-negative")
    if args.require_uw:
        args.mode = "uw"
    args.strict_uw = args.mode == "uw" and (
        bool(args.require_uw) or not bool(args.allow_fixture_fallback)
    )
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.mode == "uw":
        _load_uw_key_from_tipdrop()
    if args.require_uw:
        logger.warning("--require-uw is deprecated; UW mode is strict by default")

    try:
        structures = _parse_structures(args.structure)
        volumes = _parse_volume_pctiles(args.volume_pctile)
        holds = _parse_holds(args.holds)
        cells = build_structure_grid(
            structures=structures,
            volume_gates=volumes,
            holds=holds,
            width_strikes=int(args.width_strikes),
            max_grid=int(args.max_grid),
            allow_large=bool(args.allow_large),
        )
    except (GridBudgetError, ValueError) as exc:
        logger.error("%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "strict_uw": bool(args.strict_uw),
        "kind": "structure_optimizer",
        "pricing_fidelity": "modeled_bs_lite",
        "disclaimer": (
            "Modeled premiums (BS-lite). Relative research ranker only. "
            "Does NOT replace paper soak. Live trading gates untouched. "
            "YAML snippet is active:false — human paste only. "
            "Never auto-edits config. Never claims historical_xsp_chain."
        ),
        "args": {
            "period": args.period,
            "intraday_period": args.intraday_period,
            "structures": structures,
            "width_strikes": int(args.width_strikes),
            "volume_pctile": volumes,
            "holds": holds,
            "split_frac": args.split_frac,
            "min_trades": args.min_trades,
            "mcpt": bool(args.mcpt),
            "require_uw": bool(args.require_uw),
            "allow_fixture_fallback": bool(args.allow_fixture_fallback),
            "refresh_uw": bool(args.refresh_uw),
            "max_cache_age_hours": float(args.max_cache_age_hours),
            "n_cells": len(cells),
        },
    }

    # Daily context (regime/volume) — required for UW Stage B; fixture optional.
    daily_bars = None
    daily_source = "fixture"
    daily_cov: dict[str, Any] = {}
    try:
        if args.mode == "uw":
            daily_bars, daily_source, daily_cov = _load_daily(args)
            if daily_source == "fixture_fallback":
                print(
                    "WARN: --mode uw fell back to fixtures for daily bars. "
                    "Results are offline-synthetic, not UW history.",
                    file=sys.stderr,
                )
        else:
            daily_bars, daily_source, daily_cov = _load_daily(args)
    except FixtureFallbackError as exc:
        logger.error("UW strict daily load failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except InsufficientBarsError as exc:
        logger.error("UW daily coverage insufficient: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    try:
        ibars, isource, icov = _load_intraday(args)
    except FixtureFallbackError as exc:
        logger.error("UW strict intraday load failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except InsufficientBarsError as exc:
        logger.error("UW intraday coverage insufficient: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    if isource == "fixture_fallback":
        print(
            "WARN: --mode uw fell back to fixtures for intraday bars.",
            file=sys.stderr,
        )

    if args.mode == "uw" and isource == "uw":
        try:
            assert_intraday_coverage(
                ibars,
                min_bars=int(args.min_intraday_bars),
                min_sessions=int(args.min_intraday_sessions),
            )
        except InsufficientBarsError as exc:
            logger.error("%s", exc)
            print(f"ERROR: {exc}", file=sys.stderr)
            return 3

    payload["coverage"] = icov
    payload["daily_coverage"] = daily_cov
    payload["source"] = isource

    ranking: list[dict[str, Any]] = []
    observations_by_id: dict[str, list[tuple[str, float]]] = {}
    overrides_by_id: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="xsp_st_rules_") as tmp:
        tmp_path = Path(tmp)
        for cell in cells:
            spec: VariantSpec = cell["spec"]
            rpath = rules_path_for_spec(spec, tmp_dir=tmp_path)
            # Fixture: let run_intraday derive daily_context; UW needs explicit.
            daily_ctx = None if args.mode == "fixture" else daily_bars
            res = run_intraday_backtest(
                ibars,
                rpath,
                variant_id=spec.variant_id,
                iv_seed=float(args.iv),
                source=isource,
                max_hold_sessions=int(cell["max_hold_sessions"]),
                daily_context=daily_ctx,
            )
            summary = _summarize_intraday(res)
            summary["structure_mode"] = cell["structure_mode"]
            summary["debit_spread_width_strikes"] = cell[
                "debit_spread_width_strikes"
            ]
            summary["volume_gate_max_pctile"] = cell["volume_gate_max_pctile"]
            summary["max_hold_sessions"] = cell["max_hold_sessions"]
            summary["decision_status"] = "RESEARCH ONLY"
            summary["pricing_fidelity"] = "modeled_bs_lite"
            # Session-keyed observations for familywise MCPT (entry date, pnl).
            observations: list[tuple[str, float]] = []
            for t in res.trades:
                try:
                    sess = str(
                        datetime.fromisoformat(t.entry_ts).date()
                    )
                except (TypeError, ValueError):
                    sess = str(t.entry_ts)[:10]
                observations.append((sess, float(t.net_pnl_pct)))
            observations_by_id[spec.variant_id] = observations
            if res.trades and len(ibars) > 10:
                train, holdout, split_iso = partition_trades_by_split(
                    res.trades, ibars, split_frac=float(args.split_frac)
                )
                summary["n_train"] = len(train)
                summary["n_validation"] = len(holdout)
                summary["n_holdout"] = len(holdout)
                summary["split_ts"] = split_iso
                if train:
                    tm = sum(t.net_pnl_pct for t in train) / len(train)
                    summary["train_mean_net_pnl_pct"] = round(tm, 6)
                if holdout:
                    hm = sum(t.net_pnl_pct for t in holdout) / len(holdout)
                    summary["validation_mean_net_pnl_pct"] = round(hm, 6)
                    summary["holdout_mean_net_pnl_pct"] = round(hm, 6)
            ranking.append(summary)
            overrides_by_id[spec.variant_id] = deepcopy(cell["overrides"])
            logger.info(
                "%s structure=%s n=%d mean=%.4f early_green=%.2f "
                "blocked=%d blocked_spread=%d",
                spec.variant_id,
                cell["structure_mode"],
                summary["n_trades"],
                summary["mean_net_pnl_pct"],
                summary["early_green_rate"],
                summary["n_entries_blocked"],
                summary["n_blocked_spread"],
            )

    # Rank by mean Stage B return (desc), then n_trades.
    ranking.sort(
        key=lambda r: (
            float(r.get("mean_net_pnl_pct") or 0.0),
            int(r.get("n_trades") or 0),
        ),
        reverse=True,
    )

    if args.mcpt and ranking:
        try:
            family = {
                str(r.get("variant_id") or ""): observations_by_id.get(
                    str(r.get("variant_id") or ""), []
                )
                for r in ranking
                if int(r.get("n_trades") or 0) >= int(args.min_trades)
            }
            if family:
                family_results = familywise_max_stat_mcpt(
                    family, n_perm=int(args.mcpt_perm)
                )
                for row in ranking:
                    vid = str(row.get("variant_id") or "")
                    if vid in family_results:
                        fr = family_results[vid]
                        row["familywise_p_value"] = fr.get("familywise_p_value")
                        row["familywise_pass_5pct"] = fr.get(
                            "familywise_pass_5pct"
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCPT failed (non-fatal): %s", exc)

    payload["ranking"] = ranking
    payload["n_cells"] = len(cells)
    payload["structures_present"] = sorted(
        {str(r.get("structure_mode")) for r in ranking}
    )

    # Rollup by structure for the side-by-side summary.
    by_structure: dict[str, dict[str, Any]] = {}
    for r in ranking:
        mode = str(r.get("structure_mode") or "naked")
        bucket = by_structure.setdefault(
            mode,
            {"n_cells": 0, "means": [], "total_trades": 0},
        )
        bucket["n_cells"] += 1
        bucket["means"].append(float(r.get("mean_net_pnl_pct") or 0.0))
        bucket["total_trades"] += int(r.get("n_trades") or 0)
    for mode, bucket in by_structure.items():
        means = bucket.pop("means")
        bucket["mean_of_means"] = (
            round(sum(means) / len(means), 6) if means else 0.0
        )
    payload["by_structure"] = by_structure

    # Recommendation: always RESEARCH ONLY unless promotion gates (they won't).
    rec_row = ranking[0] if ranking else None
    edge_ok = False
    edge_reason = "structure_research_only"
    if rec_row is not None:
        n = int(rec_row.get("n_trades") or 0)
        mean_p = float(rec_row.get("mean_net_pnl_pct") or 0.0)
        if n < int(args.min_trades):
            edge_reason = f"insufficient_trades n={n}<{args.min_trades}"
        elif mean_p <= 0:
            edge_reason = "non_positive_mean"
        else:
            edge_reason = "positive_mean_but_modeled_pricing"
    status = "RESEARCH ONLY"
    yaml_snip = ""
    if rec_row is not None:
        ov = overrides_by_id.get(str(rec_row.get("variant_id") or "")) or {}
        entry_ov = ov.setdefault("entry", {})
        entry_ov["structure_mode"] = rec_row.get("structure_mode", "naked")
        entry_ov["debit_spread_width_strikes"] = int(
            rec_row.get("debit_spread_width_strikes") or DEFAULT_WIDTH_STRIKES
        )
        yaml_snip = recommended_regime_hold_yaml(
            {
                **rec_row,
                "n_validation": rec_row.get("n_validation")
                or rec_row.get("n_trades")
                or 0,
                "validation_mean_net_pnl_pct": rec_row.get(
                    "validation_mean_net_pnl_pct",
                    rec_row.get("mean_net_pnl_pct"),
                ),
            },
            ov,
            min_trades=int(args.min_trades),
            edge_ok=edge_ok,
            max_hold_sessions=int(rec_row.get("max_hold_sessions") or 0),
        )

    payload["recommendation"] = {
        "status": status,
        "variant_id": rec_row.get("variant_id") if rec_row else None,
        "structure_mode": rec_row.get("structure_mode") if rec_row else None,
        "edge_ok": edge_ok,
        "edge_reason": edge_reason,
        "pricing_fidelity": "modeled_bs_lite",
        "promotion_eligible": False,
        "row": rec_row,
        "yaml_snippet": yaml_snip,
    }
    payload["yaml_snippet"] = yaml_snip

    raw = json.dumps(payload)
    for token in _FORBIDDEN_ARTIFACT:
        if token in raw:
            logger.warning("scrubbing forbidden token from payload: %s", token)
            raw = raw.replace(token, "REDACTED")
            payload = json.loads(raw)
            break

    # Hard guard: never claim historical chain fidelity.
    fidelity = str(payload.get("pricing_fidelity") or "")
    if fidelity == "historical_xsp_chain":
        payload["pricing_fidelity"] = "modeled_bs_lite"
    rec_fid = (payload.get("recommendation") or {}).get("pricing_fidelity")
    if rec_fid == "historical_xsp_chain":
        payload["recommendation"]["pricing_fidelity"] = "modeled_bs_lite"

    json_path, md_path = write_structure_report(payload, Path(args.out))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"recommendation: {status} ({edge_reason})")
    print(f"structures: {payload.get('structures_present')}")
    print("pricing_fidelity: modeled_bs_lite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
