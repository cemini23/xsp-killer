#!/usr/bin/env python3
"""Contender hunt outside the Lane A long-call book.

Pre-registered books (not a 400-cell grid):
  - 16-delta-ish OTM put credit (short ATM-5 / long ATM-10) above 20-DMA
  - Call credit only when below 20-DMA (bear twin)
  - Iron condor above 20-DMA (both wings)
  - Turn-of-month put credit (last 3 + first 2 sessions)
  - 7 DTE and 21 DTE ATM put credit above 20-DMA

Same elite bar as research_elite_smb.py. LIVE untouched. rv20 marks.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timezone
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
from research_elite_smb import summarize  # noqa: E402
from research_vol_dte_hunt import _ann_vol  # noqa: E402
from xsp_killer.fomc_calendar import near_fomc  # noqa: E402
from xsp_killer.paper_economics import PaperEconomics  # noqa: E402
from xsp_killer.put_credit import select_long_put_strike  # noqa: E402


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 6) if xs else None


def _iv(df: pd.DataFrame, i: int) -> float | None:
    rv = _ann_vol(df, i - 1)
    if rv is None:
        return None
    return min(max(rv, 0.08), 0.80)


def _tom(d: date, dates: list[date]) -> bool:
    """Last 3 or first 2 sessions of the calendar month."""
    same = [x for x in dates if x.year == d.year and x.month == d.month]
    if d not in same:
        return False
    idx = same.index(d)
    return idx < 2 or idx >= len(same) - 3


def run_book(
    df: pd.DataFrame,
    *,
    name: str,
    side: str,
    short_steps_from_atm: int,
    width: float,
    dte: int,
    require_above: bool | None,
    turn_of_month: bool,
    skip_fomc: bool,
    econ: PaperEconomics,
) -> dict[str, Any]:
    dates = list(df["date"])
    trades: list[dict[str, Any]] = []
    hold = 5
    for i in range(25, len(df) - 1):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        if skip_fomc and near_fomc(row["date"], before=2, after=1):
            continue
        if require_above is True and not bool(row["above_ma20"]):
            continue
        if require_above is False and bool(row["above_ma20"]):
            continue
        if turn_of_month and not _tom(row["date"], dates):
            continue
        iv = _iv(df, i)
        if iv is None:
            continue
        spot = float(row["close"])
        atm = _atm(spot)
        if side == "put_credit":
            short_k = atm - short_steps_from_atm * STRIKE_STEP
            long_k = short_k - width
            entry = _spread_value("put", spot, short_k, long_k, width, dte, iv)
            kind = "put"
        elif side == "call_credit":
            short_k = atm + short_steps_from_atm * STRIKE_STEP
            long_k = short_k + width
            entry = _spread_value("call", spot, short_k, long_k, width, dte, iv)
            kind = "call"
        elif side == "iron_condor":
            p_short = atm
            p_long = atm - width
            c_short = atm
            c_long = atm + width
            p_ent = _spread_value("put", spot, p_short, p_long, width, dte, iv)
            c_ent = _spread_value("call", spot, c_short, c_long, width, dte, iv)
            entry = p_ent + c_ent
            kind = "iron"
            width_ic = width * 2
        else:
            raise ValueError(side)
        if entry <= 0:
            continue
        last = _friday_exit_index(df, i, hold)
        exit_mid = entry
        for j in range(i + 1, last + 1):
            dte_x = max(0, dte - (df.iloc[j]["date"] - row["date"]).days)
            iv_x = _iv(df, j) or iv
            s = float(df.iloc[j]["close"])
            if side == "iron_condor":
                mark = _spread_value("put", s, p_short, p_long, width, dte_x, iv_x) + _spread_value(
                    "call", s, c_short, c_long, width, dte_x, iv_x
                )
            else:
                mark = _spread_value(kind, s, short_k, long_k, width, dte_x, iv_x)
            captured = (entry - mark) / entry if entry else 0.0
            if captured >= 0.76:
                exit_mid = mark
                break
            if require_above is True and not bool(df.iloc[j]["above_ma20"]):
                exit_mid = mark
                break
            if require_above is False and bool(df.iloc[j]["above_ma20"]):
                exit_mid = mark
                break
            exit_mid = mark
        roc_credit = -_net_pct(entry, exit_mid, econ)
        risk_w = width_ic if side == "iron_condor" else width
        max_risk = risk_w - entry
        pnl = roc_credit * entry
        trades.append(
            {
                "i": i,
                "year": row["date"].year,
                "roc_credit": roc_credit,
                "roc_risk": pnl / max_risk if max_risk > 0 else 0.0,
                "pnl_usd": pnl * 100.0,
            }
        )
    out = summarize(trades, len(df))
    out["name"] = name
    return out


def main() -> int:
    df = load_rh_daily(ROOT / ".local" / "research" / "spy_daily_10y.json")
    df["ma20"] = df["close"].rolling(20).mean()
    df["above_ma20"] = df["close"] > df["ma20"]
    econ = PaperEconomics.from_yaml()
    books = [
        run_book(
            df, name="otm16_put_credit_above_ma", side="put_credit",
            short_steps_from_atm=1, width=5.0, dte=14, require_above=True,
            turn_of_month=False, skip_fomc=True, econ=econ,
        ),
        run_book(
            df, name="call_credit_below_ma", side="call_credit",
            short_steps_from_atm=0, width=5.0, dte=14, require_above=False,
            turn_of_month=False, skip_fomc=True, econ=econ,
        ),
        run_book(
            df, name="iron_condor_above_ma", side="iron_condor",
            short_steps_from_atm=0, width=5.0, dte=14, require_above=True,
            turn_of_month=False, skip_fomc=True, econ=econ,
        ),
        run_book(
            df, name="tom_put_credit_above_ma", side="put_credit",
            short_steps_from_atm=0, width=5.0, dte=14, require_above=True,
            turn_of_month=True, skip_fomc=True, econ=econ,
        ),
        run_book(
            df, name="put_credit_7dte_above_ma", side="put_credit",
            short_steps_from_atm=0, width=5.0, dte=7, require_above=True,
            turn_of_month=False, skip_fomc=True, econ=econ,
        ),
        run_book(
            df, name="put_credit_21dte_above_ma", side="put_credit",
            short_steps_from_atm=0, width=5.0, dte=21, require_above=True,
            turn_of_month=False, skip_fomc=True, econ=econ,
        ),
        run_book(
            df, name="otm16_call_credit_below_ma", side="call_credit",
            short_steps_from_atm=1, width=5.0, dte=14, require_above=False,
            turn_of_month=False, skip_fomc=True, econ=econ,
        ),
    ]
    elite = [b for b in books if b.get("elite")]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "contender_edges",
        "elite_bar": "same as elite_smb: splits>0, n_test>=30, 2025>=0, win>=65%, test>=3%",
        "n_elite": len(elite),
        "books": books,
    }
    out = ROOT / "reports" / "backtest" / "contender_edges.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out} elite={len(elite)}")
    for b in books:
        print(
            b["name"],
            "n",
            b["n"],
            "te",
            b["test_roc_risk"],
            "2025",
            (b.get("yearly_roc_risk") or {}).get("2025"),
            "win",
            b["win_pct"],
            "elite",
            b["elite"],
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
