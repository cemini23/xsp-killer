"""Stage B: session-aware 15-minute Lane A replay.

Entries only in the ET close window [15:45, 16:00). Exits and hold caps
delegate session truth to live ``xsp_session_open`` — no re-derived hours.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from xsp_killer.backtest.engine import (
    BacktestResult,
    TradeRow,
    _iloc_at,
    _pick_dte,
    _pick_strike,
    _regime_series,
    _ta_entry_ok_at,
    _ta_signal_at,
)
from xsp_killer.backtest.option_model import synthesize_call_premium
from xsp_killer.backtest.variants import entry_knobs_from_rules_dict
from xsp_killer.lane_a_monitor import (
    LaneAPosition,
    LaneRules,
    evaluate_exit_alerts,
    regime_gate_allows,
    xsp_session_open,
)
from xsp_killer.lane_a_ta import TaRules, enrich_bars
from xsp_killer.macro_regime import SMA_SLOW
from xsp_killer.paper_economics import (
    PaperEconomics,
    entry_fill_premium,
    exit_fill_premium,
    pnl_from_entry_fill,
    pnl_pct,
)

logger = logging.getLogger("xsp_killer.backtest.intraday")

ET = ZoneInfo("America/New_York")
ENTRY_WINDOW_START = time(15, 45)
ENTRY_WINDOW_END = time(16, 0)


def _to_et(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=ET)
    return ts.astimezone(ET)


def _bar_ts_et(idx: Any) -> datetime:
    ts = pd.Timestamp(idx)
    if ts.tzinfo is None:
        ts = ts.tz_localize(ET)
    else:
        ts = ts.tz_convert(ET)
    return ts.to_pydatetime()


def in_entry_window(ts: datetime) -> bool:
    """True for ET weekdays in [15:45, 16:00) when XSP session is open."""
    now = _to_et(ts)
    if now.weekday() >= 5:
        return False
    t = now.time()
    if not (ENTRY_WINDOW_START <= t < ENTRY_WINDOW_END):
        return False
    return xsp_session_open(now)


def exit_session_open(ts: datetime) -> bool:
    """Exit eligibility — exact live ``xsp_session_open`` (no re-derived hours)."""
    return xsp_session_open(_to_et(ts))


def session_date_order(bars: pd.DataFrame) -> list[date]:
    """Ordered distinct ET dates that have at least one session-open bar."""
    if bars is None or bars.empty:
        return []
    seen: list[date] = []
    seen_set: set[date] = set()
    for idx in bars.index:
        ts = _bar_ts_et(idx)
        if not xsp_session_open(ts):
            continue
        d = ts.date()
        if d not in seen_set:
            seen_set.add(d)
            seen.append(d)
    return seen


def trading_sessions_held(
    entry_ts: datetime,
    now_ts: datetime,
    session_dates: list[date],
) -> int:
    """Index distance on observed session dates (not calendar-day subtraction)."""
    if not session_dates:
        return 0
    entry_d = _to_et(entry_ts).date()
    now_d = _to_et(now_ts).date()
    try:
        i_entry = session_dates.index(entry_d)
        i_now = session_dates.index(now_d)
    except ValueError:
        return 0
    return max(0, i_now - i_entry)


def bar_coverage(bars: pd.DataFrame) -> dict[str, Any]:
    """Summary of observed 15m coverage (phases never invented)."""
    if bars is None or bars.empty:
        return {
            "n_bars": 0,
            "n_sessions": 0,
            "has_overnight_bars": False,
            "session_phases_observed": [],
            "start": None,
            "end": None,
            "interval": "15m",
        }
    session_dates = session_date_order(bars)
    phases: list[str] = []
    phase_set: set[str] = set()
    has_overnight = False
    for idx in bars.index:
        ts = _bar_ts_et(idx)
        t = ts.time()
        wd = ts.weekday()
        if not xsp_session_open(ts):
            continue
        # Classify observed open phase (mirror live calendar; do not invent).
        if wd == 5 or t <= time(9, 25) or t >= time(20, 15):
            name = "GTH"
            if t < time(9, 30) or t >= time(16, 15) or wd >= 5:
                has_overnight = True
        elif time(9, 30) <= t <= time(16, 15):
            name = "RTH"
        elif time(16, 15) < t <= time(17, 0):
            name = "Curb"
            has_overnight = True
        else:
            continue
        if name not in phase_set:
            phase_set.add(name)
            phases.append(name)
    start = _bar_ts_et(bars.index[0])
    end = _bar_ts_et(bars.index[-1])
    return {
        "n_bars": int(len(bars)),
        "n_sessions": len(session_dates),
        "has_overnight_bars": has_overnight,
        "session_phases_observed": phases,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "interval": "15m",
    }


def assert_intraday_coverage(
    bars: pd.DataFrame,
    *,
    min_bars: int,
    min_sessions: int,
) -> dict[str, Any]:
    """Raise if coverage floors are not met; return coverage dict on success."""
    cov = bar_coverage(bars)
    if cov["n_bars"] < min_bars:
        raise ValueError(
            f"insufficient intraday bars: {cov['n_bars']} < min_bars={min_bars}"
        )
    if cov["n_sessions"] < min_sessions:
        raise ValueError(
            f"insufficient sessions: {cov['n_sessions']} < min_sessions={min_sessions}"
        )
    return cov


@dataclass
class _OpenPos:
    position: LaneAPosition
    entry_fill: float
    entry_i: int
    entry_ts: datetime
    entry_reason: str
    regime_at_entry: str | None
    dte_at_entry: int


def run_intraday_backtest(
    bars: pd.DataFrame,
    rules_path: Path,
    *,
    variant_id: str,
    iv_seed: float = 0.18,
    source: str = "fixture",
    max_hold_sessions: int | None = None,
    use_bs: bool = True,
) -> BacktestResult:
    """Replay one ruleset on 15m bars with live XSP session semantics."""
    data = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    knobs = entry_knobs_from_rules_dict(data)
    lane_rules = LaneRules.from_yaml(rules_path)
    ta_rules = TaRules.from_yaml(rules_path)
    econ = PaperEconomics.from_yaml(rules_path)
    premium_scale = econ.premium_scale

    n_bars = len(bars) if bars is not None else 0
    result = BacktestResult(
        variant_id=variant_id, bars_used=n_bars, source=source
    )
    result.notes.append(
        "Stage B 15m replay; exits gated by live xsp_session_open; "
        "premiums modeled (no historical option marks)."
    )
    if bars is None or bars.empty:
        result.notes.append("empty bars")
        return result

    session_dates = session_date_order(bars)
    closes = bars["close"].astype(float)
    regime_df = _regime_series(closes)

    try:
        enriched = enrich_bars(
            bars.copy(), period=ta_rules.bb_period, std=ta_rules.bb_std
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrich_bars failed: %s", exc)
        enriched = bars.copy()
        result.notes.append(f"enrich_bars failed: {exc}")

    open_book: list[_OpenPos] = []
    last_entry_date: date | None = None

    for i, idx in enumerate(bars.index):
        now_et = _bar_ts_et(idx)
        today = now_et.date()
        spy = float(bars.iloc[i]["close"])
        reg_row = regime_df.iloc[i]
        regime = reg_row["regime"]
        regime_ok = bool(reg_row["regime_ok"])
        yellow_frac = reg_row["yellow_frac"]
        session_open = xsp_session_open(now_et)

        # --- mark open positions & evaluate exits (before new entries) ---
        still_open: list[_OpenPos] = []
        for op in open_book:
            pos = op.position
            exp = pos.expiration_date
            dte = max(0, (exp - today).days)
            pos.dte = dte
            mark = synthesize_call_premium(
                spy,
                xsp_strike=pos.strike,
                dte=dte,
                iv=iv_seed,
                premium_scale=premium_scale,
                use_bs=use_bs,
            )
            pos.mark_price = mark
            pos.mark_quote_stale = False
            pos.pnl_per_contract = pnl_from_entry_fill(
                entry_fill=op.entry_fill, exit_mid=mark, econ=econ
            )
            pos.pnl_usd = pos.pnl_per_contract * pos.quantity

            ta_sig = None
            if lane_rules.require_upper_bb_for_take_profit:
                ei = _iloc_at(enriched.index, idx)
                if ei is not None:
                    ta_sig = _ta_signal_at(enriched, ei, ta_rules)

            # evaluate_exit_alerts applies xsp_session_open internally
            alerts = evaluate_exit_alerts(
                pos, lane_rules, now_et=now_et, ta_signal=ta_sig
            )
            force_reason = None
            if dte <= 0:
                force_reason = "time_stop"

            held_sessions = trading_sessions_held(
                op.entry_ts, now_et, session_dates
            )
            # Hold cap only on a session-open bar (not Saturday closed time).
            if (
                not alerts
                and not force_reason
                and max_hold_sessions is not None
                and session_open
                and held_sessions >= max_hold_sessions
            ):
                force_reason = "hold_cap"

            if alerts:
                reason = alerts[0].exit_reason
            elif force_reason:
                reason = force_reason
            else:
                still_open.append(op)
                continue

            ret = pnl_pct(pos.entry_mid_premium or op.entry_fill, mark) or 0.0
            if op.entry_fill > 0:
                exit_fill = exit_fill_premium(mark, econ)
                net_pct = (exit_fill - op.entry_fill) / op.entry_fill
            else:
                net_pct = ret

            result.trades.append(
                TradeRow(
                    variant_id=variant_id,
                    entry_ts=pos.entry_ts or "",
                    exit_ts=now_et.isoformat(),
                    dte_at_entry=op.dte_at_entry,
                    strike=pos.strike,
                    exit_reason=reason,
                    net_pnl_pct=round(net_pct, 6),
                    pnl_usd=round(float(pos.pnl_usd or 0.0), 2),
                    entry_mid=float(pos.entry_mid_premium or 0.0),
                    exit_mid=float(mark),
                    entry_fill=float(op.entry_fill),
                    bars_held=i - op.entry_i,
                    regime_at_entry=op.regime_at_entry,
                    entry_reason=op.entry_reason,
                    sessions_held=held_sessions,
                    bar_interval="15m",
                )
            )
        open_book = still_open

        # --- entry decision: at most one per ET date; window only ---
        max_open = int(knobs["max_open_positions"])
        if len(open_book) >= max_open:
            continue
        if last_entry_date == today:
            continue
        if not in_entry_window(now_et):
            continue
        # Warmup: need SMA50 history on the 15m path
        if i < SMA_SLOW:
            continue

        ta_entry_ok = False
        ta_detail = ""
        mode = knobs["ta_entry_mode"]
        gate = knobs["regime_gate"]
        need_bounce = (
            gate == "DIP_BOUNCE"
            or mode == "bb_bounce"
            or knobs.get("intraday_entry_enabled")
        )
        if need_bounce:
            ei = _iloc_at(enriched.index, idx)
            if ei is not None:
                ta_entry_ok, ta_detail = _ta_entry_ok_at(
                    enriched,
                    ei,
                    require_vwap=bool(knobs["require_vwap_reclaim"]),
                    bb_period=ta_rules.bb_period,
                )
        else:
            ta_entry_ok = False

        allowed, _block_reason = regime_gate_allows(
            regime_gate=gate,
            regime=str(regime) if regime else None,
            regime_ok=regime_ok,
            yellow_frac=float(yellow_frac) if yellow_frac is not None else None,
            ta_entry_ok=ta_entry_ok,
            yellow_frac_min=float(knobs["regime_yellow_frac_min"]),
            yellow_require_bounce=bool(knobs["regime_yellow_require_bounce"]),
        )
        if not allowed:
            result.n_entries_blocked += 1
            continue

        if knobs["prior_day_spy_positive"] and i >= 1:
            # Compare prior session close vs the session before that when possible
            prev_close = float(bars.iloc[i - 1]["close"])
            prev2 = float(bars.iloc[i - 2]["close"]) if i >= 2 else prev_close
            if prev_close <= prev2:
                result.n_entries_blocked += 1
                continue

        dte_target = _pick_dte(knobs)
        exp = today + timedelta(days=dte_target)
        strike = _pick_strike(spy, knobs["strike_pick"])
        entry_mid = synthesize_call_premium(
            spy,
            xsp_strike=strike,
            dte=dte_target,
            iv=iv_seed,
            premium_scale=premium_scale,
            use_bs=use_bs,
        )
        fill = entry_fill_premium(entry_mid, econ)
        entry_ts_s = now_et.isoformat()
        pos = LaneAPosition(
            position_id=f"bt15:{variant_id}:{today.isoformat()}:{int(strike)}",
            chain_symbol="XSP",
            option_type="call",
            strike=strike,
            expiration_date=exp,
            quantity=float(knobs["quantity"]),
            average_price=fill,
            mark_price=entry_mid,
            dte=dte_target,
            lane="A",
            entry_ts=entry_ts_s,
            entry_mid_premium=entry_mid,
            mark_quote_stale=False,
        )
        reason = (
            f"bb_bounce:{ta_detail}"
            if need_bounce and ta_entry_ok
            else f"close_entry:{gate}"
        )
        open_book.append(
            _OpenPos(
                position=pos,
                entry_fill=fill,
                entry_i=i,
                entry_ts=now_et,
                entry_reason=reason,
                regime_at_entry=str(regime) if regime else None,
                dte_at_entry=dte_target,
            )
        )
        last_entry_date = today

    # Residual force-close at last bar
    if open_book and len(bars):
        i = len(bars) - 1
        idx = bars.index[i]
        now_et = _bar_ts_et(idx)
        spy = float(bars.iloc[i]["close"])
        today = now_et.date()
        for op in open_book:
            pos = op.position
            dte = max(0, (pos.expiration_date - today).days)
            mark = synthesize_call_premium(
                spy,
                xsp_strike=pos.strike,
                dte=dte,
                iv=iv_seed,
                premium_scale=premium_scale,
                use_bs=use_bs,
            )
            pos.mark_price = mark
            pos.pnl_per_contract = pnl_from_entry_fill(
                entry_fill=op.entry_fill, exit_mid=mark, econ=econ
            )
            pos.pnl_usd = pos.pnl_per_contract * pos.quantity
            if op.entry_fill > 0:
                exit_fill = exit_fill_premium(mark, econ)
                net_pct = (exit_fill - op.entry_fill) / op.entry_fill
            else:
                net_pct = 0.0
            held_sessions = trading_sessions_held(
                op.entry_ts, now_et, session_dates
            )
            result.trades.append(
                TradeRow(
                    variant_id=variant_id,
                    entry_ts=pos.entry_ts or "",
                    exit_ts=now_et.isoformat(),
                    dte_at_entry=op.dte_at_entry,
                    strike=pos.strike,
                    exit_reason="end_of_series",
                    net_pnl_pct=round(net_pct, 6),
                    pnl_usd=round(float(pos.pnl_usd or 0.0), 2),
                    entry_mid=float(pos.entry_mid_premium or 0.0),
                    exit_mid=float(mark),
                    entry_fill=float(op.entry_fill),
                    bars_held=i - op.entry_i,
                    regime_at_entry=op.regime_at_entry,
                    entry_reason=op.entry_reason,
                    sessions_held=held_sessions,
                    bar_interval="15m",
                )
            )

    return result
