#!/usr/bin/env python3
"""Verify honest (rv20) survivors and crisis-year stability. Research only."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_edge_hunt import load_rh_daily  # noqa: E402
from research_vol_dte_hunt import run_option_cell  # noqa: E402
from xsp_killer.paper_economics import PaperEconomics  # noqa: E402


def main() -> int:
    df = load_rh_daily(ROOT / ".local" / "research" / "spy_daily_10y.json")
    econ = PaperEconomics.from_yaml()
    geos = [
        ("put_credit_w3", 3),
        ("call_credit_w3", 3),
        ("call_debit_w3", 3),
        ("naked_call", 0),
        ("put_debit_w3", 3),
    ]
    rows = []
    for geo, width in geos:
        for filt in ("quiet_q33", "wd_0", "wd_1", "all"):
            for hold in (3, 5):
                for dte in (14, 30, 80):
                    for stops in (False, True):
                        rows.append(
                            run_option_cell(
                                df,
                                geo=geo,
                                filt=filt,
                                hold=hold,
                                width_strikes=width,
                                dte=dte,
                                iv_mode="rv20",
                                use_stops=stops,
                                econ=econ,
                            )
                        )
    surv = [r for r in rows if r["survivor"]]
    print("rv20_cells", len(rows), "survivors", len(surv))
    print("by_geo", Counter(r["geo"] for r in surv))
    print("long_survivors", sum(1 for r in surv if "debit" in r["geo"] or r["geo"].startswith("naked")))
    print("--- top rv20 ---")
    for r in sorted(surv, key=lambda x: x["test_mean"] or -9, reverse=True)[:15]:
        print(
            r["geo"],
            r["filter"],
            "dte",
            r["dte"],
            "h",
            r["hold"],
            "stops",
            r["use_stops"],
            "n",
            r["n"],
            "tr",
            r["train_mean"],
            "va",
            r["val_mean"],
            "te",
            r["test_mean"],
        )

    # Crisis-year path for the lead cell (no split; year buckets).
    lead = run_option_cell(
        df,
        geo="put_credit_w3",
        filt="quiet_q33",
        hold=5,
        width_strikes=3,
        dte=14,
        iv_mode="rv20",
        use_stops=True,
        econ=econ,
    )
    print("lead_full", lead)

    # Yearly means via a light replay of dates.
    from research_edge_hunt import (  # noqa: E402
        IV,
        STRIKE_STEP,
        _atm,
        _friday_exit_index,
        _leg,
        _net_pct,
        _passes_filter,
        _spread_value,
    )
    from research_vol_dte_hunt import _ann_vol  # noqa: E402

    width = 15.0
    yearly: dict[int, list[float]] = {}
    for i in range(25, len(df) - 1):
        row = df.iloc[i]
        if int(row["weekday"]) == 4:
            continue
        if not _passes_filter(row, "quiet_q33"):
            continue
        rv = _ann_vol(df, i - 1)
        if rv is None:
            continue
        iv_e = min(max(rv, 0.08), 0.80)
        spot = float(row["close"])
        long_k = _atm(spot)
        short_k = long_k - width
        last = _friday_exit_index(df, i, 5)

        def mark(s: float, dte_left: int, iv: float) -> float:
            return _spread_value("put", s, long_k, short_k, width, dte_left, iv)

        entry_mid = mark(spot, 14, iv_e)
        if entry_mid <= 0:
            continue
        exit_mid = entry_mid
        for j in range(i + 1, last + 1):
            dte_x = max(0, 14 - (df.iloc[j]["date"] - row["date"]).days)
            rv_j = _ann_vol(df, j - 1) or iv_e
            iv_x = min(max(rv_j, 0.08), 0.80)
            m = mark(float(df.iloc[j]["close"]), dte_x, iv_x)
            ret = (m - entry_mid) / entry_mid
            if ret >= 0.30 or ret <= -0.20:
                exit_mid = m
                break
            exit_mid = m
        net = -_net_pct(entry_mid, exit_mid, econ)
        yearly.setdefault(row["date"].year, []).append(net)
    print("--- yearly put_credit quiet 14dte h5 rv20 ---")
    for year in sorted(yearly):
        xs = yearly[year]
        print(
            year,
            "n",
            len(xs),
            "mean",
            round(sum(xs) / len(xs), 4),
            "win",
            round(100 * sum(1 for x in xs if x > 0) / len(xs), 1),
        )
    out = ROOT / "reports" / "backtest" / "edge_hunt_rv20_verify.json"
    out.write_text(
        json.dumps(
            {
                "rv20_survivors": surv,
                "by_geo": dict(Counter(r["geo"] for r in surv)),
                "yearly_lead": {
                    str(y): {
                        "n": len(xs),
                        "mean": round(sum(xs) / len(xs), 6),
                        "win_pct": round(100 * sum(1 for x in xs if x > 0) / len(xs), 2),
                    }
                    for y, xs in sorted(yearly.items())
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
