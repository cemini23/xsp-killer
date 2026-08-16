#!/usr/bin/env python3
"""Deeper XSP contenders outside Lane A and the papered 14 DTE book.

Pre-registered (not a grid): NFP-week skip, pullback-to-MA, reclaim,
high-RV skip, 7/21 calendar, put-debit below MA, credit put BWB.

Same elite bar as research_elite_smb.py. rv20 marks. LIVE untouched.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_edge_hunt import (  # noqa: E402
    STRIKE_STEP,
    _atm,
    _friday_exit_index,
    _leg,
    _net_pct,
    _spread_value,
    load_rh_daily,
)
from research_elite_smb import summarize  # noqa: E402
from research_vol_dte_hunt import _ann_vol  # noqa: E402
from xsp_killer.fomc_calendar import near_fomc  # noqa: E402
from xsp_killer.nfp_calendar import nfp_week  # noqa: E402
from xsp_killer.paper_economics import PaperEconomics  # noqa: E402


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 6) if xs else None


def _iv(df: pd.DataFrame, i: int) -> float | None:
    rv = _ann_vol(df, i - 1)
    if rv is None:
        return None
    return min(max(rv, 0.08), 0.80)


def _rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0.0).rolling(period).mean()
    loss = (-delta.clip(upper=0.0)).rolling(period).mean()
    rs = gain / loss.replace(0.0, pd.NA)
    return 100.0 - (100.0 / (1.0 + rs))


def _credit_exit(
    df: pd.DataFrame,
    i: int,
    *,
    kind: str,
    short_k: float,
    long_k: float,
    width: float,
    dte: int,
    iv: float,
    hold: int,
    dma_exit: bool,
    velocity: float,
) -> float:
    row = df.iloc[i]
    entry = _spread_value(kind, float(row["close"]), short_k, long_k, width, dte, iv)
    last = _friday_exit_index(df, i, hold)
    exit_mid = entry
    for j in range(i + 1, last + 1):
        dte_x = max(0, dte - (df.iloc[j]["date"] - row["date"]).days)
        iv_x = _iv(df, j) or iv
        mark = _spread_value(kind, float(df.iloc[j]["close"]), short_k, long_k, width, dte_x, iv_x)
        if entry > 0 and (entry - mark) / entry >= velocity:
            return mark
        if dma_exit and not bool(df.iloc[j]["above_ma20"]):
            return mark
        exit_mid = mark
    return exit_mid


def run_put_credit(
    df: pd.DataFrame,
    *,
    name: str,
    dte: int,
    width: float,
    econ: PaperEconomics,
    extra_ok: Callable[[pd.Series, int, pd.DataFrame], bool] | None = None,
    require_above: bool = True,
    require_reclaim: bool = False,
    skip_nfp_week: bool = False,
    skip_high_rv: float | None = None,
    low_rv_only: float | None = None,
    mon_tue_only: bool = False,
    hold: int = 5,
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    for i in range(25, len(df) - 1):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        if mon_tue_only and int(row["weekday"]) > 1:
            continue
        if near_fomc(row["date"], before=2, after=1):
            continue
        if skip_nfp_week and nfp_week(row["date"]):
            continue
        if require_above and not bool(row["above_ma20"]):
            continue
        if require_reclaim and not bool(row["reclaim_ma20"]):
            continue
        iv = _iv(df, i)
        if iv is None:
            continue
        if skip_high_rv is not None and iv > skip_high_rv:
            continue
        if low_rv_only is not None and iv > low_rv_only:
            continue
        if extra_ok is not None and not extra_ok(row, i, df):
            continue
        spot = float(row["close"])
        short_k = _atm(spot)
        long_k = short_k - width
        entry = _spread_value("put", spot, short_k, long_k, width, dte, iv)
        if entry <= 0 or entry >= width:
            continue
        exit_mid = _credit_exit(
            df,
            i,
            kind="put",
            short_k=short_k,
            long_k=long_k,
            width=width,
            dte=dte,
            iv=iv,
            hold=hold,
            dma_exit=True,
            velocity=0.76,
        )
        roc_credit = -_net_pct(entry, exit_mid, econ)
        max_risk = width - entry
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


def run_calendar(df: pd.DataFrame, econ: PaperEconomics) -> dict[str, Any]:
    """Short 7 DTE ATM put / long 21 DTE ATM put, above MA, FOMC skip."""
    trades: list[dict[str, Any]] = []
    for i in range(25, len(df) - 1):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        if near_fomc(row["date"], before=2, after=1):
            continue
        if not bool(row["above_ma20"]):
            continue
        iv = _iv(df, i)
        if iv is None:
            continue
        spot = float(row["close"])
        k = _atm(spot)
        front = _leg("put", spot, k, 7, iv)
        back = _leg("put", spot, k, 21, iv)
        net_debit = back - front
        if net_debit <= 0.05:
            continue
        last = _friday_exit_index(df, i, 5)
        exit_pnl = 0.0
        for j in range(i + 1, last + 1):
            dte_f = max(0, 7 - (df.iloc[j]["date"] - row["date"]).days)
            dte_b = max(0, 21 - (df.iloc[j]["date"] - row["date"]).days)
            iv_x = _iv(df, j) or iv
            s = float(df.iloc[j]["close"])
            front_x = _leg("put", s, k, dte_f, iv_x)
            back_x = _leg("put", s, k, dte_b, iv_x)
            # Short front, long back: +front decay, -back decay
            exit_pnl = (front - front_x) - (back - back_x)
            if not bool(df.iloc[j]["above_ma20"]):
                break
        roc = -_net_pct(net_debit, net_debit - exit_pnl, econ)
        trades.append(
            {
                "i": i,
                "year": row["date"].year,
                "roc_credit": roc,
                "roc_risk": roc,
                "pnl_usd": roc * net_debit * 100.0,
            }
        )
    out = summarize(trades, len(df))
    out["name"] = "calendar_put_7_21_above_ma"
    return out


def run_put_debit_below_ma(df: pd.DataFrame, econ: PaperEconomics) -> dict[str, Any]:
    """7 DTE ATM put debit only below the 20-DMA (crash twin)."""
    trades: list[dict[str, Any]] = []
    width = 5.0
    dte = 7
    for i in range(25, len(df) - 1):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        if near_fomc(row["date"], before=2, after=1):
            continue
        if bool(row["above_ma20"]):
            continue
        iv = _iv(df, i)
        if iv is None:
            continue
        spot = float(row["close"])
        long_k = _atm(spot)
        short_k = long_k - width
        entry = _spread_value("put", spot, long_k, short_k, width, dte, iv)
        if entry <= 0.05:
            continue
        last = _friday_exit_index(df, i, 5)
        exit_mid = entry
        for j in range(i + 1, last + 1):
            dte_x = max(0, dte - (df.iloc[j]["date"] - row["date"]).days)
            iv_x = _iv(df, j) or iv
            mark = _spread_value(
                "put", float(df.iloc[j]["close"]), long_k, short_k, width, dte_x, iv_x
            )
            if mark >= entry * 1.30:
                exit_mid = mark
                break
            if bool(df.iloc[j]["above_ma20"]):
                exit_mid = mark
                break
            exit_mid = mark
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
    out["name"] = "put_debit_7dte_below_ma"
    return out


def _bwb_value(spot: float, atm: float, dte: int, iv: float) -> float:
    """Credit put BWB: +1 ATM+5 / -2 ATM / +1 ATM-10. Negative = credit."""
    return (
        _leg("put", spot, atm + 5.0, dte, iv)
        - 2.0 * _leg("put", spot, atm, dte, iv)
        + _leg("put", spot, atm - 10.0, dte, iv)
    )


def run_bwb(df: pd.DataFrame, econ: PaperEconomics, *, rsi_trigger: bool) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    dte = 14
    # Far wing 10 wide, close wing 5 wide → defined risk 5 pts if credit.
    max_risk = 5.0
    for i in range(25, len(df) - 1):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        if near_fomc(row["date"], before=2, after=1):
            continue
        if rsi_trigger:
            rsi = row["rsi14"]
            if pd.isna(rsi) or float(rsi) > 30.0:
                continue
        elif not bool(row["above_ma20"]):
            continue
        iv = _iv(df, i)
        if iv is None:
            continue
        spot = float(row["close"])
        atm = _atm(spot)
        raw = _bwb_value(spot, atm, dte, iv)
        credit = -raw
        if credit <= 0.05:
            continue
        last = _friday_exit_index(df, i, 5)
        exit_val = raw
        for j in range(i + 1, last + 1):
            dte_x = max(0, dte - (df.iloc[j]["date"] - row["date"]).days)
            iv_x = _iv(df, j) or iv
            exit_val = _bwb_value(float(df.iloc[j]["close"]), atm, dte_x, iv_x)
            if credit > 0 and (credit - (-exit_val)) / credit >= 0.76:
                break
            if not rsi_trigger and not bool(df.iloc[j]["above_ma20"]):
                break
        exit_credit = -exit_val
        roc_credit = -_net_pct(credit, exit_credit, econ)
        pnl = roc_credit * credit
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
    out["name"] = "bwb_rsi30" if rsi_trigger else "bwb_put_credit_above_ma"
    return out


def _pullback(row: pd.Series, i: int, df: pd.DataFrame) -> bool:
    if i < 3:
        return False
    return float(df.iloc[i]["close"]) <= float(df.iloc[i - 3]["close"])


def _not_extended(row: pd.Series, i: int, df: pd.DataFrame) -> bool:
    ma = row["ma20"]
    if pd.isna(ma) or float(ma) <= 0:
        return False
    return (float(row["close"]) / float(ma) - 1.0) <= 0.015


def _no_crash_day(row: pd.Series, i: int, df: pd.DataFrame) -> bool:
    if i < 1:
        return False
    prev = df.iloc[i - 1]
    if pd.isna(prev["close"]) or float(prev["close"]) <= 0:
        return False
    # skip if yesterday dropped more than 1.5%
    return (float(row["close"]) / float(prev["close"]) - 1.0) > -0.015


def main() -> int:
    df = load_rh_daily(ROOT / ".local" / "research" / "spy_daily_10y.json")
    df["ma20"] = df["close"].rolling(20).mean()
    df["above_ma20"] = df["close"] > df["ma20"]
    prev_above = df["above_ma20"].shift(1)
    df["reclaim_ma20"] = df["above_ma20"] & (prev_above == False)
    df["rsi14"] = _rsi(df["close"])
    econ = PaperEconomics.from_yaml()

    books = [
        run_put_credit(df, name="pc_7dte_baseline", dte=7, width=5.0, econ=econ),
        run_put_credit(
            df, name="pc_7dte_nfp_week_skip", dte=7, width=5.0, econ=econ, skip_nfp_week=True
        ),
        run_put_credit(
            df, name="pc_7dte_skip_rv22", dte=7, width=5.0, econ=econ, skip_high_rv=0.22
        ),
        run_put_credit(
            df, name="pc_7dte_low_rv16", dte=7, width=5.0, econ=econ, low_rv_only=0.16
        ),
        run_put_credit(
            df, name="pc_7dte_no_crash_day", dte=7, width=5.0, econ=econ, extra_ok=_no_crash_day
        ),
        run_put_credit(
            df, name="pc_7dte_pullback", dte=7, width=5.0, econ=econ, extra_ok=_pullback
        ),
        run_put_credit(
            df, name="pc_7dte_not_extended", dte=7, width=5.0, econ=econ, extra_ok=_not_extended
        ),
        run_put_credit(
            df, name="pc_7dte_reclaim", dte=7, width=5.0, econ=econ, require_reclaim=True
        ),
        run_put_credit(
            df, name="pc_7dte_mon_tue", dte=7, width=5.0, econ=econ, mon_tue_only=True
        ),
        run_put_credit(
            df, name="pc_14dte_nfp_week_skip", dte=14, width=5.0, econ=econ, skip_nfp_week=True
        ),
        run_put_credit(
            df, name="pc_14dte_pullback", dte=14, width=5.0, econ=econ, extra_ok=_pullback
        ),
        run_put_credit(df, name="pc_7dte_10wide", dte=7, width=10.0, econ=econ),
        run_calendar(df, econ),
        run_put_debit_below_ma(df, econ),
        run_bwb(df, econ, rsi_trigger=False),
        run_bwb(df, econ, rsi_trigger=True),
    ]
    elite = [b for b in books if b.get("elite")]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "deep_xsp_contenders",
        "elite_bar": "splits>0, n_test>=30, 2025>=0, win>=65%, test ROC risk>=3%",
        "n_elite": len(elite),
        "books": books,
    }
    out = ROOT / "reports" / "backtest" / "deep_xsp_contenders.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out} elite={len(elite)}")
    ranked = sorted(books, key=lambda b: (b.get("test_roc_risk") or -9), reverse=True)
    for b in ranked:
        print(
            f"{b['name']:28} n={b['n']:4} te={b['test_roc_risk']} "
            f"2025={(b.get('yearly_roc_risk') or {}).get('2025')} "
            f"win={b['win_pct']} elite={b['elite']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
