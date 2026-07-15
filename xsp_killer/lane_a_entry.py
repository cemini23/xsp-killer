"""XSP Lane A paper entry — automated log-only entries in 15:45–16:00 ET window.

No Robinhood orders. Uses SPY option chain as XSP premium proxy for paper marks.

Invariants:
- Paper log only (``paper_mode: automated_log_only``) — no Robinhood order placement from this module.
- At most one paper entry per ET session (``already_entered_today`` dedupe unless ``force``).
- Macro regime gate (``regime_gate_allows``) must pass before any paper entry is recorded.
- Entry window is 15:45–16:00 ET RTH; skips outside window are logged, not silently dropped.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from xsp_killer.conductor_shadow import shadow_review_entry
from xsp_killer.lane_a_monitor import (
    DEFAULT_PAPER_LOG,
    DEFAULT_RULES,
    DEFAULT_STATE,
    LaneRules,
    compute_dte,
    is_lane_a_contract,
    load_state,
    parse_expiration,
    read_regime_detail,
    regime_gate_allows,
    save_state,
)
from xsp_killer.lane_a_ta import TaRules, TaSignal, evaluate_ta_signals, in_rth
from xsp_killer.paper_economics import load_premium_scale, scale_spy_premium
from xsp_killer.risk_gates import entry_allowed_by_risk, risk_gate_snapshot
from xsp_killer.spy_quote import (
    fetch_spy_call_quote as fetch_spy_call_mark,
)
from xsp_killer.spy_quote import (
    fetch_spy_call_quote_legacy as fetch_spy_call_quote,
)
from xsp_killer.spy_quote import (
    xsp_strike_to_spy_chain_strike,
)

logger = logging.getLogger("xsp_killer.xsp_lane_a_entry")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "briefs" / "xsp-lane-a-entry-latest.json"
DEFAULT_TELEMETRY_BRIEF = ROOT / "briefs" / "xsp-lane-a-entry-telemetry-latest.json"
ET = ZoneInfo("America/New_York")

NYSE_2026_HOLIDAYS = {
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
}


@dataclass
class EntryRules:
    window_start_et: time
    window_end_et: time
    prior_day_spy_positive: bool
    max_open_positions: int
    quantity: float
    enabled: bool
    chain_symbol: str = "XSP"
    strike_max_steps_from_atm: int = 1
    dte_pick: str = "min"
    dte_target: int | None = None
    strike_pick: str = "cheapest_near_atm"
    debit_spread_shadow: bool = False
    debit_spread_width_strikes: int = 2

    @classmethod
    def from_yaml(cls, path: Path) -> EntryRules:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entry = data.get("entry") or {}
        paper = data.get("paper_entry") or {}

        def _parse_time(s: str) -> time:
            h, m = s.split(":")
            return time(int(h), int(m))

        return cls(
            window_start_et=_parse_time(str(entry.get("window_start_et", "15:45"))),
            window_end_et=_parse_time(str(entry.get("window_end_et", "16:00"))),
            prior_day_spy_positive=bool(entry.get("prior_day_spy_positive", False)),
            max_open_positions=int(paper.get("max_open_positions", 1)),
            quantity=float(paper.get("quantity", 1)),
            enabled=bool(paper.get("enabled", True)),
            chain_symbol=str(data.get("instrument", "XSP")).upper(),
            strike_max_steps_from_atm=int(entry.get("strike_max_steps_from_atm", 1)),
            dte_pick=str(entry.get("dte_pick", "min")).strip().lower(),
            dte_target=int(entry["dte_target"])
            if entry.get("dte_target") is not None
            else None,
            strike_pick=str(entry.get("strike_pick", "cheapest_near_atm"))
            .strip()
            .lower(),
            debit_spread_shadow=bool(entry.get("debit_spread_shadow", False)),
            debit_spread_width_strikes=int(entry.get("debit_spread_width_strikes", 2)),
        )


@dataclass
class EntryDecision:
    entered: bool
    evaluated_at: str
    logic_version: str
    in_window: bool
    regime: str | None
    regime_ok: bool
    prior_day_spy_return_pct: float | None
    prior_day_ok: bool
    regime_frac: float | None = None
    regime_gate: str | None = None
    prior_day_spy_session: str | None = None
    skip_reason: str | None = None
    position: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    ta_snapshot: dict[str, Any] | None = None
    bb_entry_ok: bool = False
    vol_shadow: dict[str, Any] | None = None
    premium_scale_used: float | None = None
    risk_gate: dict[str, Any] | None = None
    live_order: dict[str, Any] | None = None
    debit_spread_shadow: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def paper_entry_enabled() -> bool:
    return os.getenv("XSP_LANE_A_PAPER_ENTRY", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def in_entry_window(now_et: datetime, rules: EntryRules) -> bool:
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    return rules.window_start_et <= t < rules.window_end_et


def open_paper_positions(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("paper_positions") or {}
    if not isinstance(raw, dict):
        return []
    out: list[dict[str, Any]] = []
    for pos in raw.values():
        if isinstance(pos, dict) and pos.get("status", "open") == "open":
            out.append(pos)
    return out


def already_entered_today(state: dict[str, Any], today: date) -> bool:
    """True only after a successful entry today (not failed attempts)."""
    day = today.isoformat()
    for pos in (state.get("paper_positions") or {}).values():
        if not isinstance(pos, dict):
            continue
        if str(pos.get("entry_ts") or "")[:10] == day:
            return True
    for evt in state.get("entry_log") or []:
        if not isinstance(evt, dict):
            continue
        if (
            evt.get("entered")
            and evt.get("position_id")
            and str(evt.get("evaluated_at", ""))[:10] == day
        ):
            return True
    return False


def fetch_spy_ohlcv() -> tuple[float | None, float | None, float | None, str | None]:
    """Return (prior_close, prior_open, prior_close_to_close_return_pct, session_date)."""
    try:
        import yfinance as yf

        hist = yf.Ticker("SPY").history(period="5d", interval="1d", timeout=10)
        if hist is None or len(hist) < 2:
            return None, None, None, None
        prev = hist.iloc[-2]
        o = float(prev["Open"])
        c = float(prev["Close"])
        ret: float | None = None
        if len(hist) >= 3:
            prev_prev_close = float(hist.iloc[-3]["Close"])
            if prev_prev_close:
                ret = (c - prev_prev_close) / prev_prev_close * 100.0
        elif o:
            ret = (c - o) / o * 100.0
        try:
            session_date = (
                prev.name.date() if hasattr(prev.name, "date") else str(prev.name)[:10]
            )
        except Exception:
            session_date = "unknown"
        logger.debug(
            "prior_day_spy session=%s close=%.4f open=%.4f return_cc=%s",
            session_date,
            c,
            o,
            f"{ret:.4f}" if ret is not None else "n/a",
        )
        return c, o, ret, str(session_date)
    except Exception as exc:
        logger.warning("SPY OHLCV fetch failed: %s", exc)
        return None, None, None, None


def fetch_spx_proxy() -> float | None:
    try:
        import yfinance as yf

        for sym in ("^GSPC", "SPY"):
            hist = yf.Ticker(sym).history(period="2d", interval="1d", timeout=10)
            if hist is not None and not hist.empty:
                px = float(hist["Close"].iloc[-1])
                return px * 10.0 if sym == "SPY" else px
    except Exception as exc:
        logger.warning("SPX proxy fetch failed: %s", exc)
    return None


def pick_expiration(
    rules: LaneRules,
    *,
    today: date,
    dte_pick: str = "min",
    dte_target: int | None = None,
) -> date | None:
    try:
        from xsp_killer.chain_cache import get_spy_expirations

        expirations = get_spy_expirations()
    except Exception as exc:
        logger.warning("SPY options list failed: %s", exc)
        return None
    candidates: list[tuple[int, date]] = []
    for raw in expirations or []:
        try:
            exp = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        if not is_lane_a_contract(
            chain_symbol="XSP",
            option_type="call",
            expiration=exp,
            rules=rules,
            today=today,
        ):
            continue
        candidates.append((compute_dte(exp, today=today), exp))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    mode = (dte_pick or "min").lower()
    if mode == "max":
        return candidates[-1][1]
    if mode == "target" and dte_target is not None:
        return min(candidates, key=lambda x: abs(x[0] - dte_target))[1]
    return candidates[0][1]


def round_xsp_strike(spx_level: float) -> float:
    step = 5.0
    return round(spx_level / step) * step


def pick_cheapest_atm_strike(
    spx_level: float,
    expiration: date,
    *,
    max_steps_from_atm: int = 1,
    premium_scale: float | None = None,
) -> tuple[float, float | None, float | None]:
    """Cheapest near-ATM XSP strike (mentor: closest to money, lowest premium)."""
    atm = round_xsp_strike(spx_level)
    step = 5.0
    candidates = [
        atm + i * step for i in range(-max_steps_from_atm, max_steps_from_atm + 1)
    ]
    best_strike = atm
    best_premium: float | None = None
    best_delta: float | None = None
    best_dist = float("inf")
    for xsp_strike in candidates:
        prem, delta = fetch_spy_call_quote(xsp_strike / 10.0, expiration)
        if prem is None or prem <= 0:
            continue
        dist = abs(xsp_strike - spx_level)
        xsp_prem = scale_spy_premium(prem, premium_scale)
        if dist < best_dist or (
            dist == best_dist and (best_premium is None or xsp_prem < best_premium)
        ):
            best_strike = xsp_strike
            best_premium = xsp_prem
            best_delta = delta
            best_dist = dist
    if best_premium is None:
        return atm, None, None
    return best_strike, best_premium, best_delta


def pick_strike(
    spx_level: float,
    expiration: date,
    *,
    strike_pick: str = "cheapest_near_atm",
    max_steps_from_atm: int = 1,
    premium_scale: float | None = None,
) -> tuple[float, float | None, float | None]:
    """Select strike by mode: cheapest_near_atm | atm_only | otm_one."""
    mode = (strike_pick or "cheapest_near_atm").lower()
    atm = round_xsp_strike(spx_level)
    if mode == "atm_only":
        prem, delta = fetch_spy_call_quote(atm / 10.0, expiration)
        if prem is None or prem <= 0:
            return atm, None, None
        return atm, scale_spy_premium(prem, premium_scale), delta
    if mode == "otm_one":
        otm = atm + 5.0
        prem, delta = fetch_spy_call_quote(otm / 10.0, expiration)
        if prem is None or prem <= 0:
            return otm, None, None
        return otm, scale_spy_premium(prem, premium_scale), delta
    return pick_cheapest_atm_strike(
        spx_level,
        expiration,
        max_steps_from_atm=max_steps_from_atm,
        premium_scale=premium_scale,
    )


def estimate_fallback_premium(
    spy_price: float,
    dte: int,
    *,
    xsp_strike: float | None = None,
    spx_level: float | None = None,
    scale_to_xsp: bool = True,
    premium_scale: float | None = None,
) -> float:
    """Strike-aware paper premium when live quote unavailable (XSP notional by default)."""
    base = max(0.35, spy_price * 0.012)
    scale = max(0.6, min(1.4, (dte / 30.0) ** 0.5))
    prem = base * scale
    if xsp_strike is not None and spx_level is not None and spx_level > 0:
        otm_steps = max(0.0, (xsp_strike - spx_level) / 5.0)
        prem *= max(0.55, 1.0 - 0.08 * otm_steps)
    if scale_to_xsp:
        prem = scale_spy_premium(prem, premium_scale)
    return round(prem, 4)


def build_paper_position(
    *,
    rules: LaneRules,
    entry_rules: EntryRules,
    expiration: date,
    strike: float,
    premium: float,
    entry_mid_premium: float,
    delta: float | None,
    evaluated_at: str,
    spy_return_pct: float | None,
    regime: str | None,
    entry_reason: str,
    spx_at_entry: float | None = None,
) -> dict[str, Any]:
    pos_id = f"paper:{entry_rules.chain_symbol}:{expiration.isoformat()}:{int(strike)}"
    dte_at_entry = compute_dte(expiration)
    return {
        "position_id": pos_id,
        "lane": "A",
        "chain_symbol": entry_rules.chain_symbol,
        "option_type": "call",
        "strike": strike,
        "expiration_date": expiration.isoformat(),
        "quantity": entry_rules.quantity,
        "average_price": round(premium, 4),
        "mark_price": round(entry_mid_premium, 4),
        "entry_mid_premium": round(entry_mid_premium, 4),
        "delta_at_entry": delta,
        "entry_ts": evaluated_at,
        "dte": dte_at_entry,
        "dte_actual": dte_at_entry,
        "dte_at_entry": dte_at_entry,
        "dte_target": entry_rules.dte_target,
        "status": "open",
        "paper_mode": "automated_log_only",
        "entry_reason": entry_reason,
        "logic_version": rules.logic_version,
        "regime_at_entry": regime,
        "prior_day_spy_return_pct": spy_return_pct,
        "quote_source": "SPY_chain_proxy",
        "spx_at_entry": spx_at_entry,
    }


def compute_debit_spread_shadow(
    *,
    long_strike: float,
    long_premium: float,
    expiration: date,
    premium_scale: float | None,
    width_strikes: int = 2,
) -> dict[str, Any] | None:
    """Best-effort debit-spread economics for the entry log (prototype).

    Fetches the short-leg premium from the same SPY chain proxy and models the
    call debit spread vs the naked long call. Never raises — returns None on any
    quote/model failure so it can't disturb the paper entry.
    """
    from xsp_killer.debit_spread import build_debit_spread, select_short_strike

    try:
        if long_premium is None or long_premium <= 0:
            return None
        short_strike = select_short_strike(long_strike, width_strikes=width_strikes)
        short_prem_raw, _ = fetch_spy_call_quote(short_strike / 10.0, expiration)
        if short_prem_raw is None or short_prem_raw <= 0:
            return None
        short_premium = scale_spy_premium(short_prem_raw, premium_scale)
        spread = build_debit_spread(
            long_strike=long_strike,
            long_premium=long_premium,
            short_strike=short_strike,
            short_premium=short_premium,
            premium_scale=premium_scale or 1.0,
        )
        return spread.to_dict() if spread is not None else None
    except Exception:
        return None


def stamp_quote_source(
    position: dict[str, Any],
    source: str,
    *,
    spy_row_strike: float | None = None,
) -> dict[str, Any]:
    position["quote_source"] = source
    if spy_row_strike is not None:
        position["spy_row_strike"] = spy_row_strike
    return position


def append_entry_log(
    decision: EntryDecision,
    *,
    log_path: Path | None = None,
    brief_path: Path | None = None,
) -> None:
    path = log_path if log_path is not None else DEFAULT_PAPER_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": decision.evaluated_at,
        "event": "paper_entry" if decision.entered else "paper_entry_skip",
        "logic_version": decision.logic_version,
        "entered": decision.entered,
        "skip_reason": decision.skip_reason,
        "regime": decision.regime,
        "regime_frac": decision.regime_frac,
        "regime_gate": decision.regime_gate,
        "prior_day_spy_return_pct": decision.prior_day_spy_return_pct,
        "ta_snapshot": decision.ta_snapshot,
        "bb_entry_ok": decision.bb_entry_ok,
        "vol_shadow": decision.vol_shadow,
        "premium_scale_used": decision.premium_scale_used,
        "risk_gate": decision.risk_gate,
        "position": decision.position,
        "debit_spread_shadow": decision.debit_spread_shadow,
        "errors": decision.errors,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def write_entry_brief(decision: EntryDecision, out_path: Path | None = None) -> Path:
    path = out_path or DEFAULT_OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def _bucket_skip_reason(reason: str | None) -> str:
    if not reason:
        return "unknown"
    if reason.startswith("regime "):
        return "regime_gate"
    if reason.startswith("outside"):
        return "out_of_window"
    if reason.startswith("max open"):
        return "max_positions"
    if reason.startswith("already entered"):
        return "already_entered_today"
    if reason.startswith("prior-day"):
        return "prior_day_filter"
    if reason.startswith("paper_entry.disabled"):
        return "disabled"
    if reason.startswith("XSP_LANE_A"):
        return "env_disabled"
    if reason.lower().startswith("conductor_shadow"):
        return "conductor_shadow"
    if reason.lower().startswith("conductor"):
        return "conductor_shadow"
    if "daily paper loss cap" in reason.lower():
        return "risk_gate"
    if "consecutive paper losses" in reason.lower():
        return "risk_gate"
    if "risk" in reason.lower():
        return "risk_gate"
    if "stale" in reason.lower() or reason.startswith("TA"):
        return "ta_gate"
    return reason.split(":")[0][:48]


def _epoch_at(state: dict[str, Any]) -> str | None:
    raw = state.get("pnl_epoch_at") or state.get("soak_reset_at")
    return str(raw) if raw else None


def entry_logs_for_epoch(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Entry log rows on or after the current soak / PnL epoch boundary."""
    logs = [row for row in (state.get("entry_log") or []) if isinstance(row, dict)]
    epoch = _epoch_at(state)
    if not epoch:
        return logs
    return [row for row in logs if str(row.get("evaluated_at") or "") >= epoch]


def et_session_date(raw: Any) -> str | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        ts = raw
    else:
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(ET).date().isoformat()


def is_et_trading_session(session_date: date) -> bool:
    if session_date.weekday() >= 5:
        return False
    if session_date.year == 2026 and session_date in NYSE_2026_HOLIDAYS:
        return False
    return True


ENTRY_EVAL_WINDOW_END_ET = time(19, 55)


def scoreboard_entry_stale(
    latest_entry_eval: datetime | None,
    *,
    now: datetime | None = None,
    window_end_et: time = ENTRY_EVAL_WINDOW_END_ET,
) -> bool:
    """Stale only when a trading session's entry window passed without a newer eval."""
    if latest_entry_eval is None:
        return True
    reference = (now or datetime.now(timezone.utc)).astimezone(ET)
    last_eval_et = latest_entry_eval.astimezone(ET)
    last_session_date = last_eval_et.date()

    d = last_session_date + timedelta(days=1)
    while d <= reference.date():
        if is_et_trading_session(d):
            window_end = datetime.combine(d, window_end_et, tzinfo=ET)
            if reference >= window_end and last_eval_et < window_end:
                return True
        d += timedelta(days=1)
    return False


def unique_et_sessions(entry_logs: list[dict[str, Any]]) -> list[str]:
    sessions: set[str] = set()
    for row in entry_logs:
        session = et_session_date(row.get("evaluated_at"))
        if not session:
            continue
        try:
            if not is_et_trading_session(date.fromisoformat(session)):
                continue
        except ValueError:
            continue
        sessions.add(session)
    return sorted(sessions)


def _session_rows_by_et_date(
    entry_logs: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in entry_logs:
        session = et_session_date(row.get("evaluated_at"))
        if not session:
            continue
        try:
            if not is_et_trading_session(date.fromisoformat(session)):
                continue
        except ValueError:
            continue
        grouped.setdefault(session, []).append(row)
    return [(session, grouped[session]) for session in sorted(grouped)]


def _representative_session_row(session_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(session_rows, key=lambda row: str(row.get("evaluated_at") or ""))
    entered = next((row for row in ordered if row.get("entered")), None)
    return entered or ordered[-1]


def summarize_entry_telemetry_from_logs(
    entry_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive skip/regime tallies from entry_log (matches scoreboard epoch filtering)."""
    skip_reason_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    last_updated_at: str | None = None
    entered_sessions = 0
    evals_total = len(entry_logs)
    for row in entry_logs:
        evaluated_at = row.get("evaluated_at")
        if evaluated_at and (
            last_updated_at is None or str(evaluated_at) > last_updated_at
        ):
            last_updated_at = str(evaluated_at)
    for _, session_rows in _session_rows_by_et_date(entry_logs):
        row = _representative_session_row(session_rows)
        regime = row.get("regime")
        if regime:
            regime_counts[str(regime)] = regime_counts.get(str(regime), 0) + 1
        if row.get("entered"):
            bucket = "entered"
            entered_sessions += 1
        else:
            bucket = _bucket_skip_reason(row.get("skip_reason"))
        skip_reason_counts[bucket] = skip_reason_counts.get(bucket, 0) + 1
    return {
        "last_updated_at": last_updated_at,
        "skip_reason_counts": skip_reason_counts,
        "regime_counts": regime_counts,
        "evals_total": evals_total,
        "sessions_evaluated": len(unique_et_sessions(entry_logs)),
        "entered_sessions": entered_sessions,
    }


def _sync_entry_telemetry(state: dict[str, Any]) -> dict[str, Any]:
    tel = summarize_entry_telemetry_from_logs(entry_logs_for_epoch(state))
    state["entry_telemetry"] = tel
    return tel


def _update_entry_telemetry(state: dict[str, Any], decision: EntryDecision) -> None:
    _sync_entry_telemetry(state)


def _write_entry_telemetry_brief(
    state: dict[str, Any], out_path: Path | None = None
) -> None:
    path = out_path or DEFAULT_TELEMETRY_BRIEF
    tel = _sync_entry_telemetry(state)
    payload = {
        "pnl_epoch_at": _epoch_at(state),
        "updated_at": tel.get("last_updated_at"),
        "evals_total": tel.get("evals_total", 0),
        "sessions_evaluated": tel.get("sessions_evaluated", 0),
        "entered_sessions": tel.get("entered_sessions", 0),
        "skip_reason_counts": tel.get("skip_reason_counts") or {},
        "regime_counts": tel.get("regime_counts") or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def entry_gates_ok(
    now: datetime,
    *,
    entry_rules: EntryRules,
    ta_rules: TaRules,
    ta: TaSignal,
    force: bool,
    intraday: bool,
) -> tuple[bool, str | None]:
    """Combine close window, RTH, and BB bounce gates per rules mode."""
    if not force and not in_rth(now) and not in_entry_window(now, entry_rules):
        return False, "outside RTH and close window"

    in_win = in_entry_window(now, entry_rules) or force
    mode = ta_rules.entry_mode

    if mode == "close_window_only":
        if not in_win:
            return False, "outside entry window 15:45–16:00 ET"
        return True, None

    if mode == "bb_bounce":
        if not ta.entry_ok:
            return False, f"no BB bounce: {ta.detail}"
        if not force and not in_rth(now):
            return False, "outside RTH"
        return True, None

    # close_window_and_bb
    if intraday and ta_rules.intraday_entry_enabled and ta.entry_ok and in_rth(now):
        return True, None
    if not in_win:
        return False, "outside entry window 15:45–16:00 ET"
    if not ta.entry_ok:
        return False, f"no BB bounce at close window: {ta.detail}"
    return True, None


def _resolve_entry_reason(
    *,
    now: datetime,
    entry_rules: EntryRules,
    ta_rules: TaRules,
    ta_signal: TaSignal,
    force: bool,
    intraday: bool,
) -> str:
    in_win = in_entry_window(now, entry_rules) or force
    if ta_rules.entry_mode == "bb_bounce":
        return "bb_bounce_long_call"
    if ta_rules.entry_mode == "close_window_only":
        return "close_window_long_call"
    if (
        intraday
        and ta_rules.intraday_entry_enabled
        and ta_signal.entry_ok
        and in_rth(now)
    ):
        return "bb_bounce_long_call"
    if in_win:
        return "close_window_long_call"
    return "bb_bounce_long_call"


def run_paper_entry(
    *,
    rules_path: Path | None = None,
    state_path: Path | None = None,
    log_path: Path | None = None,
    now_et: datetime | None = None,
    force: bool = False,
    intraday: bool = False,
    publish_intel: bool = True,
    ta_signal: TaSignal | None = None,
    brief_path: Path | None = None,
) -> EntryDecision:
    lane_rules = LaneRules.from_yaml(rules_path or DEFAULT_RULES)
    entry_rules = EntryRules.from_yaml(rules_path or DEFAULT_RULES)
    ta_rules = TaRules.from_yaml(rules_path or DEFAULT_RULES)
    state = load_state(state_path or DEFAULT_STATE)
    now = now_et or datetime.now(ET)
    evaluated_at = datetime.now(timezone.utc).isoformat()

    if ta_signal is None:
        ta_signal = evaluate_ta_signals(ta_rules, now_et=now)

    regime, regime_ok, yellow_frac, _ = read_regime_detail()
    from xsp_killer.vol_monitor import evaluate_shadow_vol_gate, session_premium_scale

    rules_file = rules_path or DEFAULT_RULES
    vol_shadow = evaluate_shadow_vol_gate(rules_path=rules_file).to_dict()
    base_scale = load_premium_scale(rules_file)
    session_scale = session_premium_scale(
        base_scale=base_scale,
        vol_shadow=vol_shadow,
        rules_path=rules_file,
    )
    decision = EntryDecision(
        entered=False,
        evaluated_at=evaluated_at,
        logic_version=lane_rules.logic_version,
        in_window=in_entry_window(now, entry_rules),
        regime=regime,
        regime_ok=regime_ok,
        regime_frac=yellow_frac,
        regime_gate=lane_rules.regime_gate,
        prior_day_spy_return_pct=None,
        prior_day_ok=True,
        prior_day_spy_session=None,
        ta_snapshot=ta_signal.to_dict(),
        bb_entry_ok=ta_signal.entry_ok,
        vol_shadow=vol_shadow,
        premium_scale_used=session_scale,
    )

    if not paper_entry_enabled():
        decision.skip_reason = "XSP_LANE_A_PAPER_ENTRY disabled"
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    if not entry_rules.enabled:
        decision.skip_reason = "paper_entry.disabled in rules"
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    gates_ok, gate_reason = entry_gates_ok(
        now,
        entry_rules=entry_rules,
        ta_rules=ta_rules,
        ta=ta_signal,
        force=force,
        intraday=intraday,
    )
    if not gates_ok:
        decision.skip_reason = gate_reason
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    open_pos = open_paper_positions(state)
    if len(open_pos) >= entry_rules.max_open_positions:
        decision.skip_reason = (
            f"max open paper positions ({entry_rules.max_open_positions})"
        )
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    if not force and already_entered_today(state, now.date()):
        decision.skip_reason = "already entered or attempted today"
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    regime_gate_ok, regime_gate_reason = regime_gate_allows(
        regime_gate=lane_rules.regime_gate,
        regime=regime,
        regime_ok=regime_ok,
        yellow_frac=yellow_frac,
        ta_entry_ok=ta_signal.entry_ok,
        yellow_frac_min=lane_rules.regime_yellow_frac_min,
        yellow_require_bounce=lane_rules.regime_yellow_require_bounce,
    )
    if not regime_gate_ok:
        decision.skip_reason = regime_gate_reason
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    # Falling-knife overlay: even a confirmed bounce is refused when VIX is in a
    # confirmed spike (no-op unless veto_entry_on_vix_spike is enabled in config).
    from xsp_killer.vol_monitor import vix_spike_entry_veto

    vix_veto_reason = vix_spike_entry_veto(vol_shadow, rules_path=rules_file)
    if vix_veto_reason:
        decision.skip_reason = vix_veto_reason
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    _, _, spy_ret, spy_session = fetch_spy_ohlcv()
    decision.prior_day_spy_return_pct = spy_ret
    decision.prior_day_spy_session = spy_session
    if entry_rules.prior_day_spy_positive:
        decision.prior_day_ok = spy_ret is not None and spy_ret > 0
        if not decision.prior_day_ok:
            decision.skip_reason = "prior-day SPY not positive"
            _finalize_entry(
                state,
                state_path,
                decision,
                publish_intel,
                log_path=log_path,
                brief_path=brief_path,
            )
            return decision

    ok_risk, risk_reason = entry_allowed_by_risk(
        state, rules_path=rules_file, premium_scale=session_scale
    )
    decision.risk_gate = risk_gate_snapshot(
        state, rules_path=rules_file, premium_scale=session_scale
    )
    if not ok_risk:
        decision.skip_reason = risk_reason
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    spx = fetch_spx_proxy()
    if spx is None:
        decision.skip_reason = "SPX proxy unavailable"
        decision.errors.append("spx_proxy_failed")
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    expiration = pick_expiration(
        lane_rules,
        today=now.date(),
        dte_pick=entry_rules.dte_pick,
        dte_target=entry_rules.dte_target,
    )
    if expiration is None:
        decision.skip_reason = "no eligible expiration in DTE window"
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    strike, premium, delta = pick_strike(
        spx,
        expiration,
        strike_pick=entry_rules.strike_pick,
        max_steps_from_atm=entry_rules.strike_max_steps_from_atm,
        premium_scale=session_scale,
    )
    quote_source = f"SPY_chain_proxy_{entry_rules.strike_pick}"
    from xsp_killer.paper_economics import PaperEconomics, entry_fill_premium

    econ = PaperEconomics.from_yaml(rules_path or DEFAULT_RULES)
    if premium is None or premium <= 0:
        spy_px = spx / 10.0
        dte_actual = compute_dte(expiration, today=now.date())
        entry_mid = estimate_fallback_premium(
            spy_px,
            dte_actual,
            xsp_strike=strike,
            spx_level=spx,
            premium_scale=session_scale,
        )
        quote_source = "fallback_estimate_strike_aware"
        decision.errors.append("quote_fallback_used")
    else:
        entry_mid = premium
    fill_premium = entry_fill_premium(entry_mid, econ)

    position = build_paper_position(
        rules=lane_rules,
        entry_rules=entry_rules,
        expiration=expiration,
        strike=strike,
        premium=fill_premium,
        entry_mid_premium=entry_mid,
        delta=delta,
        evaluated_at=evaluated_at,
        spy_return_pct=spy_ret,
        regime=regime,
        entry_reason=_resolve_entry_reason(
            now=now,
            entry_rules=entry_rules,
            ta_rules=ta_rules,
            ta_signal=ta_signal,
            force=force,
            intraday=intraday,
        ),
        spx_at_entry=spx,
    )
    spy_row = None
    try:
        q = fetch_spy_call_mark(xsp_strike_to_spy_chain_strike(strike), expiration)
        spy_row = q.spy_row_strike
    except Exception:
        spy_row = None
    stamp_quote_source(position, quote_source, spy_row_strike=spy_row)
    dte_at_entry = compute_dte(expiration, today=now.date())
    position["dte"] = dte_at_entry
    position["dte_actual"] = dte_at_entry
    position["dte_at_entry"] = dte_at_entry
    position["dte_pick"] = entry_rules.dte_pick
    position["dte_target"] = entry_rules.dte_target
    position["expiration_date"] = expiration.isoformat()
    position["entry_ta_detail"] = ta_signal.detail
    if entry_rules.debit_spread_shadow:
        decision.debit_spread_shadow = compute_debit_spread_shadow(
            long_strike=strike,
            long_premium=entry_mid,
            expiration=expiration,
            premium_scale=session_scale,
            width_strikes=entry_rules.debit_spread_width_strikes,
        )
        if decision.debit_spread_shadow is not None:
            position["debit_spread_shadow"] = decision.debit_spread_shadow
    paper_positions = state.setdefault("paper_positions", {})
    paper_positions[position["position_id"]] = position

    ok_shadow, shadow_reason = shadow_review_entry(
        regime=regime,
        prior_day_spy_return_pct=spy_ret,
        ta_detail=ta_signal.detail,
        position=position,
    )
    if not ok_shadow:
        paper_positions.pop(position["position_id"], None)
        decision.skip_reason = shadow_reason
        _finalize_entry(
            state,
            state_path,
            decision,
            publish_intel,
            log_path=log_path,
            brief_path=brief_path,
        )
        return decision

    decision.entered = True
    decision.position = position
    decision.skip_reason = None

    _maybe_place_live_entry(
        decision,
        lane_rules=lane_rules,
        entry_rules=entry_rules,
        today=now.date(),
    )

    _finalize_entry(
        state,
        state_path,
        decision,
        publish_intel,
        log_path=log_path,
        brief_path=brief_path,
    )
    return decision


_LIVE_ENTRY_REF_NAMESPACE = uuid.UUID("7d5a6c2e-3b41-4e0a-9c2d-000000000002")


def _live_entry_ref_id(instrument_id: str, day: str) -> str:
    """Deterministic idempotency key so retries can't duplicate the day's entry."""
    return str(uuid.uuid5(_LIVE_ENTRY_REF_NAMESPACE, f"{instrument_id}:{day}"))


def _live_entry_safety_config(path: Path = DEFAULT_RULES) -> dict[str, float | bool]:
    cfg: dict[str, float | bool] = {
        "max_loss_usd": 150.0,
        "max_debit_usd": 2500.0,
        "max_cost_frac": 0.5,
        "veto_red": True,
        "reviewer_max_spread_frac": 0.25,
        "reviewer_max_contracts": 5,
    }
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        live = data.get("live") or {}
        cfg["max_loss_usd"] = float(live.get("max_loss_usd", cfg["max_loss_usd"]))
        cfg["max_debit_usd"] = float(live.get("max_debit_usd", cfg["max_debit_usd"]))
        cfg["max_cost_frac"] = float(live.get("max_cost_frac", cfg["max_cost_frac"]))
        cfg["veto_red"] = bool(live.get("veto_red", cfg["veto_red"]))
        cfg["reviewer_max_spread_frac"] = float(
            live.get("reviewer_max_spread_frac", cfg["reviewer_max_spread_frac"])
        )
        cfg["reviewer_max_contracts"] = int(
            live.get("reviewer_max_contracts", cfg["reviewer_max_contracts"])
        )
    except Exception:
        pass
    return cfg


def _live_variant_allowed(current_variant: str, allowlist_variant: str | None) -> bool:
    """Exact match only — no suffix matching (a stray suffix must never authorize live)."""
    allowed = (allowlist_variant or "").strip()
    current = (current_variant or "").strip()
    if not allowed or not current:
        return False
    return current == allowed


def _maybe_place_live_entry(
    decision: "EntryDecision",
    *,
    lane_rules: "LaneRules",
    entry_rules: "EntryRules",
    today: date,
) -> None:
    """Place a real buy-to-open when live entries are authorized; else no-op.

    Fail-safe: skips (does not raise) when MCP is off, live entries are
    disabled, the kill switch is engaged, or account buying power is below the
    contract cost. Records the outcome on ``decision.live_order``. The paper
    position is unaffected (it continues as a shadow record).
    """
    from xsp_killer.conductor_reviewer import live_reviewer_enabled, review_live_order
    from xsp_killer.robinhood_mcp import (
        RobinhoodMCPAdapter,
        kill_switch_engaged,
        live_entries_enabled,
        rh_mcp_enabled,
    )

    if not rh_mcp_enabled():
        return
    if not live_entries_enabled():
        decision.live_order = {"placed": False, "reason": "live entries disabled"}
        return
    if kill_switch_engaged():
        decision.live_order = {"placed": False, "reason": "kill switch engaged"}
        return
    current_variant = str(
        getattr(lane_rules, "logic_version", None) or decision.logic_version or ""
    )
    from xsp_killer.live_gates import human_variant_review_allows

    ok_review, review_reason = human_variant_review_allows(current_variant)
    if not ok_review:
        decision.live_order = {"placed": False, "reason": review_reason}
        return
    live_cfg = _live_entry_safety_config()
    if bool(live_cfg["veto_red"]):
        try:
            regime_detail = read_regime_detail()
            live_regime = (
                regime_detail[0]
                if isinstance(regime_detail, (tuple, list))
                else regime_detail
            )
        except Exception as exc:
            decision.live_order = {
                "placed": False,
                "reason": f"live skipped: regime unavailable ({exc})",
            }
            return
        if str(live_regime or "").strip().upper() == "RED":
            decision.live_order = {
                "placed": False,
                "reason": "live skipped: RED regime (shadow only)",
            }
            return
    try:
        adapter = RobinhoodMCPAdapter()
        contract = adapter.select_entry_contract(
            underlying=entry_rules.chain_symbol or "XSP",
            option_type="call",
            dte_min=lane_rules.dte_min,
            dte_max=lane_rules.dte_max,
            dte_pick=entry_rules.dte_pick,
            dte_target=getattr(entry_rules, "dte_target", None),
            atm_steps=entry_rules.strike_max_steps_from_atm,
            strike_pick=entry_rules.strike_pick,
            today=today,
        )
        qty = max(1, int(round(entry_rules.quantity or 1)))
        limit = float(contract["ask"])
        cost = limit * 100.0 * qty
        buying_power = adapter.get_buying_power()
        stop_loss_pct = float(getattr(lane_rules, "stop_loss_pct", 0.20))
        est_max_loss = cost * stop_loss_pct
        if cost > buying_power:
            decision.live_order = {
                "placed": False,
                "reason": (
                    f"insufficient buying power ${buying_power:,.0f} "
                    f"< est cost ${cost:,.0f}"
                ),
                "contract": contract,
                "buying_power": buying_power,
            }
            return
        max_loss_usd = float(live_cfg["max_loss_usd"])
        max_debit_usd = float(live_cfg["max_debit_usd"])
        max_cost_frac = float(live_cfg["max_cost_frac"])
        if est_max_loss > max_loss_usd:
            decision.live_order = {
                "placed": False,
                "reason": (
                    f"planned stop loss ${est_max_loss:,.0f} "
                    f"> live cap ${max_loss_usd:,.0f}"
                ),
                "contract": contract,
                "buying_power": buying_power,
                "cost_estimate": round(cost, 2),
                "est_max_loss": round(est_max_loss, 2),
                "max_loss_usd": max_loss_usd,
            }
            return
        # Full-debit gate: the entire premium is at risk if the stop never fills
        # (gap / halt / assignment). Cap the actual dollars committed, not just
        # the modeled stop-loss estimate.
        if cost > max_debit_usd:
            decision.live_order = {
                "placed": False,
                "reason": (
                    f"max debit ${cost:,.0f} > live cap ${max_debit_usd:,.0f}"
                ),
                "contract": contract,
                "buying_power": buying_power,
                "cost_estimate": round(cost, 2),
                "est_max_loss": round(est_max_loss, 2),
                "max_debit_usd": max_debit_usd,
            }
            return
        if cost > max_cost_frac * buying_power:
            decision.live_order = {
                "placed": False,
                "reason": (
                    f"est cost ${cost:,.0f} exceeds {max_cost_frac:.0%} of buying power"
                ),
                "contract": contract,
                "buying_power": buying_power,
                "cost_estimate": round(cost, 2),
                "max_cost_usd": round(max_cost_frac * buying_power, 2),
                "max_cost_frac": max_cost_frac,
            }
            return
        # Deterministic pre-trade second opinion on the concrete order (spread,
        # price sanity, cost/loss re-derivation, DTE band). Fail-closed.
        review = None
        if live_reviewer_enabled():
            review = review_live_order(
                contract=contract,
                limit_price=limit,
                quantity=qty,
                cost=cost,
                est_max_loss=est_max_loss,
                buying_power=buying_power,
                max_loss_usd=max_loss_usd,
                max_cost_frac=max_cost_frac,
                dte_min=lane_rules.dte_min,
                dte_max=lane_rules.dte_max,
                max_spread_frac=float(live_cfg["reviewer_max_spread_frac"]),
                max_contracts=int(live_cfg["reviewer_max_contracts"]),
            )
            if not review.approved:
                decision.live_order = {
                    "placed": False,
                    "reason": review.reason,
                    "contract": contract,
                    "buying_power": buying_power,
                    "cost_estimate": round(cost, 2),
                    "reviewer": review.to_dict(),
                }
                return
        ref_id = _live_entry_ref_id(contract["instrument_id"], today.isoformat())
        result = adapter.buy_to_open(
            instrument_id=contract["instrument_id"],
            limit_price=limit,
            quantity=qty,
            ref_id=ref_id,
        )
        decision.live_order = {
            "placed": True,
            "contract": contract,
            "quantity": qty,
            "limit_price": round(limit, 2),
            "cost_estimate": round(cost, 2),
            "est_max_loss": round(est_max_loss, 2),
            "buying_power": buying_power,
            # Live orders price off real RH quotes — true 1x dollars, never the
            # paper SPY->XSP premium scale (which is a shadow-book convenience).
            "premium_scale": 1.0,
            "reviewer": review.to_dict() if review is not None else None,
            "result": result,
        }
    except Exception as exc:
        decision.live_order = {"placed": False, "error": str(exc)}
        decision.errors.append(f"live_entry_error: {exc}")


def close_open_paper_positions(
    state: dict[str, Any],
    *,
    state_path: Path | None = None,
    reason: str = "manual",
    position_id: str | None = None,
    evaluated_at: str | None = None,
) -> list[dict[str, Any]]:
    """Close open paper positions (operator cleanup or simulated exit)."""
    ts = evaluated_at or datetime.now(timezone.utc).isoformat()
    paper = state.setdefault("paper_positions", {})
    if not isinstance(paper, dict):
        return []
    closed: list[dict[str, Any]] = []
    for pid, raw in list(paper.items()):
        if not isinstance(raw, dict) or raw.get("status", "open") != "open":
            continue
        if position_id and pid != position_id:
            continue
        avg = float(raw.get("average_price") or 0)
        mark = float(raw.get("mark_price") or avg)
        qty = float(raw.get("quantity") or 1)
        pnl_per_contract = (mark - avg) * 100.0 if avg > 0 else 0.0
        pnl_usd = pnl_per_contract * qty
        row = dict(raw)
        row["status"] = "closed"
        row["exit_ts"] = ts
        row["exit_reason"] = reason
        row["exit_pnl_usd"] = round(pnl_usd, 2)
        row["exit_pnl_per_contract"] = round(pnl_per_contract, 2)
        paper[pid] = row
        closed.append(row)
        events = list(state.get("paper_events") or [])
        events.append(
            {
                "evaluated_at": ts,
                "position_id": pid,
                "exit_reason": reason,
                "paper_pnl_usd": row["exit_pnl_usd"],
                "paper_pnl_per_contract": row["exit_pnl_per_contract"],
                "logic_version": raw.get("logic_version", "xsp_lane_a_v1"),
                "paper_mode": "operator_close",
                "entry_ts": raw.get("entry_ts"),
            }
        )
        state["paper_events"] = events[-500:]
    if closed:
        save_state(state_path or DEFAULT_STATE, state)
        path = DEFAULT_PAPER_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for row in closed:
                fh.write(
                    json.dumps(
                        {
                            "ts": ts,
                            "event": "paper_exit",
                            "position_id": row.get("position_id"),
                            "exit_reason": reason,
                            "paper_pnl_usd": row.get("exit_pnl_usd"),
                            "logic_version": row.get("logic_version"),
                        }
                    )
                    + "\n"
                )
    return closed


def _expired_paper_full_debit_pnl(
    raw: dict[str, Any],
    *,
    rules_path: Path | None = None,
) -> tuple[float | None, float | None]:
    """Book expired long call as exit mid 0.0 (full debit loss × quantity)."""
    try:
        qty = float(raw.get("quantity") or 1.0)
    except (TypeError, ValueError):
        qty = 1.0
    if qty <= 0:
        qty = 1.0

    avg_raw = raw.get("average_price")
    entry_mid_raw = raw.get("entry_mid_premium")
    try:
        avg = float(avg_raw) if avg_raw is not None else None
    except (TypeError, ValueError):
        avg = None
    try:
        entry_mid = float(entry_mid_raw) if entry_mid_raw is not None else None
    except (TypeError, ValueError):
        entry_mid = None

    pnl_per: float | None = None
    try:
        from xsp_killer.paper_economics import (
            PaperEconomics,
            pnl_from_entry_fill,
            pnl_per_contract,
        )

        econ = PaperEconomics.from_yaml(rules_path or DEFAULT_RULES)
        if (
            avg is not None
            and entry_mid is not None
            and abs(avg - entry_mid) > 1e-6
            and avg > 0
        ):
            # average_price already includes entry fill economics.
            pnl_per = pnl_from_entry_fill(
                entry_fill=avg, exit_mid=0.0, econ=econ
            )
        elif entry_mid is not None and entry_mid > 0:
            pnl_per = pnl_per_contract(
                entry_mid=entry_mid, exit_mid=0.0, econ=econ
            )
        elif avg is not None and avg > 0:
            pnl_per = pnl_from_entry_fill(
                entry_fill=avg, exit_mid=0.0, econ=econ
            )
    except Exception as exc:
        logger.warning("expired paper economics pnl failed: %s", exc)

    if pnl_per is None:
        # Fallback: raw debit × 100 when entry fill/mid is missing economics path.
        debit = avg if avg is not None and avg > 0 else entry_mid
        if debit is None or debit <= 0:
            return None, None
        pnl_per = round(-debit * 100.0, 2)

    return pnl_per, round(pnl_per * qty, 2)


def reap_expired_paper_positions(
    state: dict[str, Any],
    *,
    state_path: Path | None = None,
    evaluated_at: str | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Close stale paper positions whose expiration is before the current ET date."""
    ts = evaluated_at or datetime.now(timezone.utc).isoformat()
    ref_day = today or datetime.now(ET).date()
    paper = state.setdefault("paper_positions", {})
    if not isinstance(paper, dict):
        return []
    closed: list[dict[str, Any]] = []
    events = list(state.get("paper_events") or [])
    seen = {
        (
            e.get("position_id"),
            e.get("exit_reason"),
            (e.get("evaluated_at") or "")[:10],
        )
        for e in events
        if isinstance(e, dict)
    }
    for pid, raw in list(paper.items()):
        if not isinstance(raw, dict) or raw.get("status", "open") != "open":
            continue
        exp = parse_expiration(str(raw.get("expiration_date") or ""))
        if exp is None or exp >= ref_day:
            continue
        row = dict(raw)
        row["status"] = "closed"
        row["exit_ts"] = ts
        row["exit_reason"] = "expired"
        pnl_per, pnl_usd = _expired_paper_full_debit_pnl(raw)
        row["exit_pnl_usd"] = pnl_usd
        row["exit_pnl_per_contract"] = pnl_per
        paper[pid] = row
        closed.append(row)
        evt_key = (pid, "expired", ts[:10])
        if evt_key not in seen:
            events.append(
                {
                    "evaluated_at": ts,
                    "position_id": pid,
                    "exit_reason": "expired",
                    "paper_pnl_usd": pnl_usd,
                    "paper_pnl_per_contract": pnl_per,
                    "logic_version": raw.get("logic_version", "xsp_lane_a_v1"),
                    "paper_mode": "automated_paper_close",
                    "entry_ts": raw.get("entry_ts"),
                    "expiration_date": raw.get("expiration_date"),
                }
            )
            seen.add(evt_key)
    if closed:
        state["paper_events"] = events[-500:]
        save_state(state_path or DEFAULT_STATE, state)
    return closed


def _finalize_entry(
    state: dict[str, Any],
    state_path: Path | None,
    decision: EntryDecision,
    publish_intel: bool,
    log_path: Path | None = None,
    brief_path: Path | None = None,
) -> None:
    log = list(state.get("entry_log") or [])
    log.append(
        {
            "evaluated_at": decision.evaluated_at,
            "entered": decision.entered,
            "skip_reason": decision.skip_reason,
            "position_id": (decision.position or {}).get("position_id"),
            "regime": decision.regime,
            "regime_frac": decision.regime_frac,
            "regime_gate": decision.regime_gate,
            "bb_entry_ok": decision.bb_entry_ok,
            "vol_shadow": decision.vol_shadow,
            "vol_shadow_would_block": (decision.vol_shadow or {}).get(
                "shadow_would_block"
            ),
            "spy_rv_annualized": (decision.vol_shadow or {}).get("spy_rv_annualized"),
            "vol_shadow_reason": (decision.vol_shadow or {}).get("reason"),
            "prior_day_spy_return_pct": decision.prior_day_spy_return_pct,
            "prior_day_spy_session": decision.prior_day_spy_session,
            "risk_gate": decision.risk_gate,
        }
    )
    state["entry_log"] = log[-200:]
    _update_entry_telemetry(state, decision)
    save_state(state_path or DEFAULT_STATE, state)
    append_entry_log(decision, log_path=log_path)
    if brief_path is not False:
        write_entry_brief(decision, out_path=brief_path)
        if brief_path is None:
            _write_entry_telemetry_brief(state)

    if publish_intel:
        try:
            from xsp_killer.intel import IntelPublisher

            IntelPublisher.publish(
                "intel:xsp_lane_a_entry",
                decision.to_dict(),
                source_system="xsp_lane_a_entry",
                confidence=1.0 if decision.entered else 0.5,
                ttl=86400,
            )
        except Exception as exc:
            decision.errors.append(f"intel publish failed: {exc}")
