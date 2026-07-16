"""Lane A backtest replay engine.

Reuses ``evaluate_exit_alerts``, ``lane_a_ta``, ``paper_economics``, and
variant-merged rules. Does **not** invent a second strategy.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from xsp_killer.backtest.option_model import synthesize_call_premium
from xsp_killer.backtest.variants import entry_knobs_from_rules_dict
from xsp_killer.backtest.volume_gate import (
    prior_day_volume_percentile,
    volume_gate_allows,
)
from xsp_killer.lane_a_entry import round_xsp_strike
from xsp_killer.lane_a_monitor import (
    LaneAPosition,
    LaneRules,
    evaluate_exit_alerts,
    regime_gate_allows,
)
from xsp_killer.lane_a_ta import (
    TaRules,
    TaSignal,
    _bar_snapshot,
    detect_bb_bounce_entry,
    detect_upper_bb_exit,
    detect_upper_bb_touch,
    enrich_bars,
    evaluate_timeframe,
)
from xsp_killer.macro_regime import (
    EMA_FAST,
    EMA_RISING_BARS,
    SMA_SLOW,
    yellow_band_frac,
)
from xsp_killer.paper_economics import (
    PaperEconomics,
    entry_fill_premium,
    exit_fill_premium,
    pnl_from_entry_fill,
    pnl_pct,
)
from xsp_killer.xsp_sessions import trading_sessions_held

logger = logging.getLogger("xsp_killer.backtest.engine")

ET = ZoneInfo("America/New_York")
# Daily bars evaluate at RTH close-window so xsp_session_open is True.
EVAL_TIME = time(15, 45)


@dataclass
class TradeRow:
    variant_id: str
    entry_ts: str
    exit_ts: str
    dte_at_entry: int
    strike: float
    exit_reason: str
    net_pnl_pct: float
    pnl_usd: float
    entry_mid: float
    exit_mid: float
    entry_fill: float
    bars_held: int
    regime_at_entry: str | None = None
    entry_reason: str = ""
    sessions_held: int = 0
    bar_interval: str = "1d"
    # Analysis-only: any mark within 90 min of entry had ret_pct > 0 before exit.
    early_green: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestResult:
    variant_id: str
    trades: list[TradeRow] = field(default_factory=list)
    n_entries_blocked: int = 0
    bars_used: int = 0
    source: str = "fixture"
    notes: list[str] = field(default_factory=list)
    residual_open: int = 0
    residual_marked_pnl_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "trades": [t.to_dict() for t in self.trades],
            "n_trades": len(self.trades),
            "n_entries_blocked": self.n_entries_blocked,
            "bars_used": self.bars_used,
            "source": self.source,
            "notes": list(self.notes),
            "residual_open": self.residual_open,
            "residual_marked_pnl_pct": self.residual_marked_pnl_pct,
        }


def _bar_ts_et(idx: Any) -> datetime:
    ts = pd.Timestamp(idx)
    if ts.tzinfo is None:
        ts = ts.tz_localize(ET)
    else:
        ts = ts.tz_convert(ET)
    # Normalize daily midnight indexes to RTH eval time.
    if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        ts = ts.replace(hour=EVAL_TIME.hour, minute=EVAL_TIME.minute, second=0)
    return ts.to_pydatetime()


def _pick_dte(
    knobs: dict[str, Any],
) -> int:
    mode = knobs["dte_pick"]
    if mode == "target" and knobs.get("dte_target") is not None:
        return int(knobs["dte_target"])
    if mode == "max":
        return int(knobs["dte_max"])
    return int(knobs["dte_min"])


def _pick_strike(spy_close: float, strike_pick: str) -> float:
    atm = round_xsp_strike(spy_close)
    mode = (strike_pick or "atm_only").lower()
    if mode == "otm_one":
        return atm + 5.0
    # atm_only / cheapest_near_atm — without chain, ATM is the offline proxy
    return atm


def _regime_series(closes: pd.Series) -> pd.DataFrame:
    """Per-bar GREEN/YELLOW/RED from EMA21/SMA50 (same axes as macro_regime)."""
    ema = closes.ewm(span=EMA_FAST, adjust=False).mean()
    sma = closes.rolling(SMA_SLOW).mean()
    rows: list[dict[str, Any]] = []
    for i in range(len(closes)):
        px = float(closes.iloc[i])
        e = float(ema.iloc[i]) if pd.notna(ema.iloc[i]) else float("nan")
        s = float(sma.iloc[i]) if pd.notna(sma.iloc[i]) else float("nan")
        if math.isnan(e) or math.isnan(s) or i < SMA_SLOW - 1:
            rows.append(
                {
                    "regime": "UNKNOWN",
                    "regime_ok": False,
                    "yellow_frac": None,
                    "ema21": e if not math.isnan(e) else None,
                    "sma50": s if not math.isnan(s) else None,
                }
            )
            continue
        ema_up = True
        if i >= EMA_RISING_BARS:
            ema_up = float(ema.iloc[i]) > float(ema.iloc[i - EMA_RISING_BARS])
        if px > e and ema_up:
            regime, ok = "GREEN", True
        elif px > s:
            regime, ok = "YELLOW", False
        else:
            regime, ok = "RED", False
        yf = yellow_band_frac(px, e, s)
        rows.append(
            {
                "regime": regime,
                "regime_ok": ok,
                "yellow_frac": yf,
                "ema21": e,
                "sma50": s,
            }
        )
    return pd.DataFrame(rows, index=closes.index)


def _iloc_at(index: pd.Index, label: Any) -> int | None:
    """Safe integer location for a label (handles numpy scalar / slice)."""
    if label not in index:
        return None
    ei = index.get_loc(label)
    if isinstance(ei, slice):
        return int(ei.start or 0)
    if isinstance(ei, int):
        return ei
    try:
        # numpy integer or ndarray of matches
        return int(ei)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _ta_entry_ok_at(
    enriched: pd.DataFrame,
    i: int,
    *,
    require_vwap: bool,
    bb_period: int,
) -> tuple[bool, str]:
    """Coarse BB-bounce entry on the bar path (daily proxy for dip-swing)."""
    if i < 1 or i >= len(enriched):
        return False, "insufficient bars"
    if i < bb_period:
        return False, "warmup"
    prev_row = enriched.iloc[i - 1]
    curr_row = enriched.iloc[i]
    try:
        prev = _bar_snapshot(prev_row, "1d")
        curr = _bar_snapshot(curr_row, "1d")
    except Exception as exc:  # noqa: BLE001
        return False, f"snapshot failed: {exc}"
    return detect_bb_bounce_entry(prev, curr, require_vwap=require_vwap)


def _ta_signal_at(
    enriched: pd.DataFrame | None,
    i: int,
    ta_rules: TaRules,
) -> Any | None:
    """Lightweight TA signal object for exit BB gate (upper touch / rejection)."""
    if enriched is None or i < 1 or len(enriched) < 2:
        return None
    sub = enriched.iloc[: i + 1]
    raw = sub[["open", "high", "low", "close"]].copy()
    if "volume" in sub.columns:
        raw["volume"] = sub["volume"]
    else:
        raw["volume"] = 0.0
    if len(raw) < ta_rules.bb_period + 2:
        return None
    prev, curr = evaluate_timeframe(raw, "1d", ta_rules)
    if curr is None or prev is None:
        return None
    exit_ok, detail = detect_upper_bb_exit(
        prev, curr, tolerance_pct=ta_rules.upper_bb_touch_tolerance_pct
    )
    touched = detect_upper_bb_touch(
        prev, curr, tolerance_pct=ta_rules.upper_bb_touch_tolerance_pct
    )
    if exit_ok:
        sig_name = "upper_bb_exit"
    elif touched:
        sig_name = "upper_bb_touch"
    else:
        sig_name = "none"
    return TaSignal(
        signal=sig_name,
        primary=curr,
        confirm=None,
        entry_ok=False,
        exit_ok=exit_ok,
        upper_bb_touched=touched,
        detail=detail,
    )


@dataclass
class _OpenPos:
    position: LaneAPosition
    entry_fill: float
    entry_i: int
    entry_ts: datetime
    entry_reason: str
    regime_at_entry: str | None
    dte_at_entry: int


def run_backtest(
    bars: pd.DataFrame,
    rules_path: Path,
    *,
    variant_id: str = "baseline",
    iv_seed: float = 0.18,
    use_bs: bool = True,
    source: str = "fixture",
    force_one_entry_per_day: bool = True,
    max_hold_sessions: int | None = None,
) -> BacktestResult:
    """Replay one merged ruleset over OHLC bars; return closed trades."""
    data = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    knobs = entry_knobs_from_rules_dict(data)
    lane_rules = LaneRules.from_yaml(rules_path)
    ta_rules = TaRules.from_yaml(rules_path)
    econ = PaperEconomics.from_yaml(rules_path)
    premium_scale = econ.premium_scale

    result = BacktestResult(
        variant_id=variant_id, bars_used=len(bars), source=source
    )
    if bars is None or bars.empty:
        result.notes.append("empty bars")
        return result

    closes = bars["close"].astype(float)
    regime_df = _regime_series(closes)

    # Enrich once for BB entry/exit on the full path.
    try:
        enriched = enrich_bars(
            bars.copy(), period=ta_rules.bb_period, std=ta_rules.bb_std
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrich_bars failed: %s", exc)
        enriched = bars.copy()
        result.notes.append(f"enrich_bars failed: {exc}")

    # Map enriched index positions back to bars index
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

        # --- mark open positions & evaluate exits ---
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

            alerts = evaluate_exit_alerts(
                pos, lane_rules, now_et=now_et, ta_signal=ta_sig
            )
            force_reason = None
            if dte <= 0:
                force_reason = "time_stop"
            bars_held = i - op.entry_i
            held_sessions = trading_sessions_held(op.entry_ts, now_et)
            if (
                not alerts
                and not force_reason
                and max_hold_sessions is not None
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
            # Net % vs entry fill (economics-aware) for ranking
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
                    bars_held=bars_held,
                    regime_at_entry=op.regime_at_entry,
                    entry_reason=op.entry_reason,
                    sessions_held=held_sessions,
                    bar_interval="1d",
                )
            )
        open_book = still_open

        # --- entry decision ---
        max_open = int(knobs["max_open_positions"])
        if len(open_book) >= max_open:
            continue
        if force_one_entry_per_day and last_entry_date == today:
            continue
        # Warmup: need SMA50 history
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
            # close_window_only / close_window_and_bb: daily close entry, no bounce req
            ta_entry_ok = False

        allowed, block_reason = regime_gate_allows(
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
            prev_close = float(bars.iloc[i - 1]["close"])
            prev2 = float(bars.iloc[i - 2]["close"]) if i >= 2 else prev_close
            if prev_close <= prev2:
                result.n_entries_blocked += 1
                continue

        vol_pctile = prior_day_volume_percentile(
            bars["volume"] if "volume" in bars.columns else pd.Series(dtype=float),
            i,
            lookback=int(knobs.get("volume_gate_lookback") or 63),
        )
        vol_ok, _vol_reason = volume_gate_allows(
            prior_vol_pctile=vol_pctile,
            max_pctile=knobs.get("volume_gate_max_pctile"),
        )
        if not vol_ok:
            result.n_entries_blocked += 1
            continue

        # Open new paper position
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
        entry_ts = now_et.isoformat()
        pos = LaneAPosition(
            position_id=f"bt:{variant_id}:{today.isoformat()}:{int(strike)}",
            chain_symbol="XSP",
            option_type="call",
            strike=strike,
            expiration_date=exp,
            quantity=float(knobs["quantity"]),
            average_price=fill,
            mark_price=entry_mid,
            dte=dte_target,
            lane="A",
            entry_ts=entry_ts,
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

    # Force-close any residual opens at last bar
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
            bars_held = i - op.entry_i
            held_sessions = trading_sessions_held(op.entry_ts, now_et)
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
                    bars_held=bars_held,
                    regime_at_entry=op.regime_at_entry,
                    entry_reason=op.entry_reason,
                    sessions_held=held_sessions,
                    bar_interval="1d",
                )
            )

    return result
