"""Isolated paper sleeve for the SMB 20-DMA put-credit book.

Log-only. Never places multi-leg live. Does not share Lane A paper state.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from xsp_killer.backtest.option_model import bs_call
from xsp_killer.fomc_calendar import near_fomc
from xsp_killer.paper_economics import (
    PaperEconomics,
    entry_fill_premium,
    exit_fill_premium,
)
from xsp_killer.put_credit import (
    build_put_credit,
    put_credit_return_on_risk,
    put_credit_value,
    select_long_put_strike,
    velocity_captured,
)

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = ROOT / "config" / "lane_pc_rules.yaml"
DEFAULT_STATE = ROOT / "briefs" / "lane-pc-state.json"
DEFAULT_LOG = ROOT / "logs" / "lane_pc_paper.jsonl"
DEFAULT_SCOREBOARD = ROOT / "briefs" / "lane-pc-scoreboard.json"
STRIKE_STEP = 5.0
R = 0.05


@dataclass
class PcRules:
    window_start: time = time(15, 45)
    window_end: time = time(16, 0)
    dte: int = 14
    width_strikes: int = 1
    velocity_pct: float = 0.76
    max_hold_sessions: int = 5
    friday_flatten: bool = True
    skip_fomc: bool = True
    require_above_ma20: bool = True
    require_window: bool = True
    ma_period: int = 20
    entry_weekdays: tuple[int, ...] = (0, 1, 2, 3)

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> PcRules:
        data = yaml.safe_load((path or DEFAULT_RULES).read_text(encoding="utf-8")) or {}
        entry = data.get("entry") or {}
        exit_cfg = data.get("exit") or {}

        def _t(raw: str, default: time) -> time:
            if not raw:
                return default
            h, m = str(raw).split(":")[:2]
            return time(int(h), int(m))

        raw_days = entry.get("weekdays", [0, 1, 2, 3])
        days = tuple(int(x) for x in raw_days)

        return cls(
            window_start=_t(entry.get("window_start_et"), time(15, 45)),
            window_end=_t(entry.get("window_end_et"), time(16, 0)),
            dte=int(entry.get("dte_target", 14)),
            width_strikes=int(entry.get("width_strikes", 1)),
            velocity_pct=float(exit_cfg.get("velocity_pct", 0.76)),
            max_hold_sessions=int(exit_cfg.get("max_hold_sessions", 5)),
            friday_flatten=bool(exit_cfg.get("friday_flatten_enabled", True)),
            skip_fomc=bool(entry.get("skip_fomc", True)),
            require_above_ma20=bool(entry.get("require_above_ma20", True)),
            require_window=bool(entry.get("require_window", True)),
            ma_period=int(entry.get("ma_period", 20)),
            entry_weekdays=days,
        )


@dataclass
class GateResult:
    allowed: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_pc_gates(
    *,
    now_et: datetime,
    close: float,
    ma20: float | None,
    rules: PcRules,
) -> GateResult:
    now = now_et.astimezone(ET) if now_et.tzinfo else now_et.replace(tzinfo=ET)
    if now.weekday() >= 5:
        return GateResult(False, "weekend")
    if now.weekday() == 4:
        return GateResult(False, "friday_no_entry")
    if now.weekday() not in rules.entry_weekdays:
        return GateResult(False, "weekday_blocked")
    if rules.require_window:
        t = now.time()
        if not (rules.window_start <= t < rules.window_end):
            return GateResult(False, "out_of_window")
    if rules.skip_fomc and near_fomc(now.date(), before=2, after=1):
        return GateResult(False, "fomc_window")
    if rules.require_above_ma20:
        if ma20 is None or not math.isfinite(float(ma20)):
            return GateResult(False, "ma20_unavailable")
        if float(close) <= float(ma20):
            return GateResult(False, "below_ma20")
    return GateResult(True, None)


def evaluate_pc_exits(
    pos: dict[str, Any],
    *,
    now_et: datetime,
    sessions_held: int,
    rules: PcRules,
) -> str | None:
    now = now_et.astimezone(ET) if now_et.tzinfo else now_et.replace(tzinfo=ET)
    credit = float(pos["entry_credit"])
    mark = float(pos["mark_value"])
    if credit > 0 and velocity_captured(entry_credit=credit, current_value=mark) >= (
        rules.velocity_pct
    ):
        return "velocity_76"
    if not bool(pos.get("above_ma20", True)):
        return "dma_break"
    if rules.friday_flatten and now.weekday() == 4 and now.time() >= time(15, 45):
        return "friday_flatten"
    if rules.max_hold_sessions > 0 and sessions_held >= rules.max_hold_sessions:
        return "hold_cap"
    return None


def _bs_put(spot: float, strike: float, dte: int, iv: float) -> float:
    t = max(0, int(dte)) / 365.0
    call = bs_call(spot, strike, t, iv, r=R)
    if t <= 1e-8:
        return max(0.0, strike - spot)
    return max(0.05, call - spot + strike * math.exp(-R * t))


def _atm(spot: float) -> float:
    return round(float(spot) / STRIKE_STEP) * STRIKE_STEP


def _ann_vol(rets: pd.Series, i: int, lookback: int = 20) -> float | None:
    if i < lookback:
        return None
    window = rets.iloc[i - lookback + 1 : i + 1]
    if window.isna().any():
        return None
    return float(window.std(ddof=1) * math.sqrt(252))


def _spread_mark(spot: float, short_k: float, long_k: float, dte: int, iv: float, width: float) -> float:
    return put_credit_value(
        short_mark=_bs_put(spot, short_k, dte, iv),
        long_mark=_bs_put(spot, long_k, dte, iv),
        width=width,
    )


def replay_pc_daily(df: pd.DataFrame, rules: PcRules | None = None) -> dict[str, Any]:
    """Close-to-close paper replay (modeled rv20). Used for local soak seed."""
    rules = rules or PcRules(require_window=False)
    work = df.copy().reset_index(drop=True)
    work["ma20"] = work["close"].rolling(rules.ma_period).mean()
    work["ret"] = work["close"].pct_change()
    work["weekday"] = work["date"].map(lambda d: d.weekday() if hasattr(d, "weekday") else d)
    width = float(rules.width_strikes) * STRIKE_STEP
    econ = PaperEconomics(
        commission_usd_per_contract=0.65,
        slippage_pct_of_premium=0.005,
        slippage_usd_per_share=0.12,
        slippage_max_pct_of_premium=0.015,
        premium_scale=1.0,
    )
    trades: list[dict[str, Any]] = []
    blocked = {"below_ma20": 0, "friday_no_entry": 0, "fomc_window": 0, "other": 0}
    open_pos: dict[str, Any] | None = None

    for i in range(len(work)):
        row = work.iloc[i]
        day = row["date"]
        if hasattr(day, "date"):
            day = day.date()
        now = datetime(day.year, day.month, day.day, 15, 50, tzinfo=ET)
        spot = float(row["close"])
        ma = row["ma20"]
        ma_f = float(ma) if pd.notna(ma) else None

        if open_pos is not None:
            rv = _ann_vol(work["ret"], i - 1) or open_pos["iv"]
            iv = min(max(rv, 0.08), 0.80)
            dte_x = max(0, rules.dte - (day - date.fromisoformat(open_pos["entry_date"])).days)
            mark = _spread_mark(
                spot, open_pos["short_strike"], open_pos["long_strike"], dte_x, iv, width
            )
            open_pos["mark_value"] = mark
            open_pos["above_ma20"] = ma_f is not None and spot > ma_f
            held = i - open_pos["entry_i"]
            reason = evaluate_pc_exits(open_pos, now_et=now, sessions_held=held, rules=rules)
            if reason:
                fill_in = entry_fill_premium(open_pos["entry_credit"], econ)
                fill_out = exit_fill_premium(mark, econ)
                pnl_pts = fill_in - fill_out
                max_risk = width - open_pos["entry_credit"]
                trades.append(
                    {
                        "entry_date": open_pos["entry_date"],
                        "exit_date": day.isoformat(),
                        "exit_reason": reason,
                        "entry_credit": open_pos["entry_credit"],
                        "exit_value": mark,
                        "pnl_usd": round(pnl_pts * 100.0, 2),
                        "roc_risk": round(pnl_pts / max_risk, 6) if max_risk > 0 else None,
                        "sessions_held": held,
                    }
                )
                open_pos = None

        if open_pos is not None:
            continue
        gate = evaluate_pc_gates(now_et=now, close=spot, ma20=ma_f, rules=rules)
        if not gate.allowed:
            key = gate.reason if gate.reason in blocked else "other"
            blocked[key] = blocked.get(key, 0) + 1
            continue
        rv = _ann_vol(work["ret"], i - 1)
        if rv is None:
            blocked["other"] += 1
            continue
        iv = min(max(rv, 0.08), 0.80)
        short_k = _atm(spot)
        long_k = select_long_put_strike(short_k, width_strikes=rules.width_strikes)
        short_p = _bs_put(spot, short_k, rules.dte, iv)
        long_p = _bs_put(spot, long_k, rules.dte, iv)
        built = build_put_credit(
            short_strike=short_k,
            short_premium=short_p,
            long_strike=long_k,
            long_premium=long_p,
            premium_scale=1.0,
        )
        if built is None:
            blocked["other"] += 1
            continue
        open_pos = {
            "entry_i": i,
            "entry_date": day.isoformat(),
            "entry_credit": built.net_credit,
            "short_strike": short_k,
            "long_strike": long_k,
            "iv": iv,
            "mark_value": built.net_credit,
            "above_ma20": True,
        }

    n = len(trades)
    wins = sum(1 for t in trades if (t["pnl_usd"] or 0) > 0)
    return {
        "n_entries": n,
        "n_blocked_below_ma": blocked["below_ma20"],
        "n_blocked_friday": blocked["friday_no_entry"],
        "n_blocked_fomc": blocked["fomc_window"],
        "win_pct": round(100.0 * wins / n, 2) if n else None,
        "mean_pnl_usd": round(sum(t["pnl_usd"] for t in trades) / n, 2) if n else None,
        "mean_roc_risk": round(
            sum(t["roc_risk"] for t in trades if t["roc_risk"] is not None)
            / max(1, sum(1 for t in trades if t["roc_risk"] is not None)),
            6,
        )
        if n
        else None,
        "trades": trades,
        "residual_open": open_pos is not None,
        "pricing_fidelity": "modeled_bs_rv20",
        "live_untouched": True,
    }


def load_state(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_STATE
    if not p.is_file():
        return {"paper_positions": {}, "closed": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    p = path or DEFAULT_STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def append_log(row: dict[str, Any], path: Path | None = None) -> None:
    p = path or DEFAULT_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def write_scoreboard(payload: dict[str, Any], path: Path | None = None) -> Path:
    p = path or DEFAULT_SCOREBOARD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p
