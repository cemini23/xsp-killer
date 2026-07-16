#!/usr/bin/env python3
"""Two-stage UW regime + trading-session hold optimizer (read-only).

Stage A: long-history daily discovery (regime × hold).
Stage B: 15m session-aware timing validation on shortlisted finalists.

Never flips LIVE_ENTRIES / LIVE_EXITS. Never writes secrets or auto-edits
``config/lane_a_variants.yaml``. Emitted YAML is always ``active: false``.

Offline:  ``python scripts/optimize_regime_hold.py --mode fixture``
Strict:   ``python scripts/optimize_regime_hold.py --mode uw --require-uw ...``
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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows consoles often default to cp1252; avoid UnicodeEncodeError on arrows etc.
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
    StageASpec,
    edge_confirmed,
    promotion_eligible,
    recommended_regime_hold_yaml,
    run_sensitivity,
    run_stage_a,
    stable_windows,
)
from xsp_killer.backtest.sweep import (  # noqa: E402
    BASE_28DTE_ATM_OVERRIDES,
    _spec_from_overrides,
)
from xsp_killer.backtest.variants import rules_path_for_spec  # noqa: E402
from xsp_killer.lane_a_variants import _deep_merge  # noqa: E402

logger = logging.getLogger("xsp_killer.optimize_regime_hold")

_DEFAULT_TIPDROP = Path(r"C:\Users\Owner\institutional-shadow")

# Forbidden substrings in written artifacts (defense-in-depth).
_FORBIDDEN_ARTIFACT = (
    "LIVE_ENTRIES",
    "LIVE_EXITS",
    "UNUSUAL_WHALES_API_KEY",
)


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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Two-stage regime + trading-session hold optimizer (UW or fixture). "
            "Stage A = daily discovery; Stage B = 15m session validation. "
            "Does not touch LIVE_* or auto-edit lane_a_variants.yaml."
        )
    )
    p.add_argument(
        "--mode",
        choices=("fixture", "uw"),
        default="fixture",
        help="Data source (uw with --require-uw never falls back to fixture)",
    )
    p.add_argument(
        "--stage-a",
        action="store_true",
        help="Run Stage A (daily regime/hold discovery)",
    )
    p.add_argument(
        "--stage-b",
        action="store_true",
        help="Run Stage B (15m session-aware validation of finalists)",
    )
    p.add_argument(
        "--period",
        default="5y",
        help="UW daily history period for Stage A (default 5y)",
    )
    p.add_argument(
        "--intraday-period",
        default="60d",
        help="UW 15m history period for Stage B (default 60d)",
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
        default=8,
        help="Min holdout trades for sample qualification",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=12,
        help="Finalist count for refine/MCPT/Stage B (default 12)",
    )
    p.add_argument(
        "--mcpt",
        action="store_true",
        help="Run MCPT-lite sign-flip on Stage A finalists",
    )
    p.add_argument(
        "--mcpt-perm",
        type=int,
        default=1000,
        help="MCPT permutations (default 1000)",
    )
    p.add_argument(
        "--coarse-to-fine",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refine DTE/TP/SL around Stage A survivors (default: on)",
    )
    p.add_argument(
        "--allow-large",
        action="store_true",
        help="Allow Stage A grid size above the default budget",
    )
    p.add_argument(
        "--require-uw",
        action="store_true",
        help="Fail nonzero if UW unavailable/insufficient (no fixture report)",
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
        "--min-intraday-trades",
        type=int,
        default=20,
        help="Promotion gate: minimum closed Stage B trades (default 20)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports" / "backtest",
        help="Output directory for regime_hold_*.json + .md",
    )
    p.add_argument("--ticker", default="SPY")
    p.add_argument("--iv", type=float, default=0.18, help="IV seed for BS-lite")
    p.add_argument(
        "--max-grid",
        type=int,
        default=240,
        help="Stage A grid budget (default 240; tests may lower)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _select_finalists(
    rows: list[dict[str, Any]], *, top_k: int, min_trades: int
) -> list[dict[str, Any]]:
    unique = [r for r in rows if not r.get("behavior_duplicate_of")]
    qualified = [
        r
        for r in unique
        if int(r.get("n_validation") or r.get("n_holdout") or 0)
        >= int(min_trades)
    ]
    pool = qualified if qualified else unique
    return pool[: min(int(top_k), len(pool))]


def _select_edge_candidate(
    finalists: list[dict[str, Any]],
    *,
    sensitivity_by_id: dict[str, dict[str, Any]],
    intraday_by_id: dict[str, dict[str, Any]],
    run_b: bool,
    min_trades: int,
    min_intraday_trades: int,
) -> tuple[dict[str, Any] | None, bool, str]:
    """Return the first rank-ordered finalist passing every edge gate."""
    if not finalists:
        return None, False, "no_candidates"

    best_row = finalists[0]
    best_reason = "sensitivity_missing"
    for index, row in enumerate(finalists):
        variant_id = str(row.get("variant_id") or "")
        sensitivity = sensitivity_by_id.get(variant_id)
        if sensitivity is None:
            reason = "sensitivity_missing"
            ok = False
        else:
            ok, reason = edge_confirmed(
                row,
                sensitivity,
                intraday_by_id.get(variant_id) if run_b else None,
                min_trades=min_trades,
                min_intraday_trades=min_intraday_trades,
            )
        if index == 0:
            best_reason = reason
        if ok:
            return row, True, reason
    return best_row, False, best_reason


def _stage_a_spec_from_row(row: dict[str, Any]) -> StageASpec:
    """Rebuild a StageASpec from a ranking row (no live YAML keys)."""
    dte = int(row.get("dte_target") or 28)
    tp = float(row.get("take_profit_pct") or 0.20)
    sl = float(row.get("stop_loss_pct") or 0.30)
    hold = int(row.get("max_hold_sessions") or 1)
    gate = str(row.get("regime_gate") or "GREEN")
    yfrac = row.get("regime_yellow_frac_min")
    ybounce = row.get("regime_yellow_require_bounce")
    prior = bool(row.get("prior_day_spy_positive", False))
    vid = str(row.get("variant_id") or "rha_unknown")

    entry: dict[str, Any] = {
        "dte_pick": "target",
        "dte_target": dte,
        "strike_pick": "atm_only",
        "regime_gate": gate,
        "prior_day_spy_positive": prior,
    }
    if gate == "GREEN_OR_YELLOW_BOUNCE":
        entry["regime_yellow_frac_min"] = float(
            0.50 if yfrac is None else yfrac
        )
        entry["regime_yellow_require_bounce"] = bool(
            False if ybounce is None else ybounce
        )
    patch = {
        "entry": entry,
        "exit": {
            "take_profit_pct": tp,
            "stop_loss_pct": sl,
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
    desc = (
        f"stageA dte={dte} tp={tp} sl={sl} regime={gate} "
        f"prior={prior} hold={hold}"
    )
    return StageASpec(
        spec=_spec_from_overrides(vid, merged, description=desc),
        max_hold_sessions=hold,
    )


def _summarize_intraday(res: Any) -> dict[str, Any]:
    pnls = [t.net_pnl_pct for t in res.trades]
    n = len(pnls)
    mean_p = float(sum(pnls) / n) if n else 0.0
    wins = sum(1 for p in pnls if p > 0)
    return {
        "variant_id": res.variant_id,
        "n_trades": n,
        "mean_net_pnl_pct": round(mean_p, 6),
        "win_pct": round(100.0 * wins / n, 2) if n else 0.0,
        "n_entries_blocked": int(res.n_entries_blocked),
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


def _mark_stable_window_flags(
    rows: list[dict[str, Any]], windows: list[dict[str, Any]]
) -> None:
    stable_ids: set[str] = set()
    for w in windows:
        for vid in w.get("member_ids") or []:
            stable_ids.add(str(vid))
    for row in rows:
        row["stable_window"] = str(row.get("variant_id") or "") in stable_ids


def _scrub_forbidden(text: str) -> str:
    out = text
    for token in _FORBIDDEN_ARTIFACT:
        if token in out:
            out = out.replace(token, "REDACTED")
    return out


def _report_to_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Regime / Hold Optimizer Report")
    lines.append("")
    lines.append(f"- generated_at: `{payload.get('generated_at')}`")
    lines.append(f"- mode: `{payload.get('mode')}`")
    rec_status = (payload.get("recommendation") or {}).get("status")
    lines.append(f"- recommendation: **{rec_status}**")
    lines.append("")
    lines.append("## Safety")
    lines.append("")
    lines.append(
        "- Read-only research. Does not flip live gates. "
        "YAML snippet is always `active: false` (human paste only)."
    )
    lines.append("")

    sa = payload.get("stage_a")
    if sa:
        lines.append("## Stage A (daily discovery)")
        lines.append("")
        lines.append(f"- fidelity: `{sa.get('fidelity')}`")
        lines.append(f"- source: `{sa.get('source')}`")
        lines.append(f"- interval: `{sa.get('interval', '1d')}`")
        cov = sa.get("coverage") or {}
        if cov:
            lines.append(
                f"- coverage: {cov.get('start')} → {cov.get('end')} "
                f"n_bars={cov.get('n_bars')} n_sessions={cov.get('n_sessions')}"
            )
        lines.append(f"- disclaimer: {sa.get('disclaimer', '')}")
        lines.append("")
        ranking = sa.get("ranking") or []
        lines.append(
            "| variant | hold | n_train | train% | n_val | val% | n_test | "
            "test% | full% | StageB n/mean | residuals | familywise p | status |"
        )
        lines.append(
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|"
        )
        for r in ranking[:20]:
            stage_b = r.get("stage_b") or {}
            family_p = r.get("familywise_p_value")
            family_p_text = f"{float(family_p):.4f}" if family_p is not None else "—"
            stage_b_text = (
                f"{int(stage_b.get('n_trades') or 0)}/"
                f"{100 * float(stage_b.get('mean_net_pnl_pct') or 0.0):.2f}%"
            )
            lines.append(
                f"| `{r.get('variant_id')}` | {r.get('max_hold_sessions')} | "
                f"{r.get('n_train')} | "
                f"{100 * float(r.get('train_mean_net_pnl_pct') or 0):.2f} | "
                f"{r.get('n_validation')} | "
                f"{100 * float(r.get('validation_mean_net_pnl_pct') or 0):.2f} | "
                f"{r.get('n_test')} | "
                f"{100 * float(r.get('test_mean_net_pnl_pct') or 0):.2f} | "
                f"{100 * float(r.get('full_mean_net_pnl_pct') or 0):.2f} | "
                f"{stage_b_text} | {int(stage_b.get('residual_open') or 0)} | "
                f"{family_p_text} | {r.get('decision_status', 'RESEARCH ONLY')} |"
            )
        lines.append("")
        wins = sa.get("stable_windows") or []
        lines.append(f"### Stable windows ({len(wins)})")
        lines.append("")
        if not wins:
            lines.append("_None (no adjacent positive parameter cluster)._")
        else:
            for w in wins[:10]:
                lines.append(
                    f"- n={w.get('n_members')} min_mean="
                    f"{100 * float(w.get('min_holdout_mean_net_pnl_pct') or 0):.2f}% "
                    f"ids={', '.join(w.get('member_ids') or [])}"
                )
        lines.append("")

    sb = payload.get("stage_b")
    if sb:
        lines.append("## Stage B (15m session validation)")
        lines.append("")
        lines.append(f"- fidelity: `{sb.get('fidelity')}`")
        lines.append(f"- source: `{sb.get('source')}`")
        cov = sb.get("coverage") or {}
        lines.append(
            f"- coverage: {cov.get('start')} → {cov.get('end')} "
            f"n_bars={cov.get('n_bars')} n_sessions={cov.get('n_sessions')} "
            f"phases={cov.get('session_phases_observed')} "
            f"overnight={cov.get('has_overnight_bars')}"
        )
        if sb.get("overnight_unvalidated"):
            lines.append(
                "- **Note:** coverage lacks GTH/Curb — overnight/session-edge "
                "exits are **unvalidated** (not a hard failure by itself)."
            )
        lines.append("")
        for row in sb.get("results") or []:
            lines.append(
                f"- `{row.get('variant_id')}`: n={row.get('n_trades')} "
                f"mean={100 * float(row.get('mean_net_pnl_pct') or 0):.2f}% "
                f"win={row.get('win_pct')}%"
            )
        lines.append("")

    sens = payload.get("sensitivity") or []
    if sens:
        lines.append("## Sensitivity (IV × slippage)")
        lines.append("")
        for s in sens:
            iv_pos = s.get("iv_positive_count")
            slip_ok = s.get("slippage_1_5x_positive")
            lines.append(
                f"- `{s.get('variant_id')}`: "
                f"iv_positive={iv_pos}/4 slip_1.5x_pos={slip_ok}"
            )
        lines.append("")

    rec = payload.get("recommendation") or {}
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"- status: **{rec.get('status')}**")
    lines.append(f"- variant_id: `{rec.get('variant_id')}`")
    lines.append(f"- edge_reason: `{rec.get('edge_reason')}`")
    lines.append("")
    lines.append("### Inactive YAML snippet")
    lines.append("")
    lines.append("```yaml")
    lines.append((rec.get("yaml_snippet") or "# (none)").rstrip())
    lines.append("```")
    lines.append("")
    return _scrub_forbidden("\n".join(lines) + "\n")


def write_regime_hold_report(
    payload: dict[str, Any],
    out_dir: Path,
    *,
    stem: str | None = None,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if stem is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"regime_hold_{ts}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_text = _scrub_forbidden(json.dumps(payload, indent=2) + "\n")
    md_text = _report_to_markdown(payload)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    logger.info("wrote %s and %s", json_path, md_path)
    return json_path, md_path


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
    return {
        "n_bars": int(len(bars)),
        "n_sessions": n_sess,
        "start": start.isoformat() if hasattr(start, "isoformat") else str(start),
        "end": end.isoformat() if hasattr(end, "isoformat") else str(end),
        "interval": interval,
        "has_overnight_bars": False,
        "session_phases_observed": ["daily"],
    }


def _load_daily(
    args: argparse.Namespace,
) -> tuple[Any, str, dict[str, Any]]:
    """Return (bars, source, coverage). Raises on --require-uw failure."""
    if args.mode == "uw" and args.require_uw:
        bars, cov = load_uw_bars_strict(
            args.ticker,
            period=args.period,
            interval="1d",
            min_bars=max(50, int(args.min_trades) * 2),
            min_sessions=0,
        )
        return bars, "uw", cov
    bars, source = load_bars(
        mode=args.mode,
        interval="1d",
        ticker=args.ticker,
        period=args.period,
    )
    if args.require_uw and source != "uw":
        raise FixtureFallbackError(
            f"--require-uw but daily source={source} (fixture fallback refused)"
        )
    return bars, source, _daily_coverage(bars, "1d")


def _load_intraday(
    args: argparse.Namespace,
) -> tuple[Any, str, dict[str, Any]]:
    if args.mode == "uw" and args.require_uw:
        bars, cov = load_uw_bars_strict(
            args.ticker,
            period=args.intraday_period,
            interval="15m",
            min_bars=int(args.min_intraday_bars),
            min_sessions=int(args.min_intraday_sessions),
        )
        return bars, "uw", cov
    if args.mode == "uw":
        bars, source = load_bars(
            mode="uw",
            interval="15m",
            ticker=args.ticker,
            period=args.intraday_period,
        )
        if args.require_uw and source != "uw":
            raise FixtureFallbackError(
                f"--require-uw but intraday source={source}"
            )
        cov = bar_coverage(bars)
        if source == "uw":
            assert_intraday_coverage(
                bars,
                min_bars=int(args.min_intraday_bars),
                min_sessions=int(args.min_intraday_sessions),
            )
        return bars, source, cov
    # fixture mode
    bars, source = load_bars(mode="fixture", interval="15m", ticker=args.ticker)
    cov = bar_coverage(bars)
    return bars, source, cov


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    run_a = bool(args.stage_a)
    run_b = bool(args.stage_b)
    if not run_a and not run_b:
        run_a = True
        run_b = True

    if args.mode == "uw":
        _load_uw_key_from_tipdrop()

    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "kind": "regime_hold_optimizer",
        "pricing_fidelity": "modeled_bs_lite",
        "disclaimer": (
            "Modeled premiums (BS-lite). Relative research ranker only. "
            "Does NOT replace paper soak. Live trading gates untouched. "
            "YAML snippet is active:false — human paste only. "
            "Never auto-edits config."
        ),
        "args": {
            "period": args.period,
            "intraday_period": args.intraday_period,
            "split_frac": args.split_frac,
            "min_trades": args.min_trades,
            "min_intraday_trades": args.min_intraday_trades,
            "top_k": args.top_k,
            "mcpt": bool(args.mcpt),
            "coarse_to_fine": bool(args.coarse_to_fine),
            "require_uw": bool(args.require_uw),
            "stage_a": run_a,
            "stage_b": run_b,
        },
    }

    stage_a_payload: dict[str, Any] | None = None
    ranking: list[dict[str, Any]] = []
    daily_bars = None
    daily_source = "fixture"
    daily_cov: dict[str, Any] = {}
    finalists: list[dict[str, Any]] = []
    cell_by_id: dict[str, StageASpec] = {}
    overrides_by_id: dict[str, dict[str, Any]] = {}

    try:
        if run_a or run_b:
            # Stage B still needs Stage A finalists; load daily whenever A runs
            # or B needs a shortlist.
            if run_a or run_b:
                daily_bars, daily_source, daily_cov = _load_daily(args)
                if daily_source == "fixture_fallback":
                    print(
                        "WARN: --mode uw fell back to fixtures for daily bars. "
                        "Results are offline-synthetic, not UW history.",
                        file=sys.stderr,
                    )

        if run_a or run_b:
            logger.info(
                "Stage A discovery on %d daily bars source=%s",
                len(daily_bars) if daily_bars is not None else 0,
                daily_source,
            )
            stage_a_payload = run_stage_a(
                daily_bars,
                split_frac=float(args.split_frac),
                min_trades=int(args.min_trades),
                iv_seed=float(args.iv),
                source=daily_source,
                coarse_to_fine=bool(args.coarse_to_fine) if run_a else False,
                top_k=int(args.top_k),
                run_mcpt=bool(args.mcpt) if run_a else False,
                n_perm=int(args.mcpt_perm),
                allow_large=bool(args.allow_large),
                max_grid=int(args.max_grid),
                mode=args.mode,
                meta={
                    "ticker": args.ticker,
                    "period": args.period,
                    "n_bars": len(daily_bars) if daily_bars is not None else 0,
                },
            )
            ranking = list(stage_a_payload.get("ranking") or [])
            windows = stable_windows(ranking)
            _mark_stable_window_flags(ranking, windows)
            stage_a_payload["ranking"] = ranking
            stage_a_payload["stable_windows"] = windows
            stage_a_payload["coverage"] = daily_cov
            stage_a_payload["interval"] = "1d"
            if run_a:
                payload["stage_a"] = stage_a_payload
            finalists = _select_finalists(
                ranking, top_k=int(args.top_k), min_trades=int(args.min_trades)
            )
            for row in finalists:
                cell = _stage_a_spec_from_row(row)
                cell_by_id[cell.variant_id] = cell
                overrides_by_id[cell.variant_id] = deepcopy(cell.overrides)

    except FixtureFallbackError as exc:
        logger.error("UW strict load failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except InsufficientBarsError as exc:
        logger.error("UW coverage insufficient: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except GridBudgetError as exc:
        logger.error("%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    # Sensitivity on finalists (daily)
    sensitivity_list: list[dict[str, Any]] = []
    if (run_a or run_b) and finalists and daily_bars is not None:
        for row in finalists:
            cell = cell_by_id.get(str(row.get("variant_id") or ""))
            if cell is None:
                cell = _stage_a_spec_from_row(row)
            try:
                sens = run_sensitivity(cell, daily_bars, source=daily_source)
                sensitivity_list.append(sens)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sensitivity failed for %s: %s",
                    row.get("variant_id"),
                    exc,
                )
        if run_a:
            payload["sensitivity"] = sensitivity_list

    # Stage B
    stage_b_block: dict[str, Any] | None = None
    intraday_by_id: dict[str, dict[str, Any]] = {}
    if run_b:
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

        phases = list(icov.get("session_phases_observed") or [])
        overnight_unvalidated = not (
            "GTH" in phases and "Curb" in phases
        )
        # Fixture mode: do not enforce UW floors (would always fail).
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

        results_b: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="xsp_rhb_rules_") as tmp:
            tmp_path = Path(tmp)
            for row in finalists:
                cell = cell_by_id.get(str(row.get("variant_id") or ""))
                if cell is None:
                    cell = _stage_a_spec_from_row(row)
                rpath = rules_path_for_spec(cell.spec, tmp_dir=tmp_path)
                res = run_intraday_backtest(
                    ibars,
                    rpath,
                    variant_id=cell.variant_id,
                    iv_seed=float(args.iv),
                    source=isource,
                    max_hold_sessions=cell.max_hold_sessions,
                    daily_context=daily_bars,
                )
                summary = _summarize_intraday(res)
                summary["max_hold_sessions"] = cell.max_hold_sessions
                # Optional holdout on intraday when enough trades
                if res.trades and len(ibars) > 10:
                    train, holdout, split_iso = partition_trades_by_split(
                        res.trades, ibars, split_frac=float(args.split_frac)
                    )
                    summary["n_train"] = len(train)
                    summary["n_holdout"] = len(holdout)
                    summary["split_ts"] = split_iso
                    if holdout:
                        hm = sum(t.net_pnl_pct for t in holdout) / len(holdout)
                        summary["holdout_mean_net_pnl_pct"] = round(hm, 6)
                results_b.append(summary)
                intraday_by_id[cell.variant_id] = summary
                row["stage_b"] = summary

        stage_b_block = {
            "fidelity": "intraday_15m_session_aware",
            "pricing_fidelity": "modeled_bs_lite",
            "source": isource,
            "interval": "15m",
            "coverage": icov,
            "overnight_unvalidated": overnight_unvalidated,
            "disclaimer": (
                "Stage B: entries only in [15:45,16:00) ET; exits gated by "
                "live xsp_session_open. Modeled premiums. "
                + (
                    "Observed phases lack GTH and/or Curb — overnight edges "
                    "unvalidated (informational, not a hard failure)."
                    if overnight_unvalidated
                    else "GTH+RTH+Curb phases observed in coverage."
                )
            ),
            "results": results_b,
        }
        payload["stage_b"] = stage_b_block
        if not run_a:
            # Still attach lightweight stage A ranking context for attribution
            payload["stage_a_context"] = {
                "source": daily_source,
                "coverage": daily_cov,
                "finalists": [r.get("variant_id") for r in finalists],
            }
        if sensitivity_list and "sensitivity" not in payload:
            payload["sensitivity"] = sensitivity_list

    # Evaluate rank-ordered finalists; never borrow another variant's sensitivity.
    sensitivity_by_id = {
        str(sensitivity.get("variant_id") or ""): sensitivity
        for sensitivity in sensitivity_list
    }
    candidate_rows = finalists if finalists else ranking[:1]
    rec_row, edge_ok, edge_reason = _select_edge_candidate(
        candidate_rows,
        sensitivity_by_id=sensitivity_by_id,
        intraday_by_id=intraday_by_id,
        run_b=run_b,
        min_trades=int(args.min_trades),
        min_intraday_trades=int(args.min_intraday_trades),
    )

    pricing_fidelity = str(payload.get("pricing_fidelity") or "modeled_bs_lite")
    can_promote = promotion_eligible(
        edge_ok,
        pricing_fidelity=pricing_fidelity,
        paper_confirmation=payload.get("paper_confirmation") is True,
    )
    status = "RESEARCH-SURVIVOR (inactive)" if edge_ok else "RESEARCH ONLY"
    rec_variant_id = str(rec_row.get("variant_id") or "") if rec_row else ""
    for row in ranking:
        row["decision_status"] = (
            "RESEARCH-SURVIVOR (inactive)"
            if str(row.get("variant_id") or "") == rec_variant_id and edge_ok
            else "RESEARCH ONLY"
        )
    yaml_snip = ""
    if rec_row is not None:
        ov = overrides_by_id.get(str(rec_row.get("variant_id") or ""))
        if ov is None:
            ov = _stage_a_spec_from_row(rec_row).overrides
        yaml_snip = recommended_regime_hold_yaml(
            rec_row,
            ov,
            min_trades=int(args.min_trades),
            edge_ok=edge_ok,
            max_hold_sessions=int(rec_row.get("max_hold_sessions") or 0),
        )

    payload["recommendation"] = {
        "status": status,
        "variant_id": rec_row.get("variant_id") if rec_row else None,
        "edge_ok": edge_ok,
        "edge_reason": edge_reason,
        "pricing_fidelity": pricing_fidelity,
        "promotion_eligible": can_promote,
        "row": rec_row,
        "yaml_snippet": yaml_snip,
    }
    # Top-level convenience aliases used by tests
    payload["yaml_snippet"] = yaml_snip
    if stage_a_payload and run_a:
        payload["stable_windows"] = stage_a_payload.get("stable_windows") or []
    if stage_b_block:
        payload["intraday_coverage"] = stage_b_block.get("coverage")

    # Scrub any accidental secrets from nested structures before write
    raw = json.dumps(payload)
    for token in _FORBIDDEN_ARTIFACT:
        if token in raw:
            logger.warning("scrubbing forbidden token from payload: %s", token)
            # re-parse after string scrub
            raw = raw.replace(token, "REDACTED")
            payload = json.loads(raw)
            break

    json_path, md_path = write_regime_hold_report(payload, Path(args.out))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"recommendation: {status} ({edge_reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
