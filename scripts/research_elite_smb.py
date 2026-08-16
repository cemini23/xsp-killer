#!/usr/bin/env python3
"""Elite hunt: Cemini wiki SMB put-credit + FOMC gates (K79 / K155 / K233).

Sources (not used in the 16 Aug first hunt):
  tipdrop-kit/projects/llm-wiki-by-cemini/wiki/concepts/xsp-put-credit-spread-small-account-smb.md
  wiki/concepts/options-capital-velocity-credit-spreads-smb.md
  wiki/concepts/fomc-iv-surface-dynamics.md
  Fed FOMC calendars 2021-2026 (federalreserve.gov)

LIVE gates untouched. rv20 marking. Report return on max risk, not just
return on credit. Elite bar is in the report, not inferred from a 400-cell grid.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_edge_hunt import (  # noqa: E402
    STRIKE_STEP,
    _atm,
    _bucket,
    _friday_exit_index,
    _leg,
    _net_pct,
    _split_bounds,
    _spread_value,
    load_rh_daily,
)
from research_vol_dte_hunt import _ann_vol  # noqa: E402
from xsp_killer.paper_economics import PaperEconomics  # noqa: E402

# Decision-day (last day of each scheduled/unscheduled FOMC).
# 2021-2026 from https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# 2016-2020 from the Fed historical calendars (standard announcement Wednesdays
# plus 2020-03-03 and 2020-03-15 unscheduled).
FOMC: tuple[date, ...] = (
    date(2016, 1, 27), date(2016, 3, 16), date(2016, 4, 27), date(2016, 6, 15),
    date(2016, 7, 27), date(2016, 9, 21), date(2016, 11, 2), date(2016, 12, 14),
    date(2017, 2, 1), date(2017, 3, 15), date(2017, 5, 3), date(2017, 6, 14),
    date(2017, 7, 26), date(2017, 9, 20), date(2017, 11, 1), date(2017, 12, 13),
    date(2018, 1, 31), date(2018, 3, 21), date(2018, 5, 2), date(2018, 6, 13),
    date(2018, 8, 1), date(2018, 9, 26), date(2018, 11, 8), date(2018, 12, 19),
    date(2019, 1, 30), date(2019, 3, 20), date(2019, 5, 1), date(2019, 6, 19),
    date(2019, 7, 31), date(2019, 9, 18), date(2019, 10, 30), date(2019, 12, 11),
    date(2020, 1, 29), date(2020, 3, 3), date(2020, 3, 15), date(2020, 4, 29),
    date(2020, 6, 10), date(2020, 7, 29), date(2020, 9, 16), date(2020, 11, 5),
    date(2020, 12, 16),
    date(2021, 1, 27), date(2021, 3, 17), date(2021, 4, 28), date(2021, 6, 16),
    date(2021, 7, 28), date(2021, 9, 22), date(2021, 11, 3), date(2021, 12, 15),
    date(2022, 1, 26), date(2022, 3, 16), date(2022, 5, 4), date(2022, 6, 15),
    date(2022, 7, 27), date(2022, 9, 21), date(2022, 11, 2), date(2022, 12, 14),
    date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14),
    date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13),
    date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
    date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18),
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7), date(2025, 6, 18),
    date(2025, 7, 30), date(2025, 9, 17), date(2025, 10, 29), date(2025, 12, 10),
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29),
)


def _near_fomc(d: date, before: int = 2, after: int = 1) -> bool:
    for f in FOMC:
        if f - timedelta(days=before) <= d <= f + timedelta(days=after):
            return True
    return False


def _sessions_until_fomc(dates: list[date], i: int) -> int | None:
    today = dates[i]
    later = [f for f in FOMC if f >= today]
    if not later:
        return None
    target = later[0]
    for k in range(i, len(dates)):
        if dates[k] >= target:
            return k - i
    return None


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 6) if xs else None


def summarize(trades: list[dict[str, Any]], n_bars: int) -> dict[str, Any]:
    train_end, val_end = _split_bounds(n_bars)
    buckets = {"train": [], "val": [], "test": []}
    yearly: dict[int, list[float]] = {}
    for t in trades:
        buckets[_bucket(t["i"], train_end, val_end)].append(t["roc_risk"])
        yearly.setdefault(t["year"], []).append(t["roc_risk"])
    full = [t["roc_risk"] for t in trades]
    credit = [t["roc_credit"] for t in trades]
    dollars = [t["pnl_usd"] for t in trades]
    test = buckets["test"]
    elite = bool(
        len(test) >= 30
        and _mean(buckets["train"]) is not None
        and _mean(buckets["val"]) is not None
        and _mean(test) is not None
        and _mean(buckets["train"]) > 0
        and _mean(buckets["val"]) > 0
        and _mean(test) > 0
        and _mean(full) is not None
        and _mean(full) > 0
        and yearly.get(2025)
        and (sum(yearly[2025]) / len(yearly[2025])) >= 0
        and (sum(1 for x in full if x > 0) / len(full)) >= 0.65
        and _mean(test) >= 0.03
    )
    return {
        "n": len(trades),
        "n_test": len(test),
        "train_roc_risk": _mean(buckets["train"]),
        "val_roc_risk": _mean(buckets["val"]),
        "test_roc_risk": _mean(test),
        "full_roc_risk": _mean(full),
        "full_roc_credit": _mean(credit),
        "mean_pnl_usd": _mean(dollars),
        "win_pct": round(100.0 * sum(1 for x in full if x > 0) / len(full), 2) if full else None,
        "yearly_roc_risk": {
            str(y): round(sum(xs) / len(xs), 4) for y, xs in sorted(yearly.items())
        },
        "yearly_n": {str(y): len(xs) for y, xs in sorted(yearly.items())},
        "elite": elite,
        "pricing_fidelity": "modeled_bs_rv20",
    }


def run_put_credit(
    df: pd.DataFrame,
    *,
    name: str,
    width: float,
    dte: int,
    hold: int,
    require_above_ma: bool,
    require_reclaim: bool,
    require_quiet: bool,
    skip_fomc: bool,
    dma_exit: bool,
    velocity_pct: float | None,
    econ: PaperEconomics,
) -> dict[str, Any]:
    dates = list(df["date"])
    trades: list[dict[str, Any]] = []
    for i in range(25, len(df) - 1):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        if require_above_ma and not bool(row["above_ma20"]):
            continue
        if require_reclaim and not bool(row["reclaim_ma20"]):
            continue
        if require_quiet:
            vp = row["yest_vol_pctile"]
            if vp is None or pd.isna(vp) or float(vp) > 0.33:
                continue
        if skip_fomc and _near_fomc(row["date"], before=2, after=1):
            continue
        rv = _ann_vol(df, i - 1)
        if rv is None:
            continue
        iv_e = min(max(rv, 0.08), 0.80)
        spot = float(row["close"])
        long_k = _atm(spot)  # long lower put
        short_k = long_k  # sell ATM
        long_put_k = long_k - width
        last = _friday_exit_index(df, i, hold)
        entry = _spread_value("put", spot, short_k, long_put_k, width, dte, iv_e)
        if entry <= 0 or entry >= width:
            continue
        max_risk = width - entry
        exit_mid = entry
        for j in range(i + 1, last + 1):
            dte_x = max(0, dte - (df.iloc[j]["date"] - row["date"]).days)
            rv_j = _ann_vol(df, j - 1) or iv_e
            iv_x = min(max(rv_j, 0.08), 0.80)
            mark = _spread_value(
                "put",
                float(df.iloc[j]["close"]),
                short_k,
                long_put_k,
                width,
                dte_x,
                iv_x,
            )
            if dma_exit and not bool(df.iloc[j]["above_ma20"]):
                exit_mid = mark
                break
            if velocity_pct is not None and entry > 0:
                captured = (entry - mark) / entry
                if captured >= velocity_pct:
                    exit_mid = mark
                    break
            exit_mid = mark
        # Short the debit: pnl_points = entry - exit (after slip via fills)
        fill_in = entry  # mid; apply econ on both sides via _net_pct then scale
        roc_credit = -_net_pct(entry, exit_mid, econ)
        pnl_points = roc_credit * fill_in
        roc_risk = pnl_points / max_risk if max_risk > 0 else 0.0
        trades.append(
            {
                "i": i,
                "year": row["date"].year,
                "roc_credit": roc_credit,
                "roc_risk": roc_risk,
                "pnl_usd": pnl_points * 100.0,  # XSP $100/point
            }
        )
    out = summarize(trades, len(df))
    out["name"] = name
    out["width"] = width
    out["dte"] = dte
    return out


def run_k233_long_call(df: pd.DataFrame, econ: PaperEconomics) -> dict[str, Any]:
    """Wiki K233: long short-dated call 3 sessions before FOMC, exit T+1."""
    dates = list(df["date"])
    trades: list[dict[str, Any]] = []
    for i in range(25, len(df) - 2):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        until = _sessions_until_fomc(dates, i)
        if until != 3:
            continue
        rv = _ann_vol(df, i - 1)
        if rv is None:
            continue
        iv_e = min(max(rv, 0.08), 0.80)
        spot = float(row["close"])
        k = _atm(spot)
        entry = _leg("call", spot, k, 14, iv_e)
        # exit first session on/after FOMC+1
        fomc_i = i + 3
        exit_i = min(fomc_i + 1, len(df) - 1)
        dte_x = max(0, 14 - (df.iloc[exit_i]["date"] - row["date"]).days)
        rv_x = _ann_vol(df, exit_i - 1) or iv_e
        exit_mid = _leg("call", float(df.iloc[exit_i]["close"]), k, dte_x, min(max(rv_x, 0.08), 0.80))
        roc = _net_pct(entry, exit_mid, econ)
        trades.append(
            {
                "i": i,
                "year": row["date"].year,
                "roc_credit": roc,
                "roc_risk": roc,
                "pnl_usd": roc * entry * 100.0,
            }
        )
    out = summarize(trades, len(df))
    out["name"] = "k233_long_call_tminus3"
    return out


def run_fomc_crush(df: pd.DataFrame, econ: PaperEconomics) -> dict[str, Any]:
    """Enter put credit T-1 if above 20DMA, exit T+1 (event crush)."""
    dates = list(df["date"])
    trades: list[dict[str, Any]] = []
    width = 5.0
    dte = 14
    for i in range(25, len(df) - 2):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        until = _sessions_until_fomc(dates, i)
        if until != 1:
            continue
        if not bool(row["above_ma20"]):
            continue
        rv = _ann_vol(df, i - 1)
        if rv is None:
            continue
        iv_e = min(max(rv, 0.08), 0.80)
        spot = float(row["close"])
        short_k = _atm(spot)
        long_k = short_k - width
        entry = _spread_value("put", spot, short_k, long_k, width, dte, iv_e)
        if entry <= 0 or entry >= width:
            continue
        exit_i = min(i + 2, len(df) - 1)
        dte_x = max(0, dte - (df.iloc[exit_i]["date"] - row["date"]).days)
        rv_x = _ann_vol(df, exit_i - 1) or iv_e
        exit_mid = _spread_value(
            "put",
            float(df.iloc[exit_i]["close"]),
            short_k,
            long_k,
            width,
            dte_x,
            min(max(rv_x, 0.08), 0.80),
        )
        roc_credit = -_net_pct(entry, exit_mid, econ)
        max_risk = width - entry
        pnl_points = roc_credit * entry
        trades.append(
            {
                "i": i,
                "year": row["date"].year,
                "roc_credit": roc_credit,
                "roc_risk": pnl_points / max_risk if max_risk > 0 else 0.0,
                "pnl_usd": pnl_points * 100.0,
            }
        )
    out = summarize(trades, len(df))
    out["name"] = "fomc_crush_put_credit_tminus1"
    return out


def main() -> int:
    df = load_rh_daily(ROOT / ".local" / "research" / "spy_daily_10y.json")
    df["ma20"] = df["close"].rolling(20).mean()
    df["above_ma20"] = df["close"] > df["ma20"]
    prev_above = df["above_ma20"].shift(1)
    df["reclaim_ma20"] = df["above_ma20"] & (prev_above == False)
    econ = PaperEconomics.from_yaml()

    cells = [
        run_put_credit(
            df, name="smb_above_ma_w5", width=5.0, dte=14, hold=5,
            require_above_ma=True, require_reclaim=False, require_quiet=False,
            skip_fomc=False, dma_exit=True, velocity_pct=0.76, econ=econ,
        ),
        run_put_credit(
            df, name="smb_reclaim_ma_w5", width=5.0, dte=14, hold=5,
            require_above_ma=True, require_reclaim=True, require_quiet=False,
            skip_fomc=False, dma_exit=True, velocity_pct=0.76, econ=econ,
        ),
        run_put_credit(
            df, name="smb_above_ma_quiet", width=5.0, dte=14, hold=5,
            require_above_ma=True, require_reclaim=False, require_quiet=True,
            skip_fomc=False, dma_exit=True, velocity_pct=0.76, econ=econ,
        ),
        run_put_credit(
            df, name="smb_above_ma_fomc_skip", width=5.0, dte=14, hold=5,
            require_above_ma=True, require_reclaim=False, require_quiet=False,
            skip_fomc=True, dma_exit=True, velocity_pct=0.76, econ=econ,
        ),
        run_put_credit(
            df, name="smb_above_ma_quiet_fomc_skip", width=5.0, dte=14, hold=5,
            require_above_ma=True, require_reclaim=False, require_quiet=True,
            skip_fomc=True, dma_exit=True, velocity_pct=0.76, econ=econ,
        ),
        run_put_credit(
            df, name="smb_above_ma_w1", width=1.0, dte=14, hold=5,
            require_above_ma=True, require_reclaim=False, require_quiet=False,
            skip_fomc=False, dma_exit=True, velocity_pct=0.76, econ=econ,
        ),
        run_put_credit(
            df, name="smb_above_ma_quiet_fomc_skip_w1", width=1.0, dte=14, hold=5,
            require_above_ma=True, require_reclaim=False, require_quiet=True,
            skip_fomc=True, dma_exit=True, velocity_pct=0.76, econ=econ,
        ),
        run_put_credit(
            df, name="smb_above_ma_no_velocity", width=5.0, dte=14, hold=5,
            require_above_ma=True, require_reclaim=False, require_quiet=False,
            skip_fomc=False, dma_exit=True, velocity_pct=None, econ=econ,
        ),
        run_k233_long_call(df, econ),
        run_fomc_crush(df, econ),
    ]

    elite = [c for c in cells if c.get("elite")]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "elite_smb_fomc",
        "cemini_sources": [
            "wiki/concepts/xsp-put-credit-spread-small-account-smb.md",
            "wiki/concepts/options-capital-velocity-credit-spreads-smb.md",
            "wiki/concepts/fomc-iv-surface-dynamics.md",
            "federalreserve.gov/monetarypolicy/fomccalendars.htm",
        ],
        "elite_bar": (
            "train/val/test roc_max_risk>0, n_test>=30, 2025>=0, "
            "win>=65%, test roc_max_risk>=3%"
        ),
        "disclaimer": (
            "Modeled BS rv20, not historical XSP fills. LIVE off. "
            "roc_risk = P&L / (width - credit)."
        ),
        "n_cells": len(cells),
        "n_elite": len(elite),
        "cells": cells,
    }
    out_dir = ROOT / "reports" / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = out_dir / f"elite_smb_{stamp}.json"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Elite hunt — Cemini SMB put-credit + FOMC",
        "",
        f"- elite bar: {payload['elite_bar']}",
        f"- elite cells: {len(elite)} / {len(cells)}",
        "",
        "| name | n | test n | train | val | test | full | win% | 2025 | elite |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for c in cells:
        y = c.get("yearly_roc_risk") or {}
        lines.append(
            f"| `{c['name']}` | {c['n']} | {c['n_test']} | "
            f"{c['train_roc_risk']} | {c['val_roc_risk']} | {c['test_roc_risk']} | "
            f"{c['full_roc_risk']} | {c['win_pct']} | {y.get('2025', '')} | "
            f"{c['elite']} |"
        )
    out_md = out_dir / f"elite_smb_{stamp}.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    print(f"elite={len(elite)}")
    for c in cells:
        print(
            c["name"],
            "n",
            c["n"],
            "te",
            c["test_roc_risk"],
            "2025",
            (c.get("yearly_roc_risk") or {}).get("2025"),
            "elite",
            c["elite"],
            "win",
            c["win_pct"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
