#!/usr/bin/env python3
"""Follow-up hunt: realized-vol marking, DTE sweep, short-vol / credit.

Uses the same RH daily SPY tape and the same train/val/test (60/20/20)
survivor rule as research_edge_hunt.py. LIVE gates untouched.
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
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from research_edge_hunt import (  # noqa: E402
    IV,
    STRIKE_STEP,
    _atm,
    _bucket,
    _friday_exit_index,
    _leg,
    _net_pct,
    _passes_filter,
    _split_bounds,
    _spread_value,
    load_rh_daily,
)
from xsp_killer.paper_economics import PaperEconomics  # noqa: E402


def _ann_vol(df: pd.DataFrame, i: int, lookback: int = 20) -> float | None:
    if i < lookback:
        return None
    rets = df["ret"].iloc[i - lookback + 1 : i + 1]
    if rets.isna().any():
        return None
    return float(rets.std(ddof=1) * math.sqrt(252))


def _fwd_vol(df: pd.DataFrame, i: int, hold: int) -> float | None:
    j = min(i + hold, len(df) - 1)
    if j <= i + 1:
        return None
    rets = df["ret"].iloc[i + 1 : j + 1]
    if rets.isna().any() or len(rets) < 2:
        return None
    return float(rets.std(ddof=1) * math.sqrt(252))


def realized_vol_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    n = len(df)
    train_end, val_end = _split_bounds(n)
    rows: list[dict[str, Any]] = []
    for filt in ("all", "quiet_q33", "hot_q67", "after_down_0.5", "wd_0", "wd_1"):
        for hold in (3, 5):
            buckets = {"train": [], "val": [], "test": []}
            for i in range(25, n - hold - 1):
                row = df.iloc[i]
                if int(row["weekday"]) == 4:
                    continue
                if not _passes_filter(row, filt):
                    continue
                rv20 = _ann_vol(df, i - 1)
                fv = _fwd_vol(df, i, hold)
                if rv20 is None or fv is None:
                    continue
                expected = float(row["close"]) * IV * math.sqrt(hold / 365.0)
                realized = abs(float(df.iloc[i + hold]["close"]) - float(row["close"]))
                buckets[_bucket(i, train_end, val_end)].append(
                    {
                        "rv20": rv20,
                        "fwd": fv,
                        "edge_vs_18": IV - fv,
                        "edge_vs_rv20": rv20 - fv,
                        "move_edge": expected - realized,
                    }
                )

            def _m(xs: list[dict[str, Any]], key: str) -> float | None:
                return round(sum(x[key] for x in xs) / len(xs), 6) if xs else None

            full = buckets["train"] + buckets["val"] + buckets["test"]
            test = buckets["test"]
            train = buckets["train"]
            val = buckets["val"]
            survivor = bool(
                len(test) >= 20
                and _m(train, "edge_vs_18")
                and _m(val, "edge_vs_18")
                and _m(test, "edge_vs_18")
                and _m(train, "edge_vs_18") > 0
                and _m(val, "edge_vs_18") > 0
                and _m(test, "edge_vs_18") > 0
            )
            rows.append(
                {
                    "kind": "vol_premium",
                    "filter": filt,
                    "hold": hold,
                    "n": len(full),
                    "n_test": len(test),
                    "train_iv18_minus_fwd": _m(train, "edge_vs_18"),
                    "val_iv18_minus_fwd": _m(val, "edge_vs_18"),
                    "test_iv18_minus_fwd": _m(test, "edge_vs_18"),
                    "full_iv18_minus_fwd": _m(full, "edge_vs_18"),
                    "full_rv20_minus_fwd": _m(full, "edge_vs_rv20"),
                    "pct_fwd_below_18": round(
                        100.0 * sum(1 for x in full if x["fwd"] < IV) / len(full), 2
                    )
                    if full
                    else None,
                    "survivor_short_18iv": survivor,
                }
            )
    return rows


def run_option_cell(
    df: pd.DataFrame,
    *,
    geo: str,
    filt: str,
    hold: int,
    width_strikes: int,
    dte: int,
    iv_mode: str,
    use_stops: bool,
    econ: PaperEconomics,
) -> dict[str, Any]:
    n = len(df)
    train_end, val_end = _split_bounds(n)
    width = float(width_strikes) * STRIKE_STEP
    pnls: dict[str, list[float]] = {"train": [], "val": [], "test": []}
    tp, sl = 0.30, 0.20

    for i in range(25, n - 1):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        if not _passes_filter(row, filt):
            continue
        rv = _ann_vol(df, i - 1)
        if iv_mode == "rv20":
            if rv is None:
                continue
            iv_e = min(max(rv, 0.08), 0.80)
        else:
            iv_e = IV
        spot = float(row["close"])
        long_k = _atm(spot)
        if geo.startswith("put_debit") or geo.startswith("put_credit"):
            short_k = long_k - width
        elif geo.startswith("call_debit") or geo.startswith("call_credit"):
            short_k = long_k + width
        else:
            short_k = None

        def mark(s: float, dte_left: int, iv: float) -> float:
            if geo.startswith("naked_call"):
                return _leg("call", s, long_k, dte_left, iv)
            if geo.startswith("naked_put"):
                return _leg("put", s, long_k, dte_left, iv)
            if geo.startswith("call_debit"):
                return _spread_value("call", s, long_k, short_k or long_k, width, dte_left, iv)
            if geo.startswith("put_debit"):
                return _spread_value("put", s, long_k, short_k or long_k, width, dte_left, iv)
            if geo.startswith("call_credit"):
                return _spread_value("call", s, long_k, short_k or long_k, width, dte_left, iv)
            if geo.startswith("put_credit"):
                return _spread_value("put", s, long_k, short_k or long_k, width, dte_left, iv)
            raise ValueError(geo)

        last = _friday_exit_index(df, i, hold)
        entry_mid = mark(spot, dte, iv_e)
        if entry_mid <= 0:
            continue
        exit_mid = entry_mid
        for j in range(i + 1, last + 1):
            dte_x = max(0, dte - (df.iloc[j]["date"] - row["date"]).days)
            if iv_mode == "rv20":
                rv_j = _ann_vol(df, j - 1) or iv_e
                iv_x = min(max(rv_j, 0.08), 0.80)
            else:
                iv_x = iv_e
            m = mark(float(df.iloc[j]["close"]), dte_x, iv_x)
            ret = (m - entry_mid) / entry_mid
            if use_stops and ret >= tp:
                exit_mid = m
                break
            if use_stops and ret <= -sl:
                exit_mid = m
                break
            exit_mid = m
        debit_like = _net_pct(entry_mid, exit_mid, econ)
        if geo.endswith("credit") or geo.startswith("call_credit") or geo.startswith(
            "put_credit"
        ):
            net = -debit_like
        else:
            net = debit_like
        pnls[_bucket(i, train_end, val_end)].append(net)

    def _mean(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 6) if xs else None

    full = pnls["train"] + pnls["val"] + pnls["test"]
    train_m, val_m, test_m, full_m = (
        _mean(pnls["train"]),
        _mean(pnls["val"]),
        _mean(pnls["test"]),
        _mean(full),
    )
    n_test = len(pnls["test"])
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
        "dte": dte,
        "width_strikes": width_strikes,
        "iv_mode": iv_mode,
        "use_stops": use_stops,
        "n": len(full),
        "n_test": n_test,
        "mean": full_m,
        "train_mean": train_m,
        "val_mean": val_m,
        "test_mean": test_m,
        "win_pct": round(100.0 * sum(1 for x in full if x > 0) / len(full), 2)
        if full
        else None,
        "survivor": survivor,
        "pricing_fidelity": f"modeled_bs_{iv_mode}",
    }


def build_option_grid() -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    geos = [
        ("call_debit_w3", 3),
        ("call_credit_w3", 3),
        ("put_credit_w3", 3),
        ("naked_call", 0),
    ]
    for geo, width in geos:
        for filt in ("quiet_q33", "wd_0", "wd_1", "all"):
            for hold in (3, 5):
                for dte in (14, 30, 80):
                    for iv_mode in ("const18", "rv20"):
                        for stops in (False, True):
                            if geo == "naked_call" and iv_mode == "const18" and dte == 30:
                                # already swept in the first hunt
                                if filt in ("quiet_q33", "wd_0", "wd_1", "all") and stops:
                                    continue
                            cells.append(
                                {
                                    "geo": geo,
                                    "filt": filt,
                                    "hold": hold,
                                    "width": width,
                                    "dte": dte,
                                    "iv_mode": iv_mode,
                                    "stops": stops,
                                }
                            )
    return cells


def hourly_windows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    bars = payload["data"]["results"][0]["bars"]
    rows = []
    for bar in bars:
        if bar.get("interpolated"):
            continue
        ts = datetime.fromisoformat(bar["begins_at"].replace("Z", "+00:00"))
        et = ts.astimezone(tz=datetime.now().astimezone().tzinfo)
        # Convert properly via zoneinfo
        from zoneinfo import ZoneInfo

        et = ts.astimezone(ZoneInfo("America/New_York"))
        rows.append(
            {
                "date": et.date(),
                "hour": et.hour,
                "minute": et.minute,
                "close": float(bar["close_price"]),
                "open": float(bar["open_price"]),
                "weekday": et.weekday(),
            }
        )
    hdf = pd.DataFrame(rows)
    days: dict[Any, dict[str, float]] = {}
    for rec in hdf.to_dict("records"):
        d = rec["date"]
        slot = days.setdefault(d, {"weekday": rec["weekday"]})
        if rec["hour"] == 10 and rec["minute"] == 0:
            slot["am"] = rec["close"]
        if rec["hour"] == 15 and rec["minute"] == 0:
            slot["close"] = rec["close"]
        if rec["hour"] == 9 and rec["minute"] == 30:
            slot["open"] = rec["open"]
    ordered = sorted(days.items())
    # fallback: first/last bar of day
    by_date = hdf.groupby("date")
    for d, slot in days.items():
        g = by_date.get_group(d)
        if "am" not in slot:
            am = g[(g["hour"] >= 10) & (g["hour"] <= 11)]
            if not am.empty:
                slot["am"] = float(am.iloc[0]["close"])
        if "close" not in slot:
            slot["close"] = float(g.iloc[-1]["close"])
        if "open" not in slot:
            slot["open"] = float(g.iloc[0]["open"])

    def _stats(vals: list[float]) -> dict[str, Any]:
        if not vals:
            return {"n": 0, "mean": None, "win_pct": None}
        return {
            "n": len(vals),
            "mean": round(sum(vals) / len(vals), 6),
            "win_pct": round(100.0 * sum(1 for v in vals if v > 0) / len(vals), 2),
        }

    am_to_close: list[float] = []
    close_to_next_open: list[float] = []
    close_to_next_close: list[float] = []
    for i, (d, slot) in enumerate(ordered):
        if int(slot["weekday"]) == 4:
            continue
        if "am" in slot and "close" in slot:
            am_to_close.append((slot["close"] - slot["am"]) / slot["am"])
        if i + 1 < len(ordered):
            nxt = ordered[i + 1][1]
            if "close" in slot and "open" in nxt:
                close_to_next_open.append((nxt["open"] - slot["close"]) / slot["close"])
            if "close" in slot and "close" in nxt:
                close_to_next_close.append((nxt["close"] - slot["close"]) / slot["close"])
    return [
        {"window": "am_to_close_same_day", **_stats(am_to_close)},
        {"window": "close_to_next_open", **_stats(close_to_next_open)},
        {"window": "close_to_next_close", **_stats(close_to_next_close)},
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bars", type=Path, required=True)
    p.add_argument("--hourly", type=Path, default=None)
    p.add_argument("--out", type=Path, default=ROOT / "reports" / "backtest")
    args = p.parse_args(argv)

    df = load_rh_daily(args.bars)
    econ = PaperEconomics.from_yaml()
    vol_rows = realized_vol_table(df)
    opt_rows = [
        run_option_cell(
            df,
            geo=c["geo"],
            filt=c["filt"],
            hold=c["hold"],
            width_strikes=c["width"],
            dte=c["dte"],
            iv_mode=c["iv_mode"],
            use_stops=c["stops"],
            econ=econ,
        )
        for c in build_option_grid()
    ]
    survivors = [r for r in opt_rows if r["survivor"]]
    survivors.sort(key=lambda r: (r["test_mean"] or -9), reverse=True)
    vol_surv = [r for r in vol_rows if r["survivor_short_18iv"]]
    hourly = hourly_windows(args.hourly) if args.hourly and args.hourly.is_file() else []

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "edge_hunt_vol_dte",
        "disclaimer": (
            "Research only. Credit P&L is the negative of the debit mark. "
            "rv20 marking uses trailing 20d realized vol, not implied vol. "
            "Not historical XSP fills. LIVE gates untouched."
        ),
        "coverage": {
            "n_bars": int(len(df)),
            "start": str(df.iloc[0]["date"]),
            "end": str(df.iloc[-1]["date"]),
        },
        "n_option_cells": len(opt_rows),
        "n_option_survivors": len(survivors),
        "option_survivors": survivors[:30],
        "vol_survivors": vol_surv,
        "vol_rows": vol_rows,
        "hourly_windows": hourly,
        "top_option": sorted(
            [r for r in opt_rows if r["mean"] is not None],
            key=lambda r: r["mean"],
            reverse=True,
        )[:12],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = args.out / f"edge_hunt_vol_dte_{stamp}.json"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def pct(x: float | None) -> str:
        return "" if x is None else f"{x * 100:.2f}"

    lines = [
        "# Edge hunt follow-up (vol premium + DTE + credit)",
        "",
        f"- bars: {payload['coverage']['start']} → {payload['coverage']['end']} n={payload['coverage']['n_bars']}",
        f"- option cells: {payload['n_option_cells']}  survivors: {payload['n_option_survivors']}",
        f"- short-18iv vol survivors: {len(vol_surv)}",
        "",
        "## Option survivors (train/val/test > 0, n_test>=20)",
        "",
        "| geo | filter | dte | hold | iv | stops | n | train% | val% | test% | full% |",
        "|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in survivors[:20] or payload["top_option"][:8]:
        lines.append(
            f"| `{r['geo']}` | {r['filter']} | {r['dte']} | {r['hold']} | "
            f"{r['iv_mode']} | {r['use_stops']} | {r['n']} | "
            f"{pct(r['train_mean'])} | {pct(r['val_mean'])} | "
            f"{pct(r['test_mean'])} | {pct(r['mean'])} |"
        )
    lines += [
        "",
        "## Short-vol vs 18% IV (fwd realized − 18%)",
        "",
        "| filter | hold | n | train | val | test | full | %fwd<18 | survivor |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in vol_rows:
        lines.append(
            f"| {r['filter']} | {r['hold']} | {r['n']} | "
            f"{r['train_iv18_minus_fwd']} | {r['val_iv18_minus_fwd']} | "
            f"{r['test_iv18_minus_fwd']} | {r['full_iv18_minus_fwd']} | "
            f"{r['pct_fwd_below_18']} | {r['survivor_short_18iv']} |"
        )
    if hourly:
        lines += ["", "## Hourly SPY windows (1y, skip Friday entries)", ""]
        for r in hourly:
            lines.append(f"- {r['window']}: n={r['n']} mean={r['mean']} win%={r['win_pct']}")
    out_md = args.out / f"edge_hunt_vol_dte_{stamp}.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    print(f"option_survivors={len(survivors)} vol_survivors={len(vol_surv)}")
    if survivors:
        t = survivors[0]
        print(
            f"best {t['geo']} {t['filter']} dte={t['dte']} iv={t['iv_mode']} "
            f"test={t['test_mean']} n_test={t['n_test']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
