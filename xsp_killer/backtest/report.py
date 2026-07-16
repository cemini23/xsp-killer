"""Ranked backtest report (JSON + markdown) and MCPT-lite sign-flip gate."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from xsp_killer.backtest.engine import BacktestResult

logger = logging.getLogger("xsp_killer.backtest.report")


def mcpt(
    pnl_pct: Any,
    n_perm: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Monte Carlo permutation test (sign-flip). H0: mean PnL is zero.

    Ported from cemini ``backtest_common/mcpt_gate.py`` (numpy-only).
    ``pass_5pct = p < 0.05 and mean > 0``. Graceful if numpy missing.
    """
    try:
        import numpy as np
    except ImportError:
        return {
            "n_trades": 0,
            "observed_mean_pct": 0.0,
            "p_value": 1.0,
            "pass_5pct": False,
            "note": "numpy missing — MCPT skipped",
        }

    pnl = np.asarray(pnl_pct, dtype=float)
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) < 5:
        return {
            "n_trades": int(len(pnl)),
            "observed_mean_pct": float(np.mean(pnl)) if len(pnl) else 0.0,
            "p_value": 1.0,
            "pass_5pct": False,
            "note": "too few trades",
        }
    obs = float(np.mean(pnl))
    rng = np.random.default_rng(seed)
    count = 0
    for _ in range(n_perm):
        signs = rng.choice([-1.0, 1.0], size=len(pnl))
        if float(np.mean(pnl * signs)) >= obs:
            count += 1
    p_val = (count + 1) / (n_perm + 1)
    return {
        "n_trades": int(len(pnl)),
        "observed_mean_pct": obs,
        "p_value": float(p_val),
        "pass_5pct": bool(p_val < 0.05 and obs > 0),
        "n_perm": n_perm,
    }


def _summarize_result(
    res: BacktestResult, *, run_mcpt: bool = False, n_perm: int = 2000
) -> dict[str, Any]:
    pnls = [t.net_pnl_pct for t in res.trades]
    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    reasons = Counter(t.exit_reason for t in res.trades)
    mean_p = float(sum(pnls) / n) if n else 0.0
    med_p = float(median(pnls)) if n else 0.0
    total_usd = float(sum(t.pnl_usd for t in res.trades))
    row: dict[str, Any] = {
        "variant_id": res.variant_id,
        "n_trades": n,
        "win_pct": round(100.0 * wins / n, 2) if n else 0.0,
        "mean_net_pnl_pct": round(mean_p, 6),
        "median_net_pnl_pct": round(med_p, 6),
        "total_pnl_usd": round(total_usd, 2),
        "exit_reasons": dict(reasons),
        "max_hold_hits": int(reasons.get("time_stop", 0)),
        "end_of_series": int(reasons.get("end_of_series", 0)),
        "n_entries_blocked": res.n_entries_blocked,
        "source": res.source,
    }
    if run_mcpt:
        row["mcpt"] = mcpt(pnls, n_perm=n_perm)
        row["mcpt_p"] = row["mcpt"].get("p_value")
        row["mcpt_pass_5pct"] = row["mcpt"].get("pass_5pct")
    return row


def healthy_windows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag sweep_* variants with positive mean and MCPT pass (when available)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        vid = str(r.get("variant_id") or "")
        if not vid.startswith("sweep_"):
            continue
        mean_p = float(r.get("mean_net_pnl_pct") or 0.0)
        pass5 = r.get("mcpt_pass_5pct")
        if mean_p > 0 and (pass5 is True or pass5 is None):
            # Without MCPT, positive mean only → "candidate (MCPT not run)"
            status = (
                "healthy"
                if pass5 is True
                else ("candidate" if pass5 is None else "noise")
            )
            if pass5 is False:
                status = "noise / needs soak"
            out.append(
                {
                    "variant_id": vid,
                    "mean_net_pnl_pct": mean_p,
                    "status": status,
                    "mcpt_pass_5pct": pass5,
                }
            )
        elif mean_p <= 0 or pass5 is False:
            out.append(
                {
                    "variant_id": vid,
                    "mean_net_pnl_pct": mean_p,
                    "status": "noise / needs soak",
                    "mcpt_pass_5pct": pass5,
                }
            )
    return out


def build_report(
    results: list[BacktestResult],
    *,
    run_mcpt: bool = False,
    n_perm: int = 2000,
    mode: str = "fixture",
    source: str = "fixture",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [
        _summarize_result(r, run_mcpt=run_mcpt, n_perm=n_perm) for r in results
    ]
    rows.sort(key=lambda r: r.get("mean_net_pnl_pct", 0.0), reverse=True)
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "source": source,
        "disclaimer": (
            "Modeled option premiums from SPY OHLC (BS-lite). Not historical fills. "
            "Relative ranker only — does NOT replace paper soak for LIVE promotion. "
            "LIVE_ENTRIES/LIVE_EXITS untouched."
        ),
        "n_variants": len(rows),
        "ranking": rows,
        "healthy_windows": healthy_windows(rows),
        "trades": {
            r.variant_id: [t.to_dict() for t in r.trades] for r in results
        },
        "meta": meta or {},
    }
    return payload


def report_to_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Lane A backtest ranking")
    lines.append("")
    lines.append(f"- generated: `{payload.get('generated_at')}`")
    lines.append(f"- mode/source: `{payload.get('mode')}` / `{payload.get('source')}`")
    lines.append(f"- variants: **{payload.get('n_variants')}**")
    lines.append("")
    lines.append(f"> {payload.get('disclaimer')}")
    lines.append("")
    lines.append("## Ranked table (by mean net %)")
    lines.append("")
    has_mcpt = any("mcpt_p" in r for r in payload.get("ranking") or [])
    if has_mcpt:
        lines.append(
            "| rank | variant | n | win% | mean net% | median% "
            "| total $ | MCPT p | pass@5% |"
        )
        lines.append(
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
        )
    else:
        lines.append(
            "| rank | variant | n | win% | mean net% | median% | total $ | exits |"
        )
        lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |")

    for i, r in enumerate(payload.get("ranking") or [], 1):
        exits = r.get("exit_reasons") or {}
        exit_s = ", ".join(f"{k}:{v}" for k, v in exits.items()) or "—"
        if has_mcpt:
            p = r.get("mcpt_p")
            p_s = f"{p:.4f}" if isinstance(p, float) else "—"
            pass_s = str(r.get("mcpt_pass_5pct"))
            lines.append(
                f"| {i} | `{r['variant_id']}` | {r['n_trades']} | "
                f"{r['win_pct']:.1f} | {100 * r['mean_net_pnl_pct']:.2f} | "
                f"{100 * r['median_net_pnl_pct']:.2f} | {r['total_pnl_usd']:.2f} | "
                f"{p_s} | {pass_s} |"
            )
        else:
            lines.append(
                f"| {i} | `{r['variant_id']}` | {r['n_trades']} | "
                f"{r['win_pct']:.1f} | {100 * r['mean_net_pnl_pct']:.2f} | "
                f"{100 * r['median_net_pnl_pct']:.2f} | {r['total_pnl_usd']:.2f} | "
                f"{exit_s} |"
            )

    lines.append("")
    lines.append("## Healthy windows (sweep axes)")
    lines.append("")
    hw = payload.get("healthy_windows") or []
    if not hw:
        lines.append("_No sweep rows (or none flagged)._")
    else:
        lines.append("| variant | mean net% | status |")
        lines.append("| --- | ---: | --- |")
        for h in hw:
            lines.append(
                f"| `{h['variant_id']}` | {100 * h['mean_net_pnl_pct']:.2f} | "
                f"{h['status']} |"
            )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_report(
    payload: dict[str, Any],
    out_dir: Path,
    *,
    stem: str | None = None,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if stem is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"lane_a_bt_{ts}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(report_to_markdown(payload), encoding="utf-8")
    logger.info("wrote %s and %s", json_path, md_path)
    return json_path, md_path


def print_ranking_table(payload: dict[str, Any]) -> None:
    """Print a compact ranked table to stdout."""
    print(report_to_markdown(payload))
