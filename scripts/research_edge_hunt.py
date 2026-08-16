#!/usr/bin/env python3
"""Long-sample edge hunt on Robinhood daily SPY (modeled BS-lite options).

Does **not** flip LIVE_ENTRIES / LIVE_EXITS. Pricing is always modeled_bs_lite.
A cell is a research survivor only if train, validation, and test means are
all > 0 and n_test >= 20. Never claims historical XSP fills.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xsp_killer.backtest.option_model import bs_call  # noqa: E402
from xsp_killer.paper_economics import (  # noqa: E402
    PaperEconomics,
    entry_fill_premium,
    exit_fill_premium,
)

STRIKE_STEP = 5.0
R = 0.05
IV = 0.18
DTE = 30
TP = 0.30
SL = 0.20


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_put(spot: float, strike: float, t_years: float, iv: float, r: float = R) -> float:
    """Put via put-call parity on the same BS call."""
    call = bs_call(spot, strike, t_years, iv, r=r)
    if t_years <= 1e-8:
        return max(0.0, strike - spot)
    return max(0.0, call - spot + strike * math.exp(-r * t_years))


def _atm(spot: float) -> float:
    return round(float(spot) / STRIKE_STEP) * STRIKE_STEP


def _t(dte: int) -> float:
    return max(0, int(dte)) / 365.0


def _leg(kind: str, spot: float, strike: float, dte: int, iv: float) -> float:
    t = _t(dte)
    if kind == "call":
        return max(0.05, bs_call(spot, strike, t, iv, r=R))
    return max(0.05, bs_put(spot, strike, t, iv, r=R))


def _spread_value(
    kind: str,
    spot: float,
    long_k: float,
    short_k: float,
    width: float,
    dte: int,
    iv: float,
) -> float:
    raw = _leg(kind, spot, long_k, dte, iv) - _leg(kind, spot, short_k, dte, iv)
    return min(max(raw, 0.0), width)


def load_rh_daily(path: Path) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bars = payload["data"]["results"][0]["bars"]
    rows: list[dict[str, Any]] = []
    for bar in bars:
        if bar.get("interpolated"):
            continue
        dt = datetime.fromisoformat(bar["begins_at"].replace("Z", "+00:00")).date()
        rows.append(
            {
                "date": dt,
                "open": float(bar["open_price"]),
                "high": float(bar["high_price"]),
                "low": float(bar["low_price"]),
                "close": float(bar["close_price"]),
                "volume": float(bar["volume"]),
            }
        )
    df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
    df = df.reset_index(drop=True)
    df["ret"] = df["close"].pct_change()
    df["weekday"] = df["date"].map(lambda d: d.weekday())
    lookback = 63
    vol_pctile: list[float | None] = [None] * len(df)
    for i in range(len(df)):
        prior = i - 1
        start = prior - lookback + 1
        if prior < 0 or start < 0:
            continue
        window = df["volume"].iloc[start : prior + 1]
        vol_pctile[i] = float((window <= df["volume"].iloc[prior]).mean())
    df["yest_vol_pctile"] = vol_pctile
    df["yest_ret"] = df["ret"].shift(1)
    return df


def _split_bounds(n: int) -> tuple[int, int]:
    train_end = int(n * 0.60)
    val_end = int(n * 0.80)
    return train_end, val_end


def _bucket(idx: int, train_end: int, val_end: int) -> str:
    if idx < train_end:
        return "train"
    if idx < val_end:
        return "val"
    return "test"


def _friday_exit_index(df: pd.DataFrame, entry_i: int, hold: int) -> int:
    """Last index in [entry_i+1, entry_i+hold] , flattening on Friday if seen."""
    last = min(entry_i + hold, len(df) - 1)
    for j in range(entry_i + 1, last + 1):
        if int(df.iloc[j]["weekday"]) == 4:
            return j
    return last


def _mark(
    geo: str,
    spot: float,
    *,
    long_k: float,
    short_k: float | None,
    width: float,
    dte: int,
    iv: float,
) -> float:
    if geo == "spy":
        return spot
    if geo.startswith("naked_call"):
        return _leg("call", spot, long_k, dte, iv)
    if geo.startswith("naked_put"):
        return _leg("put", spot, long_k, dte, iv)
    if geo.startswith("call_debit"):
        return _spread_value("call", spot, long_k, short_k or long_k, width, dte, iv)
    if geo.startswith("put_debit"):
        return _spread_value("put", spot, long_k, short_k or long_k, width, dte, iv)
    raise ValueError(geo)


def _net_pct(entry_mid: float, exit_mid: float, econ: PaperEconomics) -> float:
    fill = entry_fill_premium(entry_mid, econ)
    if fill <= 0:
        return 0.0
    px = exit_fill_premium(exit_mid, econ)
    return (px - fill) / fill


def _passes_filter(row: pd.Series, filt: str) -> bool:
    yest = row["yest_ret"]
    vp = row["yest_vol_pctile"]
    wd = int(row["weekday"])
    if pd.isna(yest):
        return False
    if filt == "all":
        return True
    if filt == "after_down_0.5":
        return float(yest) <= -0.005
    if filt == "after_down_1.0":
        return float(yest) <= -0.01
    if filt == "after_up_0.5":
        return float(yest) >= 0.005
    if filt == "quiet_q33":
        return vp is not None and not pd.isna(vp) and float(vp) <= 0.33
    if filt == "hot_q67":
        return vp is not None and not pd.isna(vp) and float(vp) >= 0.67
    if filt == "down_quiet":
        return (
            float(yest) <= -0.005
            and vp is not None
            and not pd.isna(vp)
            and float(vp) <= 0.33
        )
    if filt.startswith("wd_"):
        return wd == int(filt.split("_")[1])
    return False


def run_cell(
    df: pd.DataFrame,
    *,
    geo: str,
    filt: str,
    hold: int,
    width_strikes: int,
    overnight: bool,
    use_stops: bool,
    friday_flatten: bool,
    iv: float,
    econ: PaperEconomics,
) -> dict[str, Any]:
    n = len(df)
    train_end, val_end = _split_bounds(n)
    width = float(width_strikes) * STRIKE_STEP
    pnls: dict[str, list[float]] = {"train": [], "val": [], "test": []}
    holds: list[int] = []

    for i in range(2, n - 1):
        row = df.iloc[i]
        if friday_flatten and int(row["weekday"]) == 4:
            continue
        if not _passes_filter(row, filt):
            continue

        spot = float(row["close"])
        long_k = _atm(spot)
        if geo.startswith("put_debit"):
            short_k = long_k - width
        elif geo.startswith("call_debit"):
            short_k = long_k + width
        else:
            short_k = None

        if overnight:
            j = i + 1
            entry_spot = spot
            exit_spot = float(df.iloc[j]["open"])
            dte_e = DTE
            dte_x = max(0, DTE - (df.iloc[j]["date"] - row["date"]).days)
            if geo == "spy":
                raw = (exit_spot - entry_spot) / entry_spot
                # 2 bp round-trip friction on the underlying proxy
                net = raw - 0.0002
            else:
                em = _mark(
                    geo,
                    entry_spot,
                    long_k=long_k,
                    short_k=short_k,
                    width=width,
                    dte=dte_e,
                    iv=iv,
                )
                xm = _mark(
                    geo,
                    exit_spot,
                    long_k=long_k,
                    short_k=short_k,
                    width=width,
                    dte=dte_x,
                    iv=iv,
                )
                net = _net_pct(em, xm, econ)
            pnls[_bucket(i, train_end, val_end)].append(net)
            holds.append(1)
            continue

        if geo == "spy":
            j = _friday_exit_index(df, i, hold) if friday_flatten else min(i + hold, n - 1)
            if j <= i:
                continue
            raw = (float(df.iloc[j]["close"]) - spot) / spot
            net = raw - 0.0002
            pnls[_bucket(i, train_end, val_end)].append(net)
            holds.append(j - i)
            continue

        entry_mid = _mark(
            geo,
            spot,
            long_k=long_k,
            short_k=short_k,
            width=width,
            dte=DTE,
            iv=iv,
        )
        if entry_mid <= 0:
            continue
        last = _friday_exit_index(df, i, hold) if friday_flatten else min(i + hold, n - 1)
        exit_mid = entry_mid
        exit_j = last
        for j in range(i + 1, last + 1):
            dte_x = max(0, DTE - (df.iloc[j]["date"] - row["date"]).days)
            mark = _mark(
                geo,
                float(df.iloc[j]["close"]),
                long_k=long_k,
                short_k=short_k,
                width=width,
                dte=dte_x,
                iv=iv,
            )
            ret = (mark - entry_mid) / entry_mid
            if use_stops and ret >= TP:
                exit_mid = mark
                exit_j = j
                break
            if use_stops and ret <= -SL:
                exit_mid = mark
                exit_j = j
                break
            exit_mid = mark
            exit_j = j
        net = _net_pct(entry_mid, exit_mid, econ)
        pnls[_bucket(i, train_end, val_end)].append(net)
        holds.append(exit_j - i)

    def _mean(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 6) if xs else None

    full = pnls["train"] + pnls["val"] + pnls["test"]
    n_full = len(full)
    n_test = len(pnls["test"])
    train_m = _mean(pnls["train"])
    val_m = _mean(pnls["val"])
    test_m = _mean(pnls["test"])
    full_m = _mean(full)
    survivor = bool(
        n_test >= 20
        and train_m is not None
        and val_m is not None
        and test_m is not None
        and train_m > 0
        and val_m > 0
        and test_m > 0
        and full_m is not None
        and full_m > 0
    )
    return {
        "geo": geo,
        "filter": filt,
        "hold": hold,
        "width_strikes": width_strikes,
        "overnight": overnight,
        "use_stops": use_stops,
        "friday_flatten": friday_flatten,
        "n": n_full,
        "n_train": len(pnls["train"]),
        "n_val": len(pnls["val"]),
        "n_test": n_test,
        "mean": full_m,
        "train_mean": train_m,
        "val_mean": val_m,
        "test_mean": test_m,
        "win_pct": round(100.0 * sum(1 for x in full if x > 0) / n_full, 2)
        if n_full
        else None,
        "median_hold": float(pd.Series(holds).median()) if holds else None,
        "survivor": survivor,
        "pricing_fidelity": "modeled_bs_lite" if geo != "spy" else "underlying_spy",
    }


def build_grid() -> list[dict[str, Any]]:
    geos = [
        ("spy", 0),
        ("naked_call", 0),
        ("naked_put", 0),
        ("call_debit_w1", 1),
        ("call_debit_w2", 2),
        ("call_debit_w3", 3),
        ("put_debit_w1", 1),
        ("put_debit_w2", 2),
        ("put_debit_w3", 3),
    ]
    filts = [
        "all",
        "after_down_0.5",
        "after_down_1.0",
        "after_up_0.5",
        "quiet_q33",
        "hot_q67",
        "down_quiet",
        "wd_0",
        "wd_1",
        "wd_2",
        "wd_3",
    ]
    cells: list[dict[str, Any]] = []
    for geo, width in geos:
        for filt in filts:
            for hold in (1, 3, 5):
                cells.append(
                    {
                        "geo": geo,
                        "filt": filt,
                        "hold": hold,
                        "width": width,
                        "overnight": False,
                        "use_stops": geo != "spy",
                        "friday_flatten": True,
                    }
                )
        # Overnight close→next open, no weekday-4 skip on the *exit*.
        cells.append(
            {
                "geo": geo,
                "filt": "all",
                "hold": 1,
                "width": width,
                "overnight": True,
                "use_stops": False,
                "friday_flatten": True,
            }
        )
        cells.append(
            {
                "geo": geo,
                "filt": "after_down_0.5",
                "hold": 1,
                "width": width,
                "overnight": True,
                "use_stops": False,
                "friday_flatten": True,
            }
        )
    return cells


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="RH daily edge hunt (research only)")
    p.add_argument("--bars", type=Path, required=True, help="RH get_equity_historicals JSON")
    p.add_argument("--out", type=Path, default=ROOT / "reports" / "backtest")
    args = p.parse_args(argv)

    df = load_rh_daily(args.bars)
    econ = PaperEconomics.from_yaml()
    cells = build_grid()
    rows = [
        run_cell(
            df,
            geo=c["geo"],
            filt=c["filt"],
            hold=c["hold"],
            width_strikes=c["width"],
            overnight=c["overnight"],
            use_stops=c["use_stops"],
            friday_flatten=c["friday_flatten"],
            iv=IV,
            econ=econ,
        )
        for c in cells
    ]
    survivors = [r for r in rows if r["survivor"]]
    survivors.sort(key=lambda r: (r["test_mean"] or -9), reverse=True)
    ranked = sorted(
        [r for r in rows if r["mean"] is not None],
        key=lambda r: r["mean"],
        reverse=True,
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "edge_hunt_daily",
        "pricing_fidelity": "modeled_bs_lite",
        "disclaimer": (
            "Robinhood split-adjusted SPY daily. Option P&L is constant-IV "
            "BS-lite, not historical XSP fills. LIVE gates untouched. "
            "Survivor = train>0 and val>0 and test>0 and n_test>=20."
        ),
        "coverage": {
            "n_bars": int(len(df)),
            "start": str(df.iloc[0]["date"]),
            "end": str(df.iloc[-1]["date"]),
            "source": "robinhood_equity_historicals",
            "interval": "day",
        },
        "n_cells": len(rows),
        "n_survivors": len(survivors),
        "survivors": survivors[:40],
        "top_full_mean": ranked[:15],
        "bottom_full_mean": list(reversed(ranked[-8:])),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = args.out / f"edge_hunt_{stamp}.json"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Edge hunt (RH daily SPY)",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- bars: {payload['coverage']['start']} → {payload['coverage']['end']} n={payload['coverage']['n_bars']}",
        f"- cells: {payload['n_cells']}  survivors: {payload['n_survivors']}",
        f"- pricing: modeled_bs_lite (IV={IV}, DTE={DTE}, TP={TP}, SL={SL})",
        f"- survivor rule: train>0 AND val>0 AND test>0 AND n_test>=20",
        "",
        "## Survivors (by test mean)",
        "",
        "| geo | filter | hold | on | n | train% | val% | test% | full% | win% |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    show = survivors[:25] if survivors else ranked[:10]
    if not survivors:
        lines.append("| *(none — showing top full-sample means, not survivors)* | | | | | | | | | |")
    for r in show:
        lines.append(
            f"| `{r['geo']}` | {r['filter']} | {r['hold']} | "
            f"{'ovn' if r['overnight'] else 'eod'} | {r['n']} | "
            f"{_pct(r['train_mean'])} | {_pct(r['val_mean'])} | "
            f"{_pct(r['test_mean'])} | {_pct(r['mean'])} | {r['win_pct']} |"
        )
    out_md = args.out / f"edge_hunt_{stamp}.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    print(f"survivors: {len(survivors)} / {len(rows)}")
    if survivors:
        top = survivors[0]
        print(
            f"best_test: {top['geo']} {top['filter']} hold={top['hold']} "
            f"test={top['test_mean']} n_test={top['n_test']}"
        )
    return 0


def _pct(x: float | None) -> str:
    if x is None:
        return ""
    return f"{x * 100:.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
