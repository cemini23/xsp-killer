#!/usr/bin/env python3
"""Join TipDrop UW tide journal to overlapping PC entries (23-day window).

Not an elite 10y bar. GEX/TipSeeker history is too short to join.
LIVE untouched. rv20 marks.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_edge_hunt import load_rh_daily  # noqa: E402
from xsp_killer.paper_economics import PaperEconomics  # noqa: E402

JOURNAL = Path(r"C:\Users\Owner\institutional-shadow\data_store\uw_regime_shadow.jsonl")


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 6) if xs else None


def load_daily_bias(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    tide: dict[str, str] = {}
    spy_np: dict[str, str] = {}
    if not path.is_file():
        return tide, spy_np
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        d = row.get("et_date")
        if not d:
            continue
        if row.get("kind") == "market_tide" and row.get("bias"):
            tide[str(d)] = str(row["bias"])
        if (
            row.get("kind") == "net_prem"
            and row.get("ticker") == "SPY"
            and row.get("bias")
        ):
            spy_np[str(d)] = str(row["bias"])
    return tide, spy_np


def main() -> int:
    tide, spy_np = load_daily_bias(JOURNAL)
    days = sorted(tide)
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "overlay_skip_research",
        "window": {"first": days[0] if days else None, "last": days[-1] if days else None},
        "n_tide_days": len(days),
        "tide_counts": {
            "put": sum(1 for v in tide.values() if v == "put"),
            "call": sum(1 for v in tide.values() if v == "call"),
        },
        "pricing_fidelity": "modeled_bs_rv20",
        "elite": False,
        "note": "23-day journal only. Cannot promote a skip. GEX not joinable.",
    }
    if not days:
        out = ROOT / "reports" / "backtest" / "overlay_skips.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("no tide journal")
        return 0

    start = date.fromisoformat(days[0])
    end = date.fromisoformat(days[-1])
    df = load_rh_daily(ROOT / ".local" / "research" / "spy_daily_10y.json")
    df["ma20"] = df["close"].rolling(20).mean()
    df["above_ma20"] = df["close"] > df["ma20"]
    df["reclaim_ma20"] = False
    econ = PaperEconomics.from_yaml()

    # Restrict to journal window + a few hold days after.
    mask = (df["date"] >= start) & (df["date"] <= end)
    # Need lookback for MA/rv — keep prior 25 rows.
    idx = df.index[mask]
    if len(idx) == 0:
        print("no bars in window")
        return 1
    lo = max(0, int(idx.min()) - 25)
    hi = min(len(df), int(idx.max()) + 6)
    work = df.iloc[lo:hi].reset_index(drop=True)

    # Tag via a pass that keeps dates — same gates as research_deep_xsp.
    from research_deep_xsp import _credit_exit, _iv
    from research_edge_hunt import STRIKE_STEP, _atm, _net_pct, _spread_value
    from xsp_killer.fomc_calendar import near_fomc

    def collect(dte: int, mon_tue: bool) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        width = 5.0
        for i in range(25, len(work) - 1):
            row = work.iloc[i]
            d = row["date"]
            key = d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]
            if key < days[0] or key > days[-1]:
                continue
            if int(row["weekday"]) == 4:
                continue
            if mon_tue and int(row["weekday"]) > 1:
                continue
            if near_fomc(row["date"], before=2, after=1):
                continue
            if not bool(row["above_ma20"]):
                continue
            iv = _iv(work, i)
            if iv is None:
                continue
            spot = float(row["close"])
            short_k = _atm(spot)
            long_k = short_k - width
            entry = _spread_value("put", spot, short_k, long_k, width, dte, iv)
            if entry <= 0 or entry >= width:
                continue
            exit_mid = _credit_exit(
                work,
                i,
                kind="put",
                short_k=short_k,
                long_k=long_k,
                width=width,
                dte=dte,
                iv=iv,
                hold=5,
                dma_exit=True,
                velocity=0.76,
            )
            roc_credit = -_net_pct(entry, exit_mid, econ)
            max_risk = width - entry
            pnl = roc_credit * entry
            roc_risk = pnl / max_risk if max_risk > 0 else 0.0
            rows.append(
                {
                    "date": key,
                    "roc_risk": roc_risk,
                    "pnl_usd": pnl * 100.0,
                    "tide": tide.get(key),
                    "spy_np": spy_np.get(key),
                }
            )
        return rows

    tagged = {
        "pc_14dte": collect(14, False),
        "pc_7dte_mon_tue": collect(7, True),
    }

    def split(rows: list[dict[str, Any]], field: str, val: str) -> list[float]:
        return [r["roc_risk"] for r in rows if r.get(field) == val]

    results = {}
    for name, rows in tagged.items():
        put = split(rows, "tide", "put")
        call = split(rows, "tide", "call")
        kept = [r["roc_risk"] for r in rows if r.get("tide") != "put"]
        results[name] = {
            "n": len(rows),
            "all_roc": _mean([r["roc_risk"] for r in rows]),
            "put_tide_n": len(put),
            "put_tide_roc": _mean(put),
            "call_tide_n": len(call),
            "call_tide_roc": _mean(call),
            "skip_put_tide_n": len(kept),
            "skip_put_tide_roc": _mean(kept),
            "win_pct": round(100.0 * sum(1 for r in rows if r["roc_risk"] > 0) / len(rows), 2)
            if rows
            else None,
        }
    payload["books"] = results
    out = ROOT / "reports" / "backtest" / "overlay_skips.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
