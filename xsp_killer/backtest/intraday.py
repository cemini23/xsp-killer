"""Stage B: session-aware 15-minute Lane A replay.

Entries only in the ET close window [15:45, 16:00). Exits and hold caps
delegate session truth to live ``xsp_session_open`` — no re-derived hours.
Exchange session keys map GTH evening (>=20:15 ET) to the next calendar date
so Sunday reopen and Monday morning share one hold session.
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
from xsp_killer.paper_economics import (
    PaperEconomics,
    entry_fill_premium,
    exit_fill_premium,
    pnl_from_entry_fill,
    pnl_pct,
)
from xsp_killer.xsp_sessions import exchange_session_key, trading_sessions_held

logger = logging.getLogger("xsp_killer.backtest.intraday")

ET = ZoneInfo("America/New_York")
ENTRY_WINDOW_START = time(15, 45)
ENTRY_WINDOW_END = time(16, 0)
RTH_START = time(9, 30)
RTH_END = time(16, 15)


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
    """Unique ordered exchange session keys for ``xsp_session_open`` bars only."""
    if bars is None or bars.empty:
        return []
    seen: list[date] = []
    seen_set: set[date] = set()
    for idx in bars.index:
        ts = _bar_ts_et(idx)
        if not xsp_session_open(ts):
            continue
        key = exchange_session_key(ts)
        if key not in seen_set:
            seen_set.add(key)
            seen.append(key)
    return seen


def completed_rth_session_closes(bars: pd.DataFrame) -> list[tuple[date, float]]:
    """Last observed RTH close per civil ET weekday date, ordered by date.

    RTH is Mon–Fri 09:30–16:15 ET. Each date's close is the last bar observed
    inside that window (completed session close for that civil date).
    """
    if bars is None or bars.empty:
        return []
    last_close: dict[date, float] = {}
    order: list[date] = []
    for i, idx in enumerate(bars.index):
        ts = _bar_ts_et(idx)
        if ts.weekday() >= 5:
            continue
        t = ts.time()
        if not (RTH_START <= t <= RTH_END):
            continue
        d = ts.date()
        if d not in last_close:
            order.append(d)
        last_close[d] = float(bars.iloc[i]["close"])
    return [(d, last_close[d]) for d in order]


def _daily_context_from_intraday(bars: pd.DataFrame) -> pd.DataFrame:
    """Build fixture-only daily closes from completed observed RTH sessions."""
    closes = completed_rth_session_closes(bars)
    if not closes:
        return pd.DataFrame(columns=["close"])
    return pd.DataFrame(
        {"close": [close for _, close in closes]},
        index=pd.DatetimeIndex([pd.Timestamp(day) for day, _ in closes]),
    )


def _unknown_regime_row() -> dict[str, Any]:
    return {
        "regime": "UNKNOWN",
        "regime_ok": False,
        "yellow_frac": None,
        "ema21": None,
        "sma50": None,
    }


def _daily_session_date(idx: Any) -> date:
    """Preserve date-labeled daily bars instead of timezone-shifting midnight."""
    ts = pd.Timestamp(idx)
    if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.date()
    return _bar_ts_et(ts).date()


def align_completed_daily_regime(
    intraday: pd.DataFrame,
    daily_context: pd.DataFrame,
) -> pd.DataFrame:
    """Align each decision bar with the latest prior civil day's regime."""
    daily = daily_context.sort_index()
    if daily.empty or "close" not in daily:
        return pd.DataFrame(
            [_unknown_regime_row() for _ in intraday.index],
            index=intraday.index,
        )

    regime = _regime_series(daily["close"].astype(float))
    by_date: dict[date, pd.Series] = {}
    for idx, row in regime.iterrows():
        by_date[_daily_session_date(idx)] = row
    dates = sorted(by_date)

    rows: list[dict[str, Any]] = []
    for idx in intraday.index:
        civil_date = _bar_ts_et(idx).date()
        eligible = [day for day in dates if day < civil_date]
        if not eligible:
            rows.append(_unknown_regime_row())
        else:
            rows.append(by_date[eligible[-1]].to_dict())
    return pd.DataFrame(rows, index=intraday.index)


def completed_hourly_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 15m bars into hourly buckets labeled at completion.

    Buckets are anchored at :30 to match the 09:30 RTH open. A bucket carrying
    a completion label after a decision timestamp is unavailable to that
    decision, even if later 15m rows are present in the replay frame.
    """
    if bars is None or bars.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    frame = bars.copy().sort_index()
    index = pd.DatetimeIndex(pd.to_datetime(frame.index))
    if index.tz is None:
        index = index.tz_localize(ET)
    else:
        index = index.tz_convert(ET)
    frame.index = index

    aggregations: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in frame.columns:
        aggregations["volume"] = "sum"
    hourly = frame.resample(
        "1h",
        origin="start_day",
        offset="30min",
        label="left",
        closed="left",
    ).agg(aggregations)
    hourly = hourly.dropna(subset=["close"])
    hourly.index = hourly.index + pd.Timedelta(hours=1)
    return hourly


def _latest_completed_iloc(index: pd.Index, decision: Any) -> int | None:
    """Return the latest context row completed by ``decision``."""
    if index.empty:
        return None
    decision_ts = pd.Timestamp(decision)
    if decision_ts.tzinfo is None:
        decision_ts = decision_ts.tz_localize(ET)
    else:
        decision_ts = decision_ts.tz_convert(ET)
    eligible = index[index <= decision_ts]
    if eligible.empty:
        return None
    return int(index.get_loc(eligible[-1]))


def _prior_day_spy_ok(
    completed_closes: list[tuple[date, float]],
    entry_civil_date: date,
) -> bool:
    """Require previous completed RTH close > the completed close before it."""
    prior = [(d, px) for d, px in completed_closes if d < entry_civil_date]
    if len(prior) < 2:
        return False
    prev_close = prior[-1][1]
    prev2_close = prior[-2][1]
    return prev_close > prev2_close


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
    """Raise ``InsufficientBarsError`` if floors unmet; return coverage on success."""
    from xsp_killer.backtest.bars import InsufficientBarsError

    cov = bar_coverage(bars)
    if cov["n_bars"] < min_bars:
        raise InsufficientBarsError(
            f"insufficient intraday bars: {cov['n_bars']} < min_bars={min_bars}"
        )
    if cov["n_sessions"] < min_sessions:
        raise InsufficientBarsError(
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
    daily_context: pd.DataFrame | None = None,
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

    rth_closes = completed_rth_session_closes(bars)
    if daily_context is None:
        if source.lower() == "uw":
            raise ValueError("daily_context is required for UW intraday replay")
        daily_context = _daily_context_from_intraday(bars)
        result.notes.append("daily_context derived from completed fixture RTH closes")
    regime_df = align_completed_daily_regime(bars, daily_context)

    primary_bars = (
        completed_hourly_bars(bars)
        if ta_rules.primary_timeframe == "1h"
        else bars.copy()
    )
    try:
        enriched = enrich_bars(
            primary_bars, period=ta_rules.bb_period, std=ta_rules.bb_std
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
                ei = _latest_completed_iloc(enriched.index, idx)
                if ei is not None:
                    ta_sig = _ta_signal_at(enriched, ei, ta_rules)

            # Strategy alerts already require xsp_session_open internally.
            alerts = evaluate_exit_alerts(
                pos, lane_rules, now_et=now_et, ta_signal=ta_sig
            )

            held_sessions = trading_sessions_held(op.entry_ts, now_et)

            # Forced exits (time_stop / hold_cap) only on session-open bars.
            # Precedence on open bars: strategy alert > expiry time_stop > hold_cap.
            force_reason = None
            if session_open:
                if dte <= 0:
                    force_reason = "time_stop"
                elif (
                    max_hold_sessions is not None
                    and max_hold_sessions > 0
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

        # --- entry decision: at most one per ET civil date; window only ---
        max_open = int(knobs["max_open_positions"])
        if len(open_book) >= max_open:
            continue
        if last_entry_date == today:
            continue
        if not in_entry_window(now_et):
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
            ei = _latest_completed_iloc(enriched.index, idx)
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

        if knobs["prior_day_spy_positive"]:
            if not _prior_day_spy_ok(rth_closes, today):
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

    # Never fabricate residual liquidation. Conservatively mark unresolved
    # exposure through the normal exit-fill economics, but keep it out of trades.
    if open_book:
        last_i = len(bars) - 1
        last_now = _bar_ts_et(bars.index[last_i])
        last_spy = float(bars.iloc[last_i]["close"])
        marked_returns: list[float] = []
        for op in open_book:
            dte = max(0, (op.position.expiration_date - last_now.date()).days)
            mark = synthesize_call_premium(
                last_spy,
                xsp_strike=op.position.strike,
                dte=dte,
                iv=iv_seed,
                premium_scale=premium_scale,
                use_bs=use_bs,
            )
            if op.entry_fill > 0:
                exit_fill = exit_fill_premium(mark, econ)
                marked_returns.append((exit_fill - op.entry_fill) / op.entry_fill)
        result.residual_open = len(open_book)
        result.residual_marked_pnl_pct = (
            round(sum(marked_returns) / len(marked_returns), 6)
            if marked_returns
            else None
        )
        result.notes.append(f"residual_open={result.residual_open}")
        result.notes.append(
            f"residual_marked_pnl_pct={result.residual_marked_pnl_pct}"
        )

    return result
