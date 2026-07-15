"""XSP Lane A overnight swing monitor — Phase 0 alerts only (K116).

Polls Robinhood open SPX/XSP calls, evaluates exit rules, emits alerts.
No auto-close until Phase 1 gates pass.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml

from xsp_killer.fs_lock import flock_un, open_ex_lock
from xsp_killer.paper_economics import load_premium_scale
from xsp_killer.rh_broker import (
    fetch_robinhood_option_positions,
    rh_poll_enabled,  # noqa: F401 — re-exported for tests and lane_b
    rh_read_enabled,
)
from xsp_killer.robinhood_mcp import (
    RhMcpError,
    RobinhoodMCPAdapter,
    kill_switch_engaged,
    live_exits_enabled,
    rh_mcp_enabled,
)

logger = logging.getLogger("xsp_killer.xsp_lane_a")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = ROOT / "config" / "lane_a_rules.yaml"
DEFAULT_STATE = ROOT / "briefs" / "xsp-lane-a-state.json"
DEFAULT_OUT = ROOT / "briefs" / "xsp-lane-a-monitor-latest.json"
DEFAULT_PAPER_LOG = ROOT / "logs" / "xsp_lane_a_paper.jsonl"
DEFAULT_PAPER_BRIEF = ROOT / "briefs" / "xsp-lane-a-paper-pnl-latest.json"

ET = ZoneInfo("America/New_York")
ExitReason = Literal[
    "stop_loss",
    "take_profit",
    "upper_bb_rejection",
    "time_stop",
    "manual",
]


@dataclass
class LaneRules:
    lane: str
    dte_min: int
    dte_max: int
    exclude_expiry_month: tuple[str, ...]
    chain_symbols: tuple[str, ...]
    stop_loss_pct: float
    take_profit_pct: float
    sell_eval_start_et: time
    sell_deadline_et: time
    no_sell_start_et: time
    no_sell_end_et: time
    require_upper_bb_for_take_profit: bool
    logic_version: str
    regime_gate: str = "GREEN"
    regime_yellow_frac_min: float = 0.75
    regime_yellow_require_bounce: bool = True
    swing_hold: bool = False
    max_hold_dte: int = 0

    @classmethod
    def from_yaml(cls, path: Path) -> LaneRules:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entry = data.get("entry") or {}
        exit_cfg = data.get("exit") or {}
        logging_cfg = data.get("logging") or {}

        def _parse_time(s: str) -> time:
            h, m = s.split(":")
            return time(int(h), int(m))

        return cls(
            lane=str(data.get("lane", "A")),
            dte_min=int(entry.get("dte_min", 14)),
            dte_max=int(entry.get("dte_max", 60)),
            exclude_expiry_month=tuple(
                str(x) for x in entry.get("exclude_expiry_month") or []
            ),
            chain_symbols=tuple(
                str(x).upper() for x in entry.get("chain_symbols") or ["SPX", "XSP"]
            ),
            stop_loss_pct=float(exit_cfg.get("stop_loss_pct", 0.20)),
            take_profit_pct=float(exit_cfg.get("take_profit_pct", 0.20)),
            sell_eval_start_et=_parse_time(
                str(exit_cfg.get("sell_eval_start_et", "08:00"))
            ),
            sell_deadline_et=_parse_time(
                str(exit_cfg.get("sell_deadline_et", "09:30"))
            ),
            no_sell_start_et=_parse_time(
                str(exit_cfg.get("no_sell_start_et", "00:00"))
            ),
            no_sell_end_et=_parse_time(str(exit_cfg.get("no_sell_end_et", "08:00"))),
            require_upper_bb_for_take_profit=bool(
                exit_cfg.get("require_upper_bb_for_take_profit", True)
            ),
            logic_version=str(logging_cfg.get("logic_version", "xsp_lane_a_v2")),
            regime_gate=str(entry.get("regime_gate", "GREEN")),
            regime_yellow_frac_min=float(entry.get("regime_yellow_frac_min", 0.75)),
            regime_yellow_require_bounce=bool(
                entry.get("regime_yellow_require_bounce", True)
            ),
            swing_hold=bool(exit_cfg.get("swing_hold", False)),
            max_hold_dte=int(exit_cfg.get("max_hold_dte", 0)),
        )


@dataclass
class LaneAPosition:
    position_id: str
    chain_symbol: str
    option_type: str
    strike: float
    expiration_date: date
    quantity: float
    average_price: float
    mark_price: float | None
    dte: int
    lane: str = "A"
    entry_ts: str | None = None
    delta_at_entry: float | None = None
    entry_mid_premium: float | None = None
    mark_quote_stale: bool = False
    pnl_usd: float | None = None
    pnl_per_contract: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["expiration_date"] = self.expiration_date.isoformat()
        return d


@dataclass
class ExitAlert:
    position_id: str
    exit_reason: str
    message: str
    pnl_usd: float | None
    pnl_per_contract: float | None
    would_auto_close: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MonitorReport:
    evaluated_at: str
    phase: int
    logic_version: str
    regime: str | None
    regime_allows_new_risk: bool
    positions: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rh_connected: bool = False
    rh_poll_skipped: bool = False
    rh_mcp_reviews: list[dict[str, Any]] = field(default_factory=list)
    paper_mode: str = "hypothetical"
    paper_mtm_usd: float | None = None
    paper_hypothetical_exits: list[dict[str, Any]] = field(default_factory=list)
    ta_snapshot: dict[str, Any] | None = None
    macro_weather_extras: dict[str, Any] | None = None
    uw_shadow: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _state_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    return open_ex_lock(lock_path)


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"positions": {}}
    lock = _state_lock(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"positions": {}}
    finally:
        flock_un(lock)
        lock.close()


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _state_lock(path)
    try:
        path.write_text(json.dumps(state, indent=2) + chr(10), encoding="utf-8")
    finally:
        flock_un(lock)
        lock.close()


def parse_expiration(raw: str) -> date | None:
    if not raw:
        return None
    s = str(raw)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def compute_dte(expiration: date, *, today: date | None = None) -> int:
    ref = today or datetime.now(ET).date()
    return (expiration - ref).days


def is_lane_a_contract(
    *,
    chain_symbol: str,
    option_type: str,
    expiration: date,
    rules: LaneRules,
    today: date | None = None,
) -> bool:
    sym = (chain_symbol or "").upper()
    if sym not in rules.chain_symbols:
        return False
    if (option_type or "").lower() != "call":
        return False
    month = f"{expiration.month:02d}"
    if month in rules.exclude_expiry_month:
        return False
    dte = compute_dte(expiration, today=today)
    return rules.dte_min <= dte <= rules.dte_max


def is_lane_a_monitor_contract(
    *,
    chain_symbol: str,
    option_type: str,
    expiration: date,
    rules: LaneRules,
    today: date | None = None,
) -> bool:
    """Exit monitoring — keep open holds even when DTE drops below entry dte_min."""
    sym = (chain_symbol or "").upper()
    if sym not in rules.chain_symbols:
        return False
    if (option_type or "").lower() != "call":
        return False
    month = f"{expiration.month:02d}"
    if month in rules.exclude_expiry_month:
        return False
    dte = compute_dte(expiration, today=today)
    return 0 <= dte <= rules.dte_max


def _first_present(*candidates: Any) -> Any:
    """Return the first value that is not None (preserves 0.0 / 0 / False)."""
    for value in candidates:
        if value is not None:
            return value
    return None


def classify_position(
    raw: dict[str, Any],
    rules: LaneRules,
    *,
    for_monitor: bool = False,
    today: date | None = None,
) -> LaneAPosition | None:
    chain = str(raw.get("chain_symbol") or raw.get("symbol") or "").upper()
    opt_type = str(raw.get("type") or raw.get("option_type") or "").lower()
    exp = parse_expiration(
        str(raw.get("expiration_date") or raw.get("expiration") or "")
    )
    if exp is None:
        return None
    eligible = (
        is_lane_a_monitor_contract(
            chain_symbol=chain,
            option_type=opt_type,
            expiration=exp,
            rules=rules,
            today=today,
        )
        if for_monitor
        else is_lane_a_contract(
            chain_symbol=chain,
            option_type=opt_type,
            expiration=exp,
            rules=rules,
            today=today,
        )
    )
    if not eligible:
        return None
    qty = float(raw.get("quantity") or raw.get("qty") or 0)
    if qty <= 0:
        return None
    avg = float(raw.get("average_price") or raw.get("avg_price") or 0)
    mark_raw = _first_present(
        raw.get("mark_price"), raw.get("mark"), raw.get("adjusted_mark_price")
    )
    mark = float(mark_raw) if mark_raw is not None else None
    pos_id = str(
        raw.get("id")
        or raw.get("option_id")
        or raw.get("url")
        or f"{chain}:{exp}:{raw.get('strike_price')}"
    )
    strike = float(raw.get("strike_price") or raw.get("strike") or 0)
    entry_mid = raw.get("entry_mid_premium")
    pos = LaneAPosition(
        position_id=pos_id,
        chain_symbol=chain,
        option_type=opt_type,
        strike=strike,
        expiration_date=exp,
        quantity=qty,
        average_price=avg,
        mark_price=mark,
        dte=compute_dte(exp, today=today),
        entry_mid_premium=float(entry_mid)
        if entry_mid is not None
        else (avg if avg > 0 else None),
        pnl_usd=None,
        pnl_per_contract=None,
    )
    _attach_economics_pnl(pos)
    return pos


def read_regime_detail() -> tuple[str | None, bool, float | None, str | None]:
    """Read regime, legacy risk gate, yellow-band fraction, and reason."""
    regime: str | None = None
    yellow_frac: float | None = None
    reason: str | None = None
    try:
        from xsp_killer.intel import IntelReader

        snap = IntelReader.read("intel:playbook_snapshot")
        if isinstance(snap, dict):
            regime = str(snap.get("regime") or snap.get("status") or "").upper() or None
            raw_frac = snap.get("yellow_frac")
            if raw_frac is not None:
                try:
                    yellow_frac = float(raw_frac)
                except (TypeError, ValueError):
                    yellow_frac = None
            reason = str(snap.get("reason") or snap.get("detail") or "").strip() or None
        elif isinstance(snap, str):
            regime = snap.upper()
    except Exception as exc:
        logger.warning("playbook_snapshot read failed: %s", exc)

    if not regime:
        try:
            from xsp_killer.macro_regime import classify_regime

            state = classify_regime()
            regime = state.regime
            yellow_frac = state.yellow_frac
            reason = state.reason
            logger.info("macro_regime fallback: %s (%s)", regime, state.reason)
        except Exception as exc:
            logger.warning("macro_regime fallback failed: %s", exc)
            return "UNKNOWN", False, None, None

    if regime in ("YELLOW", "RED"):
        return regime, False, yellow_frac, reason
    if regime == "GREEN":
        return regime, True, yellow_frac, reason
    return regime, False, yellow_frac, reason


def read_regime() -> tuple[str | None, bool]:
    """Backwards-compatible regime reader."""
    regime, ok, _, _ = read_regime_detail()
    return regime, ok


def regime_gate_allows(
    *,
    regime_gate: str,
    regime: str | None,
    regime_ok: bool,
    yellow_frac: float | None,
    ta_entry_ok: bool,
    yellow_frac_min: float = 0.75,
    yellow_require_bounce: bool = True,
) -> tuple[bool, str | None]:
    gate = (regime_gate or "GREEN").strip().upper()
    if gate == "GREEN":
        if regime_ok:
            return True, None
        return False, f"regime {regime} blocks new risk"

    if gate == "DIP_BOUNCE":
        # Dip-buy strategy: enter on a confirmed BB bounce regardless of regime.
        # The bounce confirmation (ta_entry_ok) is the safety — we only buy
        # weakness that has already turned up, never a free-falling knife.
        if ta_entry_ok:
            return True, None
        return False, "DIP_BOUNCE: no confirmed BB bounce"

    if gate == "GREEN_OR_YELLOW_BOUNCE":
        if regime_ok:
            return True, None
        if regime == "YELLOW":
            if yellow_frac is None:
                return False, "regime YELLOW blocks new risk: missing yellow_frac"
            if yellow_frac < yellow_frac_min:
                return (
                    False,
                    f"regime YELLOW blocks new risk: yellow_frac {yellow_frac:.2f} < {yellow_frac_min:.2f}",
                )
            if yellow_require_bounce and not ta_entry_ok:
                return False, "regime YELLOW blocks new risk: BB bounce not confirmed"
            return True, None
        return False, f"regime {regime} blocks new risk"

    logger.warning("unknown regime gate %s; defaulting to GREEN behavior", regime_gate)
    if regime_ok:
        return True, None
    return False, f"regime {regime} blocks new risk"



def xsp_session_open(now: datetime) -> bool:
    """True when Cboe XSP is tradeable (GTH, RTH, or Curb), America/New_York.

    GTH: 20:15 previous calendar evening through 09:25 (nearly 24x5).
    RTH: 09:30–16:15.
    Curb: 16:15–17:00.
    Gap 09:25–09:30 is not tradeable. Weekends closed except Sun evening GTH.
    """
    now = now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)
    wd = now.weekday()  # Mon=0 .. Sun=6
    t = now.time()

    # Saturday: only early morning leftovers of Fri overnight GTH (until 09:25)
    if wd == 5:
        return t <= time(9, 25)
    # Sunday: GTH starts 20:15
    if wd == 6:
        return t >= time(20, 15)

    # Monday–Friday
    if t >= time(20, 15) or t <= time(9, 25):
        return True  # GTH
    if time(9, 30) <= t <= time(16, 15):
        return True  # RTH
    if time(16, 15) < t <= time(17, 0):
        return True  # Curb
    return False


def in_no_sell_window(now: datetime, rules: LaneRules) -> bool:
    t = now.time()
    return rules.no_sell_start_et <= t < rules.no_sell_end_et


def in_sell_window(now: datetime, rules: LaneRules) -> bool:
    t = now.time()
    return rules.sell_eval_start_et <= t <= rules.sell_deadline_et


def _position_return_pct(pos: LaneAPosition) -> float | None:
    entry = (
        pos.entry_mid_premium
        if pos.entry_mid_premium is not None
        else pos.average_price
    )
    if entry <= 0 or pos.mark_price is None:
        return None
    return (pos.mark_price - entry) / entry


def _attach_economics_pnl(
    pos: LaneAPosition, *, rules_path: Path | None = None
) -> None:
    if pos.mark_price is None or pos.average_price <= 0:
        return
    try:
        from xsp_killer.paper_economics import (
            PaperEconomics,
            pnl_from_entry_fill,
            pnl_per_contract,
        )

        econ = PaperEconomics.from_yaml(rules_path or DEFAULT_RULES)
        entry_mid = pos.entry_mid_premium
        if entry_mid is not None and abs(pos.average_price - entry_mid) > 1e-6:
            pos.pnl_per_contract = pnl_from_entry_fill(
                entry_fill=pos.average_price,
                exit_mid=pos.mark_price,
                econ=econ,
            )
        elif entry_mid is not None:
            pos.pnl_per_contract = pnl_per_contract(
                entry_mid=entry_mid,
                exit_mid=pos.mark_price,
                econ=econ,
            )
        else:
            pos.pnl_per_contract = pnl_from_entry_fill(
                entry_fill=pos.average_price,
                exit_mid=pos.mark_price,
                econ=econ,
            )
        pos.pnl_usd = pos.pnl_per_contract * pos.quantity
    except Exception as exc:
        logger.warning("economics pnl failed: %s", exc)


def _entry_date_et(entry_ts: str | None) -> date | None:
    """Calendar entry date in America/New_York (for overnight hold logic)."""
    if not entry_ts:
        return None
    try:
        ts = datetime.fromisoformat(str(entry_ts).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(ET).date()
    except (ValueError, TypeError):
        return None


def evaluate_exit_alerts(
    pos: LaneAPosition,
    rules: LaneRules,
    *,
    now_et: datetime | None = None,
    ta_signal: Any | None = None,
    suppress_morning_cut_dte: int | None = None,
) -> list[ExitAlert]:
    """Exit when TP/SL/BB conditions hit whenever XSP session is open.

    No clock sell/no-sell window: if Cboe XSP is tradeable (GTH/RTH/curb) and
    sell conditions fire, exit. Daily morning time_stop removed. Swing-hold
    still near-expiry cuts via max_hold_dte. ``suppress_morning_cut_dte`` kept
    for shadow-bracket API compatibility (unused for prod exits).
    """
    now = now_et or datetime.now(ET)
    alerts: list[ExitAlert] = []
    _ = suppress_morning_cut_dte  # retained for call-site compatibility

    if not xsp_session_open(now):
        return alerts

    ret_pct = _position_return_pct(pos)
    if ret_pct is None:
        return alerts

    pnl_c = pos.pnl_per_contract
    pnl = pos.pnl_usd

    # Risk exits must fire even on a stale mark; never bank profit on suspect marks.
    allow_take_profit = not pos.mark_quote_stale

    if ret_pct <= -rules.stop_loss_pct:
        alerts.append(
            ExitAlert(
                position_id=pos.position_id,
                exit_reason="stop_loss",
                message=f"Stop loss {ret_pct * 100:.1f}% (limit -{rules.stop_loss_pct * 100:.0f}%)",
                pnl_usd=pnl,
                pnl_per_contract=pnl_c,
            )
        )
        return alerts

    if allow_take_profit and ret_pct >= rules.take_profit_pct:
        can_take = True
        if rules.require_upper_bb_for_take_profit and ta_signal is not None:
            touched = getattr(ta_signal, "upper_bb_touched", False)
            rejected = getattr(ta_signal, "exit_ok", False)
            if not touched and not rejected:
                can_take = False
        if can_take:
            reason: ExitReason = (
                "upper_bb_rejection"
                if ta_signal is not None and getattr(ta_signal, "exit_ok", False)
                else "take_profit"
            )
            detail = getattr(ta_signal, "detail", "") if ta_signal else ""
            alerts.append(
                ExitAlert(
                    position_id=pos.position_id,
                    exit_reason=reason,
                    message=(
                        f"Take profit {ret_pct * 100:.1f}% (target +{rules.take_profit_pct * 100:.0f}%)"
                        + (f" — {detail}" if detail else "")
                    ),
                    pnl_usd=pnl,
                    pnl_per_contract=pnl_c,
                )
            )
            return alerts

    if rules.swing_hold:
        # Hold for recovery: only force-exit near expiry.
        if pos.dte is not None and pos.dte <= rules.max_hold_dte:
            alerts.append(
                ExitAlert(
                    position_id=pos.position_id,
                    exit_reason="time_stop",
                    message=(
                        f"Near-expiry cut (DTE {pos.dte} <= {rules.max_hold_dte}, "
                        f"return {ret_pct * 100:.1f}%)"
                    ),
                    pnl_usd=pnl,
                    pnl_per_contract=pnl_c,
                )
            )
        return alerts

    # Baseline: no clock-forced morning cut — exit only on SL/TP/BB above.
    return alerts


def merge_state_tags(positions: list[LaneAPosition], state: dict[str, Any]) -> None:
    tags = (state.get("positions") or {}) if isinstance(state, dict) else {}
    for pos in positions:
        tag = tags.get(pos.position_id) or {}
        if tag.get("lane"):
            pos.lane = str(tag["lane"])
        if tag.get("entry_ts"):
            pos.entry_ts = str(tag["entry_ts"])
        if tag.get("delta_at_entry") is not None:
            pos.delta_at_entry = float(tag["delta_at_entry"])


def paper_positions_to_lane(
    raw_positions: list[dict[str, Any]],
    rules: LaneRules,
    *,
    today: date | None = None,
) -> list[LaneAPosition]:
    """Convert persisted paper positions into LaneAPosition for exit evaluation."""
    out: list[LaneAPosition] = []
    for raw in raw_positions:
        exp = parse_expiration(str(raw.get("expiration_date") or ""))
        if exp is None:
            continue
        chain = str(raw.get("chain_symbol") or "XSP").upper()
        opt_type = str(raw.get("option_type") or "call").lower()
        if not is_lane_a_monitor_contract(
            chain_symbol=chain,
            option_type=opt_type,
            expiration=exp,
            rules=rules,
            today=today,
        ):
            continue
        qty = float(raw.get("quantity") or 0)
        if qty <= 0:
            continue
        avg = float(raw.get("average_price") or 0)
        mark_raw = _first_present(raw.get("mark_price"), raw.get("mark"))
        mark = float(mark_raw) if mark_raw is not None else None
        entry_mid_raw = raw.get("entry_mid_premium")
        entry_mid = (
            float(entry_mid_raw)
            if entry_mid_raw is not None
            else (avg if avg > 0 else None)
        )
        pos_id = str(raw.get("position_id") or "")
        strike = float(raw.get("strike") or 0)
        lane_pos = LaneAPosition(
            position_id=pos_id,
            chain_symbol=chain,
            option_type=opt_type,
            strike=strike,
            expiration_date=exp,
            quantity=qty,
            average_price=avg,
            mark_price=mark,
            dte=compute_dte(exp, today=today),
            lane=str(raw.get("lane") or "A"),
            entry_ts=raw.get("entry_ts"),
            delta_at_entry=raw.get("delta_at_entry"),
            entry_mid_premium=entry_mid,
            mark_quote_stale=bool(raw.get("mark_quote_stale")),
            pnl_usd=None,
            pnl_per_contract=None,
        )
        _attach_economics_pnl(lane_pos)
        out.append(lane_pos)
    return out


def compute_paper_open_mtm(
    state: dict[str, Any],
    *,
    rules_path: Path | None = None,
) -> tuple[float, float | None]:
    """Scaled and 1× open-position MTM from persisted paper positions."""
    open_positions = [
        p
        for p in (state.get("paper_positions") or {}).values()
        if isinstance(p, dict) and p.get("status", "open") == "open"
    ]
    if not open_positions:
        return 0.0, 0.0
    rules = LaneRules.from_yaml(rules_path or DEFAULT_RULES)
    classified = paper_positions_to_lane(
        open_positions,
        rules,
        today=datetime.now(ET).date(),
    )
    mtm_scaled = round(sum(float(pos.pnl_usd or 0.0) for pos in classified), 2)
    scale = load_premium_scale(rules_path or DEFAULT_RULES)
    mtm_1x = round(mtm_scaled / scale, 2) if scale else None
    return mtm_scaled, mtm_1x


def refresh_paper_marks(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Update mark_price on open paper positions via per-strike SPY chain proxy."""
    try:
        from xsp_killer.lane_a_entry import estimate_fallback_premium, fetch_spx_proxy
        from xsp_killer.spy_quote import (
            fetch_spy_call_quote,
            xsp_strike_to_spy_chain_strike,
        )
    except ImportError:
        return positions

    now_iso = datetime.now(timezone.utc).isoformat()
    spx = fetch_spx_proxy()
    updated: list[dict[str, Any]] = []
    for raw in positions:
        pos = dict(raw)
        exp = parse_expiration(str(pos.get("expiration_date") or ""))
        strike = float(pos.get("strike") or 0)
        if exp is None or strike <= 0:
            updated.append(pos)
            continue
        dte = compute_dte(exp)
        entry_mid_raw = pos.get("entry_mid_premium")
        entry_mid = float(entry_mid_raw) if entry_mid_raw is not None else None
        last_raw = pos.get("last_mark_price")
        last_mark = float(last_raw) if last_raw is not None else None
        quote = fetch_spy_call_quote(
            xsp_strike_to_spy_chain_strike(strike),
            exp,
            entry_mid_xsp=entry_mid,
            last_mark_xsp=last_mark,
        )
        if quote.exit_mark_xsp is not None:
            pos["mark_mid_xsp"] = quote.mark_xsp
            pos["mark_price"] = quote.exit_mark_xsp
            pos["mark_quote_stale"] = quote.stale
            pos["mark_stale_reason"] = quote.stale_reason
            pos["spy_row_strike"] = quote.spy_row_strike
            pos["last_mark_price"] = quote.exit_mark_xsp
            pos["last_mark_at"] = now_iso
        elif spx is not None:
            spy_px = spx / 10.0
            fb = estimate_fallback_premium(
                spy_px, dte, xsp_strike=strike, spx_level=spx
            )
            pos["mark_price"] = round(fb, 4)
            pos["mark_quote_stale"] = True
            pos["mark_stale_reason"] = "fallback_estimate"
        else:
            pos["mark_quote_stale"] = True
            pos["mark_stale_reason"] = "no_quote"
        updated.append(pos)
    return updated


def close_paper_positions_on_exit(
    state: dict[str, Any],
    alerts: list[ExitAlert],
    *,
    evaluated_at: str,
    logic_version: str,
    spx_at_exit: float | None = None,
) -> list[dict[str, Any]]:
    """Mark paper positions closed on first exit alert of the session."""
    paper = state.get("paper_positions") or {}
    if not isinstance(paper, dict):
        return []
    closed: list[dict[str, Any]] = []
    seen_ids = {a.position_id for a in alerts}
    for pos_id, raw in list(paper.items()):
        if not isinstance(raw, dict) or raw.get("status") != "open":
            continue
        if pos_id not in seen_ids:
            continue
        alert = next((a for a in alerts if a.position_id == pos_id), None)
        raw = dict(raw)
        raw["status"] = "closed"
        raw["exit_ts"] = evaluated_at
        raw["exit_reason"] = alert.exit_reason if alert else "manual"
        raw["exit_pnl_usd"] = alert.pnl_usd if alert else None
        raw["exit_pnl_per_contract"] = alert.pnl_per_contract if alert else None
        raw["spx_at_exit"] = spx_at_exit
        entry_spx_raw = raw.get("spx_at_entry")
        try:
            entry_spx = float(entry_spx_raw) if entry_spx_raw is not None else None
        except (TypeError, ValueError):
            entry_spx = None
        if (
            entry_spx is not None
            and entry_spx > 0
            and spx_at_exit is not None
            and spx_at_exit > 0
        ):
            raw["spy_drift_pct"] = round(
                (spx_at_exit - entry_spx) / entry_spx * 100.0, 4
            )
        paper[pos_id] = raw
        closed.append(raw)
        events = list(state.get("paper_events") or [])
        day_key = evaluated_at[:10]
        seen = {
            (
                e.get("position_id"),
                e.get("exit_reason"),
                (e.get("evaluated_at") or "")[:10],
            )
            for e in events
        }
        evt_key = (pos_id, raw["exit_reason"], day_key)
        if evt_key not in seen:
            events.append(
                {
                    "evaluated_at": evaluated_at,
                    "position_id": pos_id,
                    "exit_reason": raw["exit_reason"],
                    "paper_pnl_usd": raw.get("exit_pnl_usd"),
                    "paper_pnl_per_contract": raw.get("exit_pnl_per_contract"),
                    "logic_version": logic_version,
                    "paper_mode": "automated_paper_close",
                    "entry_ts": raw.get("entry_ts"),
                }
            )
            state["paper_events"] = events[-500:]
    state["paper_positions"] = paper
    return closed


def load_open_paper_positions(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("paper_positions") or {}
    if not isinstance(raw, dict):
        return []
    open_rows = [
        p
        for p in raw.values()
        if isinstance(p, dict) and p.get("status", "open") == "open"
    ]
    return refresh_paper_marks(open_rows)


_OPTION_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _real_option_id(pos: "LaneAPosition") -> str | None:
    """Return the Robinhood option UUID for a position, or None for paper.

    Paper positions carry synthetic ids (``paper:XSP:...``) with SPX-scaled
    strikes that do not map to a tradeable XSP instrument, so they cannot be
    reviewed against the live endpoint.
    """
    pid = str(pos.position_id or "")
    return pid if _OPTION_UUID_RE.match(pid) else None


def _phase1_canary_enabled() -> bool:
    return os.getenv("XSP_LANE_A_PHASE1_CANARY", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# Fixed namespace so a logical exit (position + trading day + reason) maps to a
# stable ref_id — the broker dedupes on it across the 4 morning monitor runs.
_EXIT_REF_NAMESPACE = uuid.UUID("7d5a6c2e-3b41-4e0a-9c2d-000000000001")


def _exit_ref_id(option_id: str, day: str, exit_reason: str) -> str:
    return str(uuid.uuid5(_EXIT_REF_NAMESPACE, f"{option_id}:{day}:{exit_reason}"))


def _build_close_order(option_id: str, pos: "LaneAPosition") -> dict[str, Any]:
    """Sell-to-close legs[] order: limit at mark, market when no mark."""
    qty_int = max(1, int(round(pos.quantity or 1)))
    order: dict[str, Any] = {
        "legs": [
            {
                "option_id": option_id,
                "side": "sell",
                "position_effect": "close",
                "ratio_quantity": 1,
            }
        ],
        "quantity": str(qty_int),
        "time_in_force": "gfd",
    }
    if pos.mark_price is not None:
        order["type"] = "limit"
        order["price"] = f"{float(pos.mark_price):.2f}"
    else:
        order["type"] = "market"
    return order


def dry_run_exit_reviews_via_mcp(
    alerts: list["ExitAlert"],
    positions: list["LaneAPosition"],
    *,
    variant_monitor: bool = False,
    variant_id: str | None = None,
) -> list[dict[str, Any]]:
    """Exit signal handoff to Robinhood MCP: always review, place when live.

    Invariants:
    - Paper synthetic positions (non-UUID ids) are skipped with a recorded
      ``skipped`` note; only real Robinhood option UUIDs are acted on.
    - Every real exit reviews first (``review_option_order``) for an audited
      preview, then places (``place_option_order``) ONLY when live exits are
      enabled and the kill switch is clear; otherwise it stays review-only.
    - Live places require hard human variant review (``XSP_LANE_A_LIVE_VARIANT_ID``
      + ``XSP_LANE_A_LIVE_HUMAN_ACK`` + ack file) for that exact variant; paper
      synthetic positions never place.
    - Live placement uses a deterministic ``ref_id`` per (option, day, reason)
      so the 4 morning monitor runs can't create duplicate exit orders.
    - When nothing is reviewable, a single buy-to-open proof-of-life canary
      review runs (gated by ``XSP_LANE_A_PHASE1_CANARY``); the canary never
      places an order.
    """
    if not rh_mcp_enabled():
        return []
    pos_by_id = {p.position_id: p for p in positions}
    adapter = RobinhoodMCPAdapter()
    live = live_exits_enabled(config=adapter.config) and not kill_switch_engaged()
    if live:
        from xsp_killer.live_gates import human_variant_review_allows

        # Variant monitors: ack must match this variant. Baseline uses
        # LIVE_VARIANT_ID as the promoted id (must still dual-ack).
        check_id = (variant_id or "").strip() or os.getenv(
            "XSP_LANE_A_LIVE_VARIANT_ID", ""
        )
        ok_review, _reason = human_variant_review_allows(check_id)
        if not ok_review:
            live = False
    day = datetime.now(ET).date().isoformat()
    reviews: list[dict[str, Any]] = []
    reviewable = 0
    for alert in alerts:
        pos = pos_by_id.get(alert.position_id)
        if pos is None:
            continue
        option_id = _real_option_id(pos)
        if option_id is None:
            reviews.append(
                {
                    "position_id": alert.position_id,
                    "exit_reason": alert.exit_reason,
                    "skipped": "paper synthetic position — no live instrument",
                }
            )
            continue
        order = _build_close_order(option_id, pos)
        entry: dict[str, Any] = {
            "position_id": alert.position_id,
            "exit_reason": alert.exit_reason,
            "live": live,
        }
        try:
            entry["review"] = adapter.review_option_order(order)
            reviewable += 1
            if live:
                place_order = {
                    **order,
                    "ref_id": _exit_ref_id(option_id, day, alert.exit_reason),
                }
                entry["placed"] = adapter.place_option_order(place_order)
            reviews.append(entry)
        except (RhMcpError, Exception) as exc:
            entry["error"] = str(exc)
            reviews.append(entry)
    if reviewable == 0 and _phase1_canary_enabled():
        try:
            canary = adapter.phase1_canary_review()
            reviews.append({"canary": True, "no_order_placed": True, **canary})
        except Exception as exc:
            reviews.append({"canary": True, "error": str(exc)})
    return reviews


def append_paper_pnl_log(
    *,
    report: MonitorReport,
    classified: list[LaneAPosition],
    alerts: list[ExitAlert],
    log_path: Path | None = None,
) -> None:
    """Append hypothetical paper PnL row (no RH capital required for logging)."""
    path = log_path or DEFAULT_PAPER_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    mtm = sum(p.pnl_usd or 0.0 for p in classified)
    report.paper_mtm_usd = mtm if classified else 0.0
    row = {
        "ts": report.evaluated_at,
        "event": "monitor_eval",
        "logic_version": report.logic_version,
        "phase": report.phase,
        "paper_mode": report.paper_mode,
        "positions_n": len(classified),
        "paper_mtm_usd": report.paper_mtm_usd,
        "alerts_n": len(alerts),
        "positions": [p.to_dict() for p in classified],
        "alerts": [a.to_dict() for a in alerts],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def record_paper_exit_signals(
    state: dict[str, Any],
    alerts: list[ExitAlert],
    *,
    evaluated_at: str,
    logic_version: str,
) -> list[dict[str, Any]]:
    """First alert per position+reason per ET day → hypothetical paper exit."""
    events: list[dict[str, Any]] = list(state.get("paper_events") or [])
    seen = {
        (e.get("position_id"), e.get("exit_reason"), (e.get("evaluated_at") or "")[:10])
        for e in events
    }
    new_exits: list[dict[str, Any]] = []
    day_key = evaluated_at[:10]
    for alert in alerts:
        key = (alert.position_id, alert.exit_reason, day_key)
        if key in seen:
            continue
        evt = {
            "evaluated_at": evaluated_at,
            "position_id": alert.position_id,
            "exit_reason": alert.exit_reason,
            "paper_pnl_usd": alert.pnl_usd,
            "paper_pnl_per_contract": alert.pnl_per_contract,
            "logic_version": logic_version,
            "paper_mode": "hypothetical_would_close",
        }
        events.append(evt)
        new_exits.append(evt)
        seen.add(key)
    if new_exits:
        state["paper_events"] = events[-500:]
    return new_exits


def write_paper_pnl_brief(
    state: dict[str, Any],
    *,
    report: MonitorReport | None = None,
    out_path: Path | None = None,
    logic_version: str | None = None,
) -> Path:
    """Baseline production lane only — variant PnL lives in variants scoreboard."""
    epoch_at = state.get("pnl_epoch_at") or state.get("soak_reset_at")
    events = [
        e
        for e in (state.get("paper_events") or [])
        if isinstance(e, dict)
        and (not epoch_at or str(e.get("evaluated_at") or "") >= str(epoch_at))
    ]
    resolved_pnl = sum(float(e.get("paper_pnl_usd") or 0) for e in events)
    path = out_path or DEFAULT_PAPER_BRIEF
    scale = load_premium_scale()
    mtm_scaled = report.paper_mtm_usd if report else None
    mtm_1x: float | None = None
    if mtm_scaled is None:
        mtm_scaled, mtm_1x = compute_paper_open_mtm(state)
    resolved_logic_version = (
        (report.logic_version if report else None)
        or logic_version
        or str(state.get("logic_version") or "").strip()
        or LaneRules.from_yaml(DEFAULT_RULES).logic_version
    )
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "baseline_prod_only",
        "logic_version": resolved_logic_version,
        "paper_mode": "hypothetical",
        "note": (
            "Production baseline lane only. Shadow variant comparison: "
            "briefs/xsp-lane-a-variants-scoreboard.json (per-variant, not summed). "
            "open_positions_mtm_usd uses premium_scale; "
            "open_positions_mtm_usd_1x is SPY-proxy 1×."
        ),
        "pnl_epoch_at": epoch_at,
        "premium_scale_used": scale,
        "open_positions_mtm_usd": mtm_scaled,
        "open_positions_mtm_usd_1x": (
            round(mtm_scaled / scale, 2)
            if mtm_1x is None and mtm_scaled is not None and scale
            else mtm_1x
        ),
        "hypothetical_exits_n": len(events),
        "hypothetical_realized_pnl_usd": round(resolved_pnl, 2),
        "latest_evaluated_at": report.evaluated_at if report else None,
        "recent_exits": events[-10:],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def run_monitor(
    *,
    rules_path: Path | None = None,
    state_path: Path | None = None,
    positions_override: list[dict[str, Any]] | None = None,
    now_et: datetime | None = None,
    publish_intel: bool = True,
    ta_signal: Any | None = None,
    fetch_ta: bool = True,
    log_path: Path | None = None,
    paper_brief_path: Path | None = None,
    write_paper_brief: bool = True,
) -> MonitorReport:
    rules = LaneRules.from_yaml(rules_path or DEFAULT_RULES)
    state = load_state(state_path or DEFAULT_STATE)
    regime, regime_ok, _, _ = read_regime_detail()

    suppress_dte: int | None = None
    if fetch_ta or ta_signal is not None:
        try:
            from xsp_killer.lane_a_ta import TaRules, evaluate_ta_signals

            ta_rules = TaRules.from_yaml(rules_path or DEFAULT_RULES)
            suppress_dte = ta_rules.suppress_morning_cut_dte_gte
            if ta_signal is None and fetch_ta:
                ta_signal = evaluate_ta_signals(
                    ta_rules, now_et=now_et or datetime.now(ET)
                )
        except Exception as exc:
            ta_signal = None
            logger.warning("TA evaluation skipped: %s", exc)

    report = MonitorReport(
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        phase=0,
        logic_version=rules.logic_version,
        regime=regime,
        regime_allows_new_risk=regime_ok,
    )
    if ta_signal is not None and hasattr(ta_signal, "to_dict"):
        report.ta_snapshot = ta_signal.to_dict()

    try:
        from xsp_killer.macro_weather_notes import build_monitor_macro_weather_extras

        report.macro_weather_extras = build_monitor_macro_weather_extras()
        if report.macro_weather_extras:
            logger.info(
                "k155 macro_weather_extras attached (log-only): event_cluster=%s",
                report.macro_weather_extras.get("event_cluster"),
            )
    except Exception as exc:
        logger.info("k155 macro weather extras skipped: %s", exc)

    try:
        from xsp_killer.uw_shadow import build_monitor_uw_shadow

        report.uw_shadow = build_monitor_uw_shadow(now_et=now_et)
        if report.uw_shadow:
            logger.info(
                "uw_shadow attached (log-only): flow_bias=%s npt_bias=%s wall=%s iv_rank=%s",
                (report.uw_shadow.get("flow") or {}).get("net_prem_bias"),
                (report.uw_shadow.get("net_prem") or {}).get("net_prem_bias"),
                (report.uw_shadow.get("gex") or {}).get("wall_side"),
                (report.uw_shadow.get("iv_rank") or {}).get("iv_rank_1y"),
            )
    except Exception as exc:
        logger.info("uw_shadow skipped: %s", exc)

    today = (now_et or datetime.now(ET)).date()

    paper_raw: list[dict[str, Any]] = []
    if state.get("paper_positions"):
        report.paper_mode = "automated_paper"
    if state.get("paper_positions") and not positions_override:
        from xsp_killer.lane_a_entry import reap_expired_paper_positions

        reap_expired_paper_positions(
            state,
            state_path=state_path or DEFAULT_STATE,
            evaluated_at=report.evaluated_at,
            today=today,
        )
        paper_raw = load_open_paper_positions(state)
        for pr in paper_raw:
            # Persist refreshed marks back into state.
            pid = pr.get("position_id")
            if pid and isinstance(state.get("paper_positions"), dict):
                state["paper_positions"][pid] = pr

    raw_positions: list[dict[str, Any]]
    if positions_override is not None:
        raw_positions = positions_override
        report.rh_connected = True
    elif not rh_read_enabled():
        raw_positions = []
        report.rh_poll_skipped = True
    else:
        raw_positions, err = fetch_robinhood_option_positions()
        if err:
            report.errors.append(err)
        else:
            report.rh_connected = True

    classified: list[LaneAPosition] = []
    for raw in raw_positions:
        pos = classify_position(raw, rules, for_monitor=True, today=today)
        if pos is not None:
            classified.append(pos)

    # Paper ids are ``paper:...``; RH ids are UUIDs — always merge both books.
    if state.get("paper_positions") and not positions_override:
        classified.extend(paper_positions_to_lane(paper_raw, rules, today=today))

    merge_state_tags(classified, state)
    report.positions = [p.to_dict() for p in classified]

    try:
        from xsp_killer.exit_shadow import mark_virtual_holds

        mark_virtual_holds(
            state,
            now_et=now_et or datetime.now(ET),
            rules=rules,
            ta_signal=ta_signal,
            suppress_morning_cut_dte=suppress_dte,
            evaluate_fn=evaluate_exit_alerts,
        )
    except Exception as exc:
        report.errors.append(f"shadow virtual hold mark failed: {exc}")

    all_alerts: list[ExitAlert] = []
    for pos in classified:
        all_alerts.extend(
            evaluate_exit_alerts(
                pos,
                rules,
                now_et=now_et,
                ta_signal=ta_signal,
                suppress_morning_cut_dte=suppress_dte,
            )
        )

    report.alerts = [a.to_dict() for a in all_alerts]
    # Variant monitors (write_paper_brief=False or XSP_LANE_A_VARIANT_MONITOR=1)
    # skip the phase-1 MCP canary when there is nothing to review — avoids
    # N-variants × cron spam of buy-to-open proof-of-life previews.
    _variant_monitor = (not write_paper_brief) or os.getenv(
        "XSP_LANE_A_VARIANT_MONITOR", ""
    ).strip().lower() in ("1", "true", "yes", "on")
    _has_rh_positions = any(_real_option_id(p) for p in classified)
    if _variant_monitor and not all_alerts and not _has_rh_positions:
        report.rh_mcp_reviews = []
    else:
        report.rh_mcp_reviews = dry_run_exit_reviews_via_mcp(
            all_alerts,
            classified,
            variant_monitor=_variant_monitor,
            variant_id=rules.logic_version,
        )

    paper_positions_active = bool(state.get("paper_positions")) and not positions_override
    if paper_positions_active:
        try:
            from xsp_killer.lane_a_entry import fetch_spx_proxy

            spx_at_exit = fetch_spx_proxy()
        except Exception:
            spx_at_exit = None
        closed_paper = close_paper_positions_on_exit(
            state,
            all_alerts,
            evaluated_at=report.evaluated_at,
            logic_version=rules.logic_version,
            spx_at_exit=spx_at_exit,
        )
        report.paper_hypothetical_exits = [
            {
                "evaluated_at": report.evaluated_at,
                "position_id": c.get("position_id"),
                "exit_reason": c.get("exit_reason"),
                "paper_pnl_usd": c.get("exit_pnl_usd"),
                "paper_pnl_per_contract": c.get("exit_pnl_per_contract"),
                "paper_mode": "automated_paper_close",
            }
            for c in closed_paper
        ]
        if all_alerts:
            try:
                from xsp_killer.exit_shadow import (
                    append_shadow_exit_log,
                    build_shadow_exit_record,
                    open_virtual_holds,
                )

                now_local = now_et or datetime.now(ET)
                for alert in all_alerts:
                    pos_obj = next(
                        (p for p in classified if p.position_id == alert.position_id),
                        None,
                    )
                    if pos_obj is None:
                        continue
                    shadow_rec = build_shadow_exit_record(
                        pos_obj,
                        rules,
                        now_et=now_local,
                        ta_signal=ta_signal,
                        suppress_morning_cut_dte=suppress_dte,
                        actual_alert=alert,
                        evaluated_at=report.evaluated_at,
                        evaluate_fn=evaluate_exit_alerts,
                    )
                    append_shadow_exit_log(shadow_rec, state=state)
                    open_virtual_holds(
                        state,
                        pos_obj,
                        shadow_rec,
                        rules,
                        actual_alert=alert,
                    )
            except Exception as exc:
                report.errors.append(f"shadow exit log failed: {exc}")
    else:
        report.paper_hypothetical_exits = record_paper_exit_signals(
            state,
            all_alerts,
            evaluated_at=report.evaluated_at,
            logic_version=rules.logic_version,
        )
    append_paper_pnl_log(
        report=report, classified=classified, alerts=all_alerts, log_path=log_path
    )
    if write_paper_brief:
        write_paper_pnl_brief(
            state,
            report=report,
            out_path=paper_brief_path,
            logic_version=rules.logic_version,
        )

    if publish_intel and all_alerts:
        try:
            from xsp_killer.intel import IntelPublisher

            IntelPublisher.publish(
                "intel:xsp_lane_a_alert",
                {
                    "evaluated_at": report.evaluated_at,
                    "alerts": report.alerts,
                    "positions_n": len(classified),
                    "logic_version": rules.logic_version,
                },
                source_system="xsp_lane_a_monitor",
                confidence=1.0,
                ttl=3600,
            )
        except Exception as exc:
            report.errors.append(f"intel publish failed: {exc}")

    # Persist state (position tags + paper_events)
    if classified:
        tags = state.setdefault("positions", {})
        for pos in classified:
            prev = tags.get(pos.position_id) or {}
            tags[pos.position_id] = {
                **prev,
                "lane": pos.lane,
                "last_seen": report.evaluated_at,
                "dte": pos.dte,
                "strike": pos.strike,
                "chain_symbol": pos.chain_symbol,
            }
    save_state(state_path or DEFAULT_STATE, state)

    return report


def write_report(report: MonitorReport, out_path: Path | None = None) -> Path:
    path = out_path or DEFAULT_OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path
